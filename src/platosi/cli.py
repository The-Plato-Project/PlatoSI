import argparse
import json
from pathlib import Path
import sys

from platosi.registry import Registry


def main():
    parser = argparse.ArgumentParser(description="Attributed, offline resource retrieval")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    for name in ("enable", "disable", "index"):
        p = commands.add_parser(name)
        p.add_argument("provider")
    for name in ("search", "lookup", "analyze"):
        p = commands.add_parser(name)
        p.add_argument("query")
        p.add_argument("--mode", choices=("exact", "accent-insensitive"), default="exact")
        p.add_argument("--limit", type=int, default=20)
    p = commands.add_parser("passage")
    p.add_argument("edition")
    p.add_argument("citation")
    args = parser.parse_args()
    registry = Registry(args.root)
    if args.command == "status":
        result = registry.statuses()
    elif args.command in ("enable", "disable"):
        registry.set_enabled(args.provider, args.command == "enable")
        result = registry.statuses()
    elif args.command == "index":
        if args.provider not in registry.providers:
            parser.error(f"Unknown provider: {args.provider}")
        registration = registry.providers[args.provider]
        if not registration.enabled:
            parser.error(f"Provider is disabled: {args.provider}")
        result = registration.load().build()
    else:
        if hasattr(args, "limit") and args.limit < 1:
            parser.error("--limit must be positive")
        if hasattr(args, "query") and not args.query.strip():
            parser.error("query must not be empty")
        method = {"search": "search", "lookup": "lookup", "analyze": "analyze", "passage": "passage"}[args.command]
        result = {"operation": method, "providers": registry.statuses(),
                  "available_providers": [], "results": []}
        if hasattr(args, "limit"):
            result["limit_per_provider"] = args.limit
            result["possibly_truncated_providers"] = []
        for registration, provider in registry.active(method):
            result["available_providers"].append(registration.manifest["id"])
            if method == "passage":
                records = provider.passage(args.edition, args.citation)
            else:
                records = getattr(provider, method)(args.query, args.mode, args.limit)
                if len(records) == args.limit:
                    result["possibly_truncated_providers"].append(registration.manifest["id"])
            result["results"].extend(records)
        if not result["available_providers"]:
            result["message"] = f"No enabled and available provider supports {method}."
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
