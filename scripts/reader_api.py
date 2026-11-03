"""Run the local reader API on standard input and output."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.reader_protocol import serve

if __name__ == "__main__":
    serve(ROOT, sys.stdin.buffer, sys.stdout.buffer)
