"""Build and inventory PlatoSI's shippable Platonic morphology database."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platosi.dialogue_morphology import (
    DATABASE,
    POLICY_VERSION,
    SCHEMA_VERSION,
    DialogueMorphologyIndex,
)
from platosi.dialogue_lexicon import SCHEMA_VERSION as LEXICON_SCHEMA_VERSION
from platosi.greek_language_repository import archive_database
from platosi.registry import Registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--dialogue",
        action="append",
        dest="dialogues",
        metavar="ID",
        help="Canonical dialogue to build; repeat for more than one",
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="Build every work in the canonical corpus inventory",
    )
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=ROOT / "docs" / "plato-greek-language-repository-v1-inventory.json",
    )
    args = parser.parse_args()

    canonical = json.loads(
        (ROOT / "docs" / "canonical-corpus-v1-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    works = {work["dialogue"]: work for work in canonical["works"]}
    dialogues = list(works) if args.all else args.dialogues
    unknown = [dialogue for dialogue in dialogues if dialogue not in works]
    if unknown:
        parser.error("Unknown canonical dialogue: " + ", ".join(unknown))

    registry = Registry(ROOT)
    index = DialogueMorphologyIndex(ROOT)
    artifact = ROOT / DATABASE
    before = (
        (artifact.stat().st_mtime_ns, artifact.stat().st_size)
        if artifact.exists()
        else None
    )
    builds = []
    try:
        for dialogue in dialogues:
            print(f"Building {dialogue}...", file=sys.stderr, flush=True)

            def progress(position, total, form, analyzed):
                if position == 1 or position % 500 == 0 or position == total:
                    state = "analyzed" if analyzed else "unresolved"
                    print(
                        f"  {position}/{total}: {form} ({state})",
                        file=sys.stderr,
                        flush=True,
                    )

            builds.append(index.build(
                registry,
                dialogue,
                text_version=works[dialogue]["text_version"],
                provider_id="morpheus",
                rebuild=args.rebuild,
                progress=progress,
            ))
    finally:
        registry.close()

    after = (artifact.stat().st_mtime_ns, artifact.stat().st_size)
    if after != before:
        index.compact()
    data = artifact.read_bytes()
    archive = archive_database(ROOT)
    archive_data = archive.read_bytes()
    with sqlite3.connect(artifact) as db:
        records = {
            "dialogue_builds": db.execute(
                "SELECT COUNT(*) FROM index_builds WHERE state = 'ready'"
            ).fetchone()[0],
            "canonical_sections": db.execute(
                "SELECT COUNT(*) FROM canonical_sections"
            ).fetchone()[0],
            "canonical_forms": db.execute(
                "SELECT COUNT(*) FROM canonical_forms"
            ).fetchone()[0],
            "token_occurrences": db.execute(
                "SELECT COUNT(*) FROM tokens"
            ).fetchone()[0],
            "morphology_builds": db.execute(
                "SELECT COUNT(*) FROM morphology_builds WHERE state = 'ready'"
            ).fetchone()[0],
            "morphology_forms": db.execute(
                "SELECT COUNT(*) FROM morphology_forms"
            ).fetchone()[0],
            "morphology_memberships": db.execute(
                "SELECT COUNT(*) FROM morphology_build_forms"
            ).fetchone()[0],
            "morphology_analyses": db.execute(
                "SELECT COUNT(*) FROM morphology_analyses"
            ).fetchone()[0],
        }
    inventory = {
        "artifact": archive.relative_to(ROOT).as_posix(),
        "artifact_sha256": hashlib.sha256(archive_data).hexdigest(),
        "artifact_size": len(archive_data),
        "database": artifact.relative_to(ROOT).as_posix(),
        "database_sha256": hashlib.sha256(data).hexdigest(),
        "database_size": len(data),
        "schema_versions": {
            "canonical_index": LEXICON_SCHEMA_VERSION,
            "morphology": SCHEMA_VERSION,
        },
        "policy_version": POLICY_VERSION,
        "records": records,
        "builds": [
            {
                "dialogue": dialogue,
                "text_version": works[dialogue]["text_version"],
                **snapshot,
            }
            for dialogue, snapshot in zip(dialogues, builds)
        ],
    }
    args.inventory.parent.mkdir(parents=True, exist_ok=True)
    args.inventory.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(inventory, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
