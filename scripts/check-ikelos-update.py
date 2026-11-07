"""Report whether PyPI has a newer ikelos build than PlatoSI's pinned version."""

import json
from pathlib import Path
import re
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "requirements-morphology-build.txt"
PYPI = "https://pypi.org/pypi/ikelos/json"


def main():
    match = re.search(
        r"^ikelos==([^\s\\]+)",
        PIN.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise RuntimeError("The ikelos build dependency is not pinned")
    request = urllib.request.Request(
        PYPI,
        headers={"Accept": "application/json", "User-Agent": "PlatoSI-maintainer"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    latest = payload["info"]["version"]
    pinned = match.group(1)
    print(json.dumps({
        "package": "ikelos",
        "pinned": pinned,
        "latest": latest,
        "update_available": latest != pinned,
        "policy": "Review upstream changes and morphology diffs before changing the pin.",
    }, indent=2))


if __name__ == "__main__":
    main()
