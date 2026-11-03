"""Download pinned Perseus XML and build the canonical reader corpus."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.canonical_build import extract_segments
from platosi.canonical_text import CanonicalCorpus, DATA, make_work


def source_hash(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def source_metadata(corpus):
    revision = corpus.inventory["source_revision"]
    for filename, expected in corpus.inventory["source_metadata"].items():
        path = corpus.root / DATA / "source" / filename
        if path.exists():
            data = path.read_bytes()
        else:
            url = f"https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/{revision}/{filename}"
            request = Request(url, headers={"User-Agent": "PlatoSI-canonical-corpus-builder"})
            with urlopen(request, timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"Downloaded source metadata does not match the inventory: {filename}")
            atomic_write(path, data)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Existing source metadata does not match the inventory: {path}")


def build_entry(corpus, entry):
    filename = f"tlg0059.{entry['tlg']}.{entry['edition']}.xml"
    source = corpus.root / DATA / "source" / entry["tlg"] / filename
    if source.exists():
        data = source.read_bytes()
    else:
        revision = corpus.inventory["source_revision"]
        url = (f"https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/{revision}"
               f"/data/tlg0059/{entry['tlg']}/{filename}")
        request = Request(url, headers={"User-Agent": "PlatoSI-canonical-corpus-builder"})
        with urlopen(request, timeout=60) as response:
            data = response.read()
        if source_hash(data) != entry["source_lf_sha256"]:
            raise ValueError(f"Downloaded source does not match the pinned inventory: {filename}")
        atomic_write(source, data)
    if source_hash(data) != entry["source_lf_sha256"]:
        raise ValueError(f"Existing source does not match the pinned inventory: {source}")
    work = make_work(corpus.inventory, entry, extract_segments(source))
    destination = corpus.root / DATA / "works" / f"{entry['dialogue']}.json"
    atomic_write(destination, (json.dumps(work, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dialogue", help="Build one dialogue instead of the full corpus")
    args = parser.parse_args()
    corpus = CanonicalCorpus(ROOT)
    entries = [corpus.entry(args.dialogue)] if args.dialogue else corpus.inventory["works"]
    source_metadata(corpus)
    for entry in entries:
        work = build_entry(corpus, entry)
        print(f"Built {work['dialogue']}: {work['text_version']}", flush=True)


if __name__ == "__main__":
    main()
