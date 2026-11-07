"""Local experimental browser playground, independent of provider implementations."""

import json
import ipaddress
import math
import secrets
import socket
import sqlite3
import threading
import time
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from platosi.cancellation import Cancellation, Cancelled
from platosi.inquiry import INSTRUCTIONS, inquire, model_provider
from platosi.profiles import Profiles
from platosi.reader_api import ReaderApi
from platosi.registry import Registry
from platosi.word_models import Examination
from platosi.word_reader import WordReader, tokens


DEFAULT_PROMPT = """Listen carefully to what I actually say. Ground your observations in the material I provide. Explore meaningful symbolic, linguistic, structural, and philosophical connections while distinguishing observation from speculation. Do not impose a predetermined framework or reflexively correct or dismiss my interpretations. Respond substantively; ask questions only when clarification would genuinely help. Treat me as an independent thinker. Do not impose conventional dream interpretation frameworks unless I request them."""
WEB_DIR = Path(__file__).resolve().parents[2] / "playground"
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(network) for network in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def private_ipv4(address):
    try:
        ip = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        return False
    return any(ip in network for network in PRIVATE_NETWORKS)


def lan_addresses():
    addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
    return sorted({entry[4][0] for entry in addresses if private_ipv4(entry[4][0])})


class Playground:
    def __init__(self, root):
        self.root = Path(root)
        self.jobs = {}
        self.lock = threading.Lock()
        self.reader = WordReader(root)
        self.lookup = ReaderApi(root)
        self.examination = Examination(root)


    def bootstrap(self):
        registry = Registry(self.root)
        providers = []
        errors = []
        for registration in registry.providers.values():
            manifest = registration.manifest
            if manifest["type"] != "language-model" or "chat" not in manifest["capabilities"]:
                continue
            if not registration.enabled:
                continue
            try:
                provider = registration.load()
                if not provider.available():
                    errors.append(f"{manifest['id']}: unavailable")
                    continue
                providers.append({"id": manifest["id"], "models": provider.list_models()})
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f"{manifest['id']}: {error}")
        return {"default_prompt": DEFAULT_PROMPT, "grounding_instructions": INSTRUCTIONS,
                "models": providers, "model_errors": errors,
                "profiles": list(Profiles(self.root).profiles),
                "resources": [s for s in registry.statuses(check_availability=False)
                              if s["type"] != "language-model"]}

    @staticmethod
    def validate(payload):
        if not isinstance(payload, dict):
            raise ValueError("Request must be a JSON object")
        for field in ("provider", "model", "system_prompt", "mode"):
            if not isinstance(payload.get(field), str):
                raise ValueError(f"{field} must be a string")
        if not payload["provider"] or not payload["model"]:
            raise ValueError("Select a model provider and model")
        if payload["mode"] not in ("free", "grounded"):
            raise ValueError("Unknown conversation mode")
        temperature = payload.get("temperature")
        if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
                or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ValueError("Temperature must be between 0 and 2")
        max_tokens = payload.get("max_tokens")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 8192:
            raise ValueError("Maximum response tokens must be an integer between 1 and 8192")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("At least one message is required")
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {"role", "content"}
                    or message["role"] not in ("user", "assistant")
                    or not isinstance(message["content"], str) or not message["content"].strip()):
                raise ValueError("Messages must have a user or assistant role and nonempty text")
        if messages[-1]["role"] != "user":
            raise ValueError("The last message must be from the reader")
        if payload["mode"] == "grounded":
            for field in ("profile", "text", "edition", "citation", "headword", "form"):
                if not isinstance(payload.get(field, ""), str):
                    raise ValueError(f"{field} must be a string")
            include = payload.get("include", [])
            if not isinstance(include, list) or any(not isinstance(item, str) or not item for item in include):
                raise ValueError("Included resources must be provider IDs")

    def start(self, payload):
        self.validate(payload)
        cancellation = Cancellation()
        job_id = secrets.token_urlsafe(24)
        job = {"status": "running", "cancellation": cancellation, "created": time.monotonic()}
        with self.lock:
            cutoff = time.monotonic() - 300
            self.jobs = {k: v for k, v in self.jobs.items()
                         if v["status"] == "running" or v["created"] > cutoff}
            self.jobs[job_id] = job
        threading.Thread(target=self.run, args=(job, payload), daemon=True).start()
        return job_id

    def start_examination(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Request must be a JSON object")
        for field in ("corpus", "edition", "scope", "start", "models", "settings"):
            if field not in payload:
                raise ValueError(f"Missing {field}")
        cancellation = Cancellation()
        job_id = secrets.token_urlsafe(24)
        job = {"status": "running", "cancellation": cancellation, "created": time.monotonic()}
        with self.lock:
            cutoff = time.monotonic() - 300
            self.jobs = {k: v for k, v in self.jobs.items()
                         if v["status"] == "running" or v["created"] > cutoff}
            self.jobs[job_id] = job
        threading.Thread(target=self.run_examination, args=(job, payload), daemon=True).start()
        return job_id




    def run_examination(self, job, payload):
        cancellation = job["cancellation"]
        try:
            local = self.reader.explore(payload)
            result = self.examination.run(self.reader._registry(), local, payload["models"],
                                          payload["settings"], payload.get("fresh", False), cancellation)
            cancellation.check()
            with self.lock:
                if job["status"] == "running":
                    job.update(status="complete", result=result)
        except Cancelled:
            with self.lock:
                job["status"] = "cancelled"
        except Exception as error:
            with self.lock:
                if job["status"] == "running":
                    job.update(status="error", error=f"{type(error).__name__}: {error}")

    def run(self, job, payload):
        cancellation = job["cancellation"]
        try:
            registry = Registry(self.root)
            registration, provider = model_provider(registry, payload["provider"], "chat")
            cancellation.check()
            options = {"model": payload["model"], "generation": {"temperature": payload["temperature"]},
                       "max_tokens": payload["max_tokens"]}
            messages = [{"role": "system", "content": payload["system_prompt"]}]
            if payload["mode"] == "free":
                messages.extend(payload["messages"])
                response = provider.chat(messages, options, cancellation)
                if not isinstance(response, dict) or not isinstance(response.get("text"), str) or not response["text"].strip():
                    raise ValueError("Model provider returned an invalid response")
                result = {"answer": response["text"], "evidence": [], "warnings": [],
                          "model": {"provider": registration.manifest["id"],
                                    "model": response.get("model", payload["model"])}}
                if response.get("done_reason") == "length":
                    result["warnings"].append("The response reached the model's generation limit.")
            else:
                profile = Profiles(self.root).get(payload["profile"]) if payload.get("profile") else None
                messages.extend(payload["messages"][:-1])

                def generate_chat(selected_provider, prompt, chat_options):
                    cancellation.check()
                    return selected_provider.chat(messages + [{"role": "user", "content": prompt}],
                                                  {**chat_options, "max_tokens": payload["max_tokens"]},
                                                  cancellation)

                result = inquire(
                    registry, payload["messages"][-1]["content"], profile=profile,
                    include=payload.get("include", []), text=payload.get("text") or None,
                    edition=payload.get("edition") or None, citation=payload.get("citation") or None,
                    headwords=[payload["headword"]] if payload.get("headword") else None,
                    forms=[payload["form"]] if payload.get("form") else None,
                    model_id=payload["provider"], model=payload["model"],
                    generation=options["generation"], generate_response=generate_chat)
            cancellation.check()
            with self.lock:
                if job["status"] == "running":
                    job.update(status="complete", result=result)
        except Cancelled:
            with self.lock:
                job["status"] = "cancelled"
        except Exception as error:
            with self.lock:
                if job["status"] == "running":
                    job.update(status="error", error=f"{type(error).__name__}: {error}")

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError("Unknown generation")
            return {k: job[k] for k in ("status", "result", "error") if k in job}

    def stop(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError("Unknown generation")
            if job["status"] != "running":
                return job["status"]
            job["status"] = "cancelled"
        job["cancellation"].cancel()
        return "cancelled"


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, playground, *, lan=False, addresses=None, access_token=None):
        if address[0] != ("0.0.0.0" if lan else "127.0.0.1"):
            raise ValueError("Playground must bind to loopback, or 0.0.0.0 in LAN mode")
        super().__init__(address, Handler)
        self.playground = playground
        self.lan = lan
        self.addresses = set(addresses if addresses is not None else (lan_addresses() if lan else []))
        if any(not private_ipv4(address) for address in self.addresses):
            self.server_close()
            raise ValueError("LAN host addresses must be private IPv4 addresses")
        self.access_token = (access_token if access_token is not None else secrets.token_urlsafe(24)) if lan else None
        if lan and (not isinstance(self.access_token, str) or not self.access_token):
            self.server_close()
            raise ValueError("LAN mode requires a nonempty access token")
        self.sessions = set()
        self.sessions_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def headers_common(self, content_type, length):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.headers_common("application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def valid_host(self):
        host = self.headers.get("Host", "")
        allowed = {"127.0.0.1"} | self.server.addresses
        if host not in {f"{address}:{self.server.server_port}" for address in allowed}:
            return False
        client = self.client_address[0]
        return client == "127.0.0.1" or (self.server.lan and private_ipv4(client))

    def authenticated(self):
        if not self.server.lan:
            return True
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        session = cookies.get("platosi_session")
        with self.server.sessions_lock:
            return session is not None and session.value in self.server.sessions

    def send_file(self, filename, content_type):
        body = (WEB_DIR / filename).read_bytes()
        self.send_response(200)
        self.headers_common(content_type, len(body))
        self.wfile.write(body)

    def login(self):
        try:
            if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                raise ValueError("Expected form data")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid form length")
            form = parse_qs(self.rfile.read(length).decode("utf-8"), strict_parsing=True)
            tokens = form.get("token", [])
            if len(tokens) != 1 or not secrets.compare_digest(
                    tokens[0].encode("utf-8"), self.server.access_token.encode("utf-8")):
                self.send_json(403, {"error": "Invalid access token"})
                return
            session = secrets.token_urlsafe(32)
            with self.server.sessions_lock:
                self.server.sessions.add(session)
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"platosi_session={session}; Path=/; HttpOnly; SameSite=Strict")
            self.headers_common("text/plain; charset=utf-8", 0)
        except (ValueError, UnicodeError) as error:
            self.send_json(400, {"error": str(error)})

    def do_GET(self):
        if not self.valid_host():
            self.send_json(403, {"error": "Invalid host"})
            return
        path = urlsplit(self.path).path
        if self.server.lan and not self.authenticated():
            if path == "/":
                self.send_file("login.html", "text/html; charset=utf-8")
            elif path == "/style.css":
                self.send_file("style.css", "text/css; charset=utf-8")
            else:
                self.send_json(401, {"error": "Authentication required"})
            return
        static = {"/": ("lookup.html", "text/html; charset=utf-8"),
                  "/conversation": ("index.html", "text/html; charset=utf-8"),
                  "/reader": ("reader.html", "text/html; charset=utf-8"),
                  "/lookup.js": ("lookup.js", "text/javascript; charset=utf-8"),
                  "/reader.js": ("reader.js", "text/javascript; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path in static:
            filename, content_type = static[path]
            self.send_file(filename, content_type)
        elif path == "/api/bootstrap":
            try:
                self.send_json(200, self.server.playground.bootstrap())
            except (OSError, ValueError, RuntimeError) as error:
                self.send_json(500, {"error": str(error)})
        elif path == "/api/reader/options":
            try:
                registry = self.server.playground.reader._registry()
                self.send_json(200, {
                    "profiles": list(Profiles(self.server.playground.root).profiles),
                    "resources": [{k: v for k, v in resource.items() if k != "config"}
                                  for resource in registry.statuses(check_availability=False)],
                })
            except (OSError, ValueError, RuntimeError) as error:
                self.send_json(500, {"error": str(error)})
        elif path == "/api/lookups":
            try:
                self.send_json(200, self.server.playground.lookup.execute("capabilities", {}))
            except (OSError, ValueError, RuntimeError, ImportError, sqlite3.Error) as error:
                self.send_json(500, {"error": str(error)})
        elif path.startswith("/api/jobs/"):
            try:
                self.send_json(200, self.server.playground.get(path[len("/api/jobs/"):]))
            except KeyError:
                self.send_json(404, {"error": "Unknown generation"})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        origin = f"http://{self.headers.get('Host', '')}"
        if not self.valid_host() or self.headers.get("Origin") != origin:
            self.send_json(403, {"error": "Invalid host or origin"})
            return
        path = urlsplit(self.path).path
        if path == "/login" and self.server.lan:
            self.login()
            return
        if not self.authenticated():
            self.send_json(401, {"error": "Authentication required"})
            return
        if path.startswith("/api/jobs/") and path.endswith("/stop"):
            try:
                job_id = path[len("/api/jobs/"):-len("/stop")]
                self.send_json(200, {"status": self.server.playground.stop(job_id)})
            except KeyError:
                self.send_json(404, {"error": "Unknown generation"})
            return
        if path not in ("/api/jobs", "/api/lookup", "/api/reader/scope", "/api/reader/explore",
                        "/api/reader/occurrences", "/api/reader/examine"):
            self.send_json(404, {"error": "Not found"})
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Expected application/json")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("Request must be between 1 byte and 2 MB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            app = self.server.playground
            if path == "/api/jobs":
                self.send_json(202, {"id": app.start(payload)})
            elif path == "/api/reader/examine":
                self.send_json(202, {"id": app.start_examination(payload)})
            elif not isinstance(payload, dict):
                raise ValueError("Request must be a JSON object")
            elif path == "/api/lookup":
                operation = payload.get("operation")
                if not isinstance(operation, str) or operation not in ("word.analyze", "text.search", "text.passage"):
                    raise ValueError("Unknown lookup")
                self.send_json(200, app.lookup.execute(operation, payload.get("payload")))
            elif path == "/api/reader/scope":
                scope = app.reader.scope(payload["corpus"], payload["edition"], payload["scope"])
                self.send_json(200, {"scope": scope, "tokens": list(tokens(scope["text"]))})
            elif path == "/api/reader/explore":
                self.send_json(200, app.reader.explore(payload))
            else:
                self.send_json(200, app.reader.occurrences(payload))
        except (ValueError, UnicodeError, KeyError) as error:
            self.send_json(400, {"error": str(error)})
        except (OSError, RuntimeError, sqlite3.Error, ImportError) as error:
            self.send_json(500, {"error": str(error)})


def serve(root, port, lan=False):
    addresses = lan_addresses() if lan else []
    if lan and not addresses:
        raise RuntimeError("No private IPv4 address detected; connect to a private network and retry.")
    server = Server(("0.0.0.0" if lan else "127.0.0.1", port), Playground(root),
                    lan=lan, addresses=addresses)
    print(f"PlatoSI playground: http://127.0.0.1:{server.server_port}/", flush=True)
    if lan:
        for address in addresses:
            print(f"LAN address: {address}  Browser URL: http://{address}:{server.server_port}/", flush=True)
        print(f"LAN access token: {server.access_token}", flush=True)
        print("HTTP is unencrypted. Use only a trusted private network; do not port-forward.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
