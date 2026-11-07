import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi import __version__
from platosi.canonical_build import extract_segments
from platosi.canonical_text import sections_from_segments, segment_digest, text_version


spec = importlib.util.spec_from_file_location("package_platosi", ROOT / "scripts" / "package-platosi.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class LocalDistributionTests(unittest.TestCase):
    def test_archive_integrity_reproducibility_and_clean_install(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            archive, checksum = packager.build_release(ROOT, temp / "release.zip")
            second, _ = packager.build_release(ROOT, temp / "second.zip")
            self.assertEqual(archive.read_bytes(), second.read_bytes())
            self.assertEqual(checksum.read_text(encoding="ascii").split()[0],
                             hashlib.sha256(archive.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                packager.build_release(ROOT, archive)
            installed = temp / "installed"
            with zipfile.ZipFile(archive) as package:
                names = package.namelist()
                self.assertFalse(any(name.startswith(("models/", "tests/")) for name in names))
                self.assertEqual(
                    [name for name in names if name.startswith("data/")],
                    ["data/plato-evidence-v1.sqlite.xz"],
                )
                self.assertFalse(any("__pycache__" in name for name in names))
                self.assertIn("config/name-research-sources.json", names)
                self.assertIn("src/platosi/research_sources.py", names)
                self.assertIn("plugins/morpheus/provider.py", names)
                self.assertIn("scripts/verify-occurrences.py", names)
                self.assertIn("src/platosi/occurrence_check.py", names)
                self.assertIn("src/platosi/dialogue_morphology.py", names)
                self.assertIn("docs/morpheus.md", names)
                self.assertIn("docs/plato-evidence-v1-inventory.json", names)
                self.assertFalse(json.loads(package.read("plugins/morpheus/plugin.json"))["enabled_by_default"])
                manifest = json.loads(package.read("release-manifest.json"))
                self.assertEqual(manifest["version"], __version__)
                self.assertEqual(manifest["protocol_version"], 1)
                self.assertEqual(manifest["location_contract"], "platosi.location.v1")
                self.assertEqual(set(names), set(manifest["files"]) | {"release-manifest.json"})
                for name, metadata in manifest["files"].items():
                    data = package.read(name)
                    self.assertEqual(metadata["sha256"], hashlib.sha256(data).hexdigest(), name)
                    self.assertEqual(metadata["size"], len(data), name)
                package.extractall(installed)

            info = self.request(installed, "system.info", {})
            self.assertEqual(info["version"], __version__)
            self.assertEqual(info["protocol_version"], 1)
            self.assertEqual(info["location_contract"], "platosi.location.v1")

            source = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
                      '<div subtype="book" n="1"><p>'
                      '<milestone unit="section" resp="Stephanus" n="327a"/>κατέβην'
                      '</p></div></body></text></TEI>').encode("utf-8")
            data_root = installed / "data" / "canonical-text-v1" / "source"
            xml_path = data_root / "tlg030" / "tlg0059.tlg030.perseus-grc2.xml"
            xml_path.parent.mkdir(parents=True)
            xml_path.write_bytes(source)
            segments = extract_segments(xml_path)
            entry = {"dialogue": "republic", "tlg": "tlg030", "edition": "perseus-grc2",
                     "title": "Republic", "title_greek": None,
                     "source_lf_sha256": hashlib.sha256(source).hexdigest(),
                     "segments_sha256": segment_digest(segments),
                     "text_version": text_version("republic", sections_from_segments(segments))}
            metadata = b"fixture"
            (data_root / "README.md").write_bytes(metadata)
            inventory = {"contract": "platosi.location.v1", "source_repository": "fixture",
                         "source_revision": "fixture", "source_metadata": {
                             "README.md": hashlib.sha256(metadata).hexdigest()}, "works": [entry]}
            (installed / "docs" / "canonical-corpus-v1-inventory.json").write_text(
                json.dumps(inventory), encoding="utf-8")
            build = subprocess.run([sys.executable, "-I", str(installed / "scripts" / "build-canonical-corpus.py")],
                                   cwd=temp, capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([sys.executable, "-I", str(installed / "scripts" / "check-local-dependency.py")],
                                    cwd=temp, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1 dialogues; Republic 327a location verified", result.stdout)

    def request(self, installed, operation, payload):
        process = subprocess.Popen([sys.executable, "-I", "-u", str(installed / "scripts" / "reader_api.py")],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            request = {"version": 1, "id": "test", "operation": operation, "payload": payload}
            process.stdin.write((json.dumps(request) + "\n").encode())
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertEqual(response["status"], "ok", response)
            return response["result"]
        finally:
            process.stdin.close()
            process.wait(timeout=30)
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
