import argparse
import json
from pathlib import Path
import sys

from platosi.profiles import Profiles, select
from platosi.registry import Registry


def main():
    parser = argparse.ArgumentParser(description="Attributed, offline resource retrieval")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    profile_command = commands.add_parser("profile")
    profile_actions = profile_command.add_subparsers(dest="profile_action", required=True)
    profile_actions.add_parser("list")
    profile_show = profile_actions.add_parser("show")
    profile_show.add_argument("name")
    profile_save = profile_actions.add_parser("save")
    profile_save.add_argument("name")
    profile_save.add_argument("--resource", action="append", default=[], metavar="ID")
    profile_save.add_argument("--text-first", action="store_true")
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
    p = commands.add_parser("retrieve")
    p.add_argument("query", help="JSON object for a scholarly resource provider")
    for name in ("search", "lookup", "analyze", "passage", "retrieve"):
        p = commands.choices[name]
        p.add_argument("--profile", help="Use a saved reader profile")
        p.add_argument("--include", action="append", default=[], metavar="ID",
                       help="Consult only these provider IDs, in the order supplied")
        p.add_argument("--exclude", action="append", default=[], metavar="ID",
                       help="Exclude a provider from this inquiry")
    args = parser.parse_args()
    if args.command == "profile":
        profiles = Profiles(args.root)
        try:
            if args.profile_action == "list":
                result = profiles.profiles
            elif args.profile_action == "show":
                result = {"name": args.name, **profiles.get(args.name)}
            else:
                profiles.save(args.name, args.resource, args.text_first)
                result = {"name": args.name, **profiles.get(args.name)}
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
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
        method = args.command
        if method == "retrieve":
            try:
                query = json.loads(args.query)
            except json.JSONDecodeError as error:
                parser.error(f"Invalid JSON query: {error}")
            if not isinstance(query, dict):
                parser.error("retrieve query must be a JSON object")
        try:
            profile = Profiles(args.root).get(args.profile) if args.profile else None
            selection, active = select(registry, method, profile, args.include, args.exclude)
        except ValueError as error:
            parser.error(str(error))
        statuses = registry.statuses(check_availability=False)
        selected_by_id = {entry["id"]: entry for entry in selection}
        for status in statuses:
            state = selected_by_id.get(status["id"])
            status["selected"] = state is not None
            if state is not None:
                status["available"] = state["available"]
                if state["reason"] == "source or current index unavailable":
                    status["unavailable_reason"] = state["reason"]
        result = {"operation": method, "profile": args.profile,
                  "inquiry_include": args.include, "inquiry_exclude": args.exclude,
                  "selected_resources": selection, "providers": statuses,
                  "available_providers": [], "results": []}
        if hasattr(args, "limit"):
            result["limit_per_provider"] = args.limit
            result["possibly_truncated_providers"] = []
        for registration, provider in active:
            result["available_providers"].append(registration.manifest["id"])
            if method == "passage":
                records = provider.passage(args.edition, args.citation)
            elif method == "retrieve":
                records = provider.retrieve(query)
            else:
                records = getattr(provider, method)(args.query, args.mode, args.limit)
                if len(records) == args.limit:
                    result["possibly_truncated_providers"].append(registration.manifest["id"])
            result["results"].extend(records)
        if not result["available_providers"]:
            result["message"] = f"No enabled and available provider supports {method} in this selection."
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
