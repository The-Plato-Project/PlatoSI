"""Shared storage identity for canonical and linguistic evidence."""

import lzma
import os
from pathlib import Path
import shutil
import tempfile


DATABASE = Path("data/plato-evidence-v1.sqlite")
ARCHIVE = Path("data/plato-evidence-v1.sqlite.xz")


def database_path(root):
    root = Path(root)
    database = root / DATABASE
    if database.is_file():
        return database
    archive = root / ARCHIVE
    if not archive.is_file():
        return database
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=database.parent,
            prefix=database.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            with lzma.open(archive, "rb") as source:
                shutil.copyfileobj(source, handle)
        if database.exists():
            temporary.unlink()
        else:
            os.replace(temporary, database)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return database


def archive_database(root):
    root = Path(root)
    database = root / DATABASE
    if not database.is_file():
        raise FileNotFoundError(f"Evidence database is missing: {database}")
    archive = root / ARCHIVE
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=archive.parent,
            prefix=archive.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            with database.open("rb") as source, lzma.open(
                handle,
                "wb",
                preset=9,
            ) as destination:
                shutil.copyfileobj(source, destination)
        os.replace(temporary, archive)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return archive
