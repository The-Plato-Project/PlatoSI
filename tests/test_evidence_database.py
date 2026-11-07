import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from platosi.evidence_database import ARCHIVE, DATABASE, database_path


class EvidenceDatabaseTests(unittest.TestCase):
    def test_materializes_verified_database_from_shipped_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / ARCHIVE
            archive.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / ARCHIVE, archive)
            database = database_path(root)
            inventory = json.loads(
                (ROOT / "docs" / "plato-evidence-v1-inventory.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(database, root / DATABASE)
            self.assertEqual(
                hashlib.sha256(database.read_bytes()).hexdigest(),
                inventory["database_sha256"],
            )
            self.assertEqual(
                database.stat().st_size,
                inventory["database_size"],
            )


if __name__ == "__main__":
    unittest.main()
