"""Build a portable local-process distribution without local data or models."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi import __version__
from platosi.canonical_text import CONTRACT
from platosi.reader_api import VERSION


SCRIPTS = (
    "build-canonical-corpus.py", "reader_api.py", "check-local-dependency.py", "platosi.py", "playground.py",
    "plato-common.ps1", "download-plato.ps1", "download-lsj.ps1", "download-morphology.ps1",
    "validate-plato.ps1", "validate-lsj.ps1", "validate-morphology.ps1",
)
DOCS = (
    "local-dependency.md", "text-location-contract.md", "retrieval.md",
    "glem-licensing-review.md", "morphology-research.md", "dilemma-phase1-evaluation.md",
    "canonical-corpus-v1-inventory.json", "corpus-inventory.json", "lsj-inventory.json",
    "morphology-inventory.json",
)


def release_files(root):
    root = Path(root)
    paths = [root / "scripts" / name for name in SCRIPTS]
    paths += [root / "docs" / name for name in DOCS]
    paths += sorted((root / "src" / "platosi").glob("*.py"))
    paths += sorted((root / "plugins").glob("*/plugin.json"))
    paths += sorted((root / "plugins").glob("*/provider.py"))
    paths += sorted(path for path in (root / "playground").iterdir()
                    if path.is_file() and path.suffix in (".html", ".js", ".css"))
    if not (root / "src" / "platosi" / "__init__.py").is_file():
        raise FileNotFoundError("PlatoSI source package is missing")
    if not (root / "plugins" / "perseus-plato" / "plugin.json").is_file():
        raise FileNotFoundError("Perseus provider is missing")
    if not (root / "playground" / "index.html").is_file():
        raise FileNotFoundError("Playground assets are missing")
    files = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Distribution file is missing or is a symlink: {path}")
        name = path.relative_to(root).as_posix()
        if name.casefold() in {key.casefold() for key in files}:
            raise ValueError(f"Duplicate distribution path: {name}")
        files[name] = path.read_bytes()
    files["README.md"] = (root / "docs" / "local-dependency.md").read_bytes()
    return files


def build_release(root, destination):
    destination = Path(destination)
    checksum_path = destination.with_name(destination.name + ".sha256")
    if destination.exists() or checksum_path.exists():
        raise FileExistsError(f"Release or checksum already exists: {destination}")
    files = release_files(root)
    manifest = {
        "service": "PlatoSI", "version": __version__, "protocol_version": VERSION,
        "location_contract": CONTRACT,
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                  for name, data in sorted(files.items())},
    }
    files["release-manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    with checksum_path.open("x", encoding="ascii", newline="\n") as checksum:
        checksum.write(f"{digest}  {destination.name}\n")
    return destination, checksum_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"platosi-local-{__version__}.zip")
    args = parser.parse_args()
    archive, checksum = build_release(ROOT, args.output)
    print(f"Built {archive}\nSHA-256: {checksum}")


if __name__ == "__main__":
    main()
