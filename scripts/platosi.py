"""Command-line entry point; no external Python packages are needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from platosi.cli import main

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
