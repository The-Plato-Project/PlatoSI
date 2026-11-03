"""Versioned newline-delimited local-process protocol for reader lookups."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from platosi.cancellation import Cancellation, Cancelled
from platosi.reader_api import InvalidRequest, ReaderApi, VERSION


MAX_MESSAGE_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 8_000_000
MAX_PENDING = 16


def serve(root, source, destination):
    api = ReaderApi(root)
    lock = threading.Lock()
    pending = {}
    executor = ThreadPoolExecutor(max_workers=4)

    def send(message, finished_id=None):
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        if len(data) > MAX_RESPONSE_BYTES:
            message = {"version": VERSION, "id": message.get("id"), "status": "failed",
                       "error": "Response exceeds the protocol size limit"}
            data = (json.dumps(message) + "\n").encode("utf-8")
        with lock:
            destination.write(data)
            destination.flush()
            if finished_id is not None:
                pending.pop(finished_id, None)

    def run(request, cancellation):
        request_id = request["id"]
        try:
            result = api.execute(request["operation"], request["payload"], cancellation)
            response = {"version": VERSION, "id": request_id, "status": "ok", "result": result}
        except Cancelled:
            response = {"version": VERSION, "id": request_id, "status": "cancelled"}
        except InvalidRequest as error:
            response = {"version": VERSION, "id": request_id, "status": "invalid", "error": str(error)}
        except Exception as error:
            response = {"version": VERSION, "id": request_id, "status": "failed",
                        "error": f"{type(error).__name__}: {error}"}
        send(response, request_id)

    try:
        while True:
            line = source.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
                send({"version": VERSION, "id": None, "status": "invalid", "error": "Invalid message length"})
                while line and not line.endswith(b"\n"):
                    line = source.readline(MAX_MESSAGE_BYTES + 1)
                continue
            request = None
            try:
                request = json.loads(line.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("Request must be an object")
                request_id = request.get("id")
                if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                    raise ValueError("id must be a nonempty string of at most 128 characters")
                if type(request.get("version")) is not int or request["version"] != VERSION:
                    raise ValueError("Unsupported contract version")
                if not isinstance(request.get("operation"), str) or not isinstance(request.get("payload"), dict):
                    raise ValueError("operation and payload are required")
                with lock:
                    if request_id in pending:
                        raise ValueError("Request id is already active")
                if request["operation"] == "request.cancel":
                    target = request["payload"].get("id")
                    if not isinstance(target, str) or not target or target == request_id:
                        raise ValueError("Cancellation requires a different request id")
                    with lock:
                        cancellation = pending.get(target)
                        if cancellation:
                            cancellation.cancel()
                    send({"version": VERSION, "id": request_id, "status": "ok",
                          "result": {"requested": cancellation is not None}})
                else:
                    with lock:
                        if len(pending) >= MAX_PENDING:
                            raise ValueError("Too many active requests")
                        cancellation = Cancellation()
                        pending[request_id] = cancellation
                    executor.submit(run, request, cancellation)
            except (ValueError, UnicodeError) as error:
                send({"version": VERSION, "id": request.get("id") if isinstance(request, dict) else None,
                      "status": "invalid", "error": str(error)})
    finally:
        with lock:
            for cancellation in pending.values():
                cancellation.cancel()
        executor.shutdown(wait=True)
