"""Run the experimental local browser playground."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.playground import serve

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local PlatoSI model playground")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lan", action="store_true", help="Allow token-protected access on private IPv4 networks")
    args = parser.parse_args()
    serve(ROOT, args.port, lan=args.lan)
