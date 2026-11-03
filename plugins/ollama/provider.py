"""Local-only Ollama adapter; no other provider depends on Ollama."""

import http.client
import io
import json
import select
import socket
import time
from urllib.parse import urlsplit

class OllamaProvider:
    def __init__(self, manifest, root):
        self.manifest = manifest
        self.config = manifest["config"]
        endpoint = urlsplit(self.config["endpoint"])
        if (endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "localhost", "::1")
                or endpoint.username or endpoint.password or endpoint.path not in ("", "/")
                or endpoint.query or endpoint.fragment):
            raise ValueError("Ollama endpoint must be a local HTTP loopback origin")
        self.host = endpoint.hostname
        self.port = endpoint.port or 11434
        self.timeout = self.config.get("timeout_seconds", 300)
        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("Ollama timeout_seconds must be positive")

    def request(self, method, path, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        timeout = min(self.timeout, 5) if method == "GET" else self.timeout
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read()
            if response.status != 200:
                raise RuntimeError(f"Ollama {path} returned HTTP {response.status}: {raw.decode('utf-8', 'replace')}")
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"Ollama {path} returned a non-object response")
            return data
        finally:
            connection.close()

    def available(self):
        try:
            self.list_models()
            return True
        except OSError:
            return False

    def list_models(self):
        data = self.request("GET", "/api/tags")
        models = data.get("models")
        if not isinstance(models, list):
            raise ValueError("Ollama returned an invalid models list")
        result = []
        for item in models:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError("Ollama returned an invalid model record")
            if item.get("remote_host") or item.get("remote_model") or item["name"].endswith(":cloud"):
                continue
            result.append({"name": item["name"], "details": item.get("details", {}),
                           "digest": item.get("digest")})
        return result

    def generate(self, prompt, options):
        model = options.get("model") or self.config.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Select a model via --model or the Ollama provider configuration")
        models = self.list_models()
        names = [entry["name"] for entry in models]
        if model not in names:
            raise ValueError(f"Local model {model!r} is not available; discovered: {', '.join(names) or '(none)'}")
        generation = options.get("generation", {})
        if not isinstance(generation, dict):
            raise ValueError("Generation options must be a JSON object")
        payload = {"model": model, "prompt": prompt, "stream": False,
                   "think": self.config.get("think", False),
                   "options": {**self.config.get("generation", {}), **generation}}
        data = self.request("POST", "/api/generate", payload)
        if not isinstance(data.get("response"), str) or not data["response"].strip():
            raise ValueError("Ollama returned an empty or invalid response")
        return {"text": data["response"], "model": data.get("model", model),
                "done_reason": data.get("done_reason")}

    def chat(self, messages, options, cancellation):
        cancellation.check()
        model = options.get("model") or self.config.get("model")
        names = [entry["name"] for entry in self.list_models()]
        cancellation.check()
        if not isinstance(model, str) or model not in names:
            raise ValueError(f"Local model {model!r} is not available; discovered: {', '.join(names) or '(none)'}")
        generation = options.get("generation", {})
        if not isinstance(generation, dict):
            raise ValueError("Generation options must be a JSON object")
        generation = {**self.config.get("generation", {}), **generation}
        if "max_tokens" in options:
            generation["num_predict"] = options["max_tokens"]
        payload = {"model": model, "messages": messages, "stream": True,
                   "think": self.config.get("think", False),
                   "options": generation}
        response_format = options.get("response_format")
        if response_format is not None:
            if response_format != "json":
                raise ValueError("Unsupported response format")
            schema = options.get("response_schema")
            if schema is not None and not isinstance(schema, dict):
                raise ValueError("Response schema must be an object")
            payload["format"] = schema if schema is not None else "json"
        connection = socket.create_connection((self.host, self.port), timeout=min(self.timeout, 5))
        connection.setblocking(False)
        buffer = bytearray()
        deadline = time.monotonic() + self.timeout

        def wait(reading):
            nonlocal deadline
            while True:
                cancellation.check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Ollama chat connection timed out")
                readable, writable, _ = select.select([connection] if reading else [],
                                                       [] if reading else [connection], [], min(0.2, remaining))
                if readable or writable:
                    return

        def receive():
            nonlocal deadline
            wait(True)
            data = connection.recv(65536)
            deadline = time.monotonic() + self.timeout
            return data

        def read_line():
            while b"\n" not in buffer:
                data = receive()
                if not data:
                    raise ValueError("Ollama closed an incomplete response")
                buffer.extend(data)
                if len(buffer) > 4_000_000:
                    raise ValueError("Ollama response line is too large")
            end = buffer.index(b"\n") + 1
            line = bytes(buffer[:end])
            del buffer[:end]
            return line

        def read_exact(count):
            while len(buffer) < count:
                data = receive()
                if not data:
                    raise ValueError("Ollama closed an incomplete response")
                buffer.extend(data)
            result = bytes(buffer[:count])
            del buffer[:count]
            return result

        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            host = f"[{self.host}]" if ":" in self.host else self.host
            request = (f"POST /api/chat HTTP/1.1\r\nHost: {host}:{self.port}\r\n"
                       f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                       "Accept-Encoding: identity\r\nConnection: close\r\n\r\n").encode("ascii") + body
            sent = 0
            while sent < len(request):
                wait(False)
                sent += connection.send(request[sent:sent + 65536])
                deadline = time.monotonic() + self.timeout
            status = read_line().decode("iso-8859-1").split()
            if len(status) < 2 or not status[1].isdigit():
                raise ValueError("Ollama returned an invalid HTTP status")
            header_lines = bytearray()
            while True:
                line = read_line()
                if line in (b"\r\n", b"\n"):
                    break
                header_lines.extend(line)
                if len(header_lines) > 65536:
                    raise ValueError("Ollama returned oversized HTTP headers")
            headers = http.client.parse_headers(io.BytesIO(bytes(header_lines) + b"\r\n"))
            if int(status[1]) != 200:
                raise RuntimeError(f"Ollama /api/chat returned HTTP {status[1]}")
            parts = []
            final = None
            pending = bytearray()

            def consume(chunk):
                nonlocal final
                pending.extend(chunk)
                while b"\n" in pending:
                    end = pending.index(b"\n") + 1
                    line = bytes(pending[:end])
                    del pending[:end]
                    if not line.strip():
                        continue
                    data = json.loads(line.decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("Ollama returned an invalid chat record")
                    if data.get("error"):
                        raise RuntimeError(f"Ollama chat error: {data['error']}")
                    message = data.get("message", {})
                    if not isinstance(message, dict) or not isinstance(message.get("content", ""), str):
                        raise ValueError("Ollama returned an invalid chat message")
                    parts.append(message.get("content", ""))
                    if data.get("done"):
                        final = data
                        return
                if len(pending) > 4_000_000:
                    raise ValueError("Ollama chat record is too large")

            if "chunked" in headers.get("Transfer-Encoding", "").lower():
                while final is None:
                    line = read_line().strip().split(b";", 1)[0]
                    size = int(line, 16)
                    if size == 0:
                        break
                    if size > 16_000_000:
                        raise ValueError("Ollama response chunk is too large")
                    consume(read_exact(size))
                    if read_exact(2) != b"\r\n":
                        raise ValueError("Ollama returned invalid chunk framing")
            else:
                content_length = headers.get("Content-Length")
                remaining = int(content_length) if content_length is not None else None
                while final is None and (remaining is None or remaining > 0):
                    if not buffer:
                        data = receive()
                        if not data:
                            break
                        buffer.extend(data)
                    count = len(buffer) if remaining is None else min(len(buffer), remaining)
                    consume(bytes(buffer[:count]))
                    del buffer[:count]
                    if remaining is not None:
                        remaining -= count
            if pending.strip() and final is None:
                consume(b"\n")
            cancellation.check()
            if final is None or not "".join(parts).strip():
                raise ValueError("Ollama returned an incomplete or empty chat response")
            return {"text": "".join(parts), "model": final.get("model", model),
                    "done_reason": final.get("done_reason")}
        finally:
            connection.close()


def create_provider(manifest, root):
    return OllamaProvider(manifest, root)
