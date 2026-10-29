"""Provider-local SQLite helpers."""

from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import os
import sqlite3
import tempfile


@contextmanager
def new_index(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    try:
        with closing(sqlite3.connect(temp)) as db:
            with db:
                yield db
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def read_index(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Provider index not found: {path}; build this provider first.")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        yield db


def signature(manifest):
    return json.dumps({name: manifest.get(name) for name in ("id", "version", "source", "config")},
                      sort_keys=True, ensure_ascii=False)


def stamp(db, manifest):
    db.execute("CREATE TABLE index_metadata (signature TEXT NOT NULL)")
    db.execute("INSERT INTO index_metadata VALUES (?)", (signature(manifest),))


def current(path, manifest):
    if not path.is_file():
        return False
    with read_index(path) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_metadata'").fetchone() is None:
            return False
        row = db.execute("SELECT signature FROM index_metadata").fetchone()
        return row is not None and row["signature"] == signature(manifest)


def verify_blob(path, expected_size, expected_hash):
    size = path.stat().st_size
    if size != expected_size:
        raise ValueError(f"Source size mismatch: {path}")
    digest = hashlib.sha1(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_hash:
        raise ValueError(f"Source Git blob hash mismatch: {path}")
