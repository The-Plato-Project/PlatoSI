"""Verify an installed PlatoSI dependency using its local-process API."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    process = subprocess.Popen([sys.executable, "-I", "-u", str(ROOT / "scripts" / "reader_api.py")],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def request(operation, payload):
        message = {"version": 1, "id": operation, "operation": operation, "payload": payload}
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"PlatoSI exited before answering {operation}")
        response = json.loads(line.decode("utf-8"))
        if response.get("id") != operation or response.get("status") != "ok":
            raise RuntimeError(f"{operation} failed: {response}")
        return response["result"]

    try:
        info = request("system.info", {})
        if info["service"] != "PlatoSI" or info["protocol_version"] != 1:
            raise RuntimeError("The installed service has an incompatible protocol")
        catalogue = request("canonical.catalog", {})
        republic = next((work for work in catalogue["works"] if work["dialogue"] == "republic"), None)
        if republic is None:
            raise RuntimeError("Republic is missing from the canonical catalogue")
        location = {"dialogue": "republic", "text_version": republic["text_version"],
                    "start": {"stephanus": "327a", "offset": 0},
                    "end": {"stephanus": "327a", "offset": 7}}
        resolved = request("canonical.resolve", {"location": location})
        if resolved["text"] != "κατέβην":
            raise RuntimeError("The opening word did not resolve as expected")
        print(f"PlatoSI {info['version']}; protocol {info['protocol_version']}; "
              f"{len(catalogue['works'])} dialogues; Republic 327a location verified.")
    finally:
        process.stdin.close()
        process.wait(timeout=30)
        errors = process.stderr.read().decode("utf-8", errors="replace")
        process.stdout.close()
        process.stderr.close()
        if process.returncode:
            raise RuntimeError(f"PlatoSI exited with code {process.returncode}: {errors}")


if __name__ == "__main__":
    main()
