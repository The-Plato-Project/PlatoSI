import argparse
import json
from pathlib import Path
import sys

from platosi.dialogue_morphology import DialogueMorphologyIndex, MorphologyBuildError
from platosi.inquiry import inquire, model_provider
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
    morphology_index = commands.add_parser(
        "index-dialogue-morphology",
        help="Build PlatoSI's permanent morphology index from a local analyzer",
    )
    morphology_index.add_argument("dialogue")
    morphology_index.add_argument("--text-version")
    morphology_index.add_argument("--provider", default="morpheus")
    morphology_index.add_argument("--rebuild", action="store_true")
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
    p = commands.add_parser("models", help="Discover models from an installed model provider")
    p.add_argument("--provider", help="Language-model provider ID")
    p = commands.add_parser("inquire", help="Ask a model about reader-selected evidence")
    p.add_argument("question")
    p.add_argument("--provider", help="Language-model provider ID")
    p.add_argument("--model", help="Model name from the selected provider")
    p.add_argument("--generation", default="{}", help="JSON object of generation settings")
    p.add_argument("--text", help="Exact Greek word or phrase to search")
    p.add_argument("--edition", help="Edition identifier for a passage")
    p.add_argument("--citation", help="Citation within the edition")
    p.add_argument("--headword", action="append", help="Dictionary lookup term (repeatable)")
    p.add_argument("--form", action="append", help="Morphology lookup form (repeatable)")
    p.add_argument("--scholarly-query", help="JSON object for selected scholarly providers")
    p.add_argument("--mode", choices=("exact", "accent-insensitive"), default="exact")
    p.add_argument("--limit", type=int, default=3, help="Maximum evidence records per provider and operation")
    p.add_argument("--json", action="store_true", help="Return the complete evidence records as JSON")
    for name in ("search", "lookup", "analyze", "passage", "retrieve", "inquire"):
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
    elif args.command == "models":
        try:
            registration, provider = model_provider(registry, args.provider, "models")
            result = {"provider": registration.manifest["id"], "models": provider.list_models()}
        except (ValueError, RuntimeError, OSError) as error:
            parser.error(str(error))
    elif args.command == "inquire":
        try:
            generation = json.loads(args.generation)
            if not isinstance(generation, dict):
                raise ValueError("--generation must be a JSON object")
            scholarly_query = json.loads(args.scholarly_query) if args.scholarly_query is not None else None
            if scholarly_query is not None and not isinstance(scholarly_query, dict):
                raise ValueError("--scholarly-query must be a JSON object")
            profile = Profiles(args.root).get(args.profile) if args.profile else None
            result = inquire(registry, args.question, profile=profile, include=args.include,
                             exclude=args.exclude, text=args.text, edition=args.edition,
                             citation=args.citation, headwords=args.headword, forms=args.form,
                             scholarly_query=scholarly_query, mode=args.mode, limit=args.limit,
                             model_id=args.provider, model=args.model, generation=generation)
        except (ValueError, RuntimeError, OSError) as error:
            parser.error(str(error))
        if not args.json:
            print_inquiry(result)
            return
    elif args.command in ("enable", "disable"):
        registry.set_enabled(args.provider, args.command == "enable")
        result = registry.statuses()
    elif args.command == "index":
        if args.provider not in registry.providers:
            parser.error(f"Unknown provider: {args.provider}")
        registration = registry.providers[args.provider]
        if not registration.enabled:
            parser.error(f"Provider is disabled: {args.provider}")
        provider = registration.load()
        if not hasattr(provider, "build"):
            parser.error(f"Provider does not support indexing: {args.provider}")
        result = provider.build()
    elif args.command == "index-dialogue-morphology":
        def progress(position, total, form, analyzed):
            if position == 1 or position % 100 == 0 or position == total:
                status = "analyzed" if analyzed else "unresolved"
                print(
                    f"{position}/{total}: {form} ({status})",
                    file=sys.stderr,
                    flush=True,
                )

        try:
            result = DialogueMorphologyIndex(args.root).build(
                registry,
                args.dialogue,
                text_version=args.text_version,
                provider_id=args.provider,
                rebuild=args.rebuild,
                progress=progress,
            )
        except (ValueError, MorphologyBuildError) as error:
            parser.error(str(error))
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


def print_inquiry(result):
    if result["answer"]:
        print(result["answer"])
        print("\nModel:", result["model"]["provider"], result["model"].get("model", ""))
    else:
        print("No model response was generated.")
    if result["evidence"]:
        print("\nEvidence (use --json for complete records):")
        for item in result["evidence"]:
            record = item["record"]
            source = record.get("source", {})
            print(f"[{item['id']}] {record.get('evidence_type', 'source evidence')} | "
                  f"{record.get('provider', 'unknown provider')} | "
                  f"version {record.get('provider_version', 'unknown')} | "
                  f"revision {source.get('revision', 'unknown')}")
            if record.get("edition"):
                print("  Edition:", record["edition"])
            if record.get("stephanus_at_match"):
                print("  Stephanus:", json.dumps(record["stephanus_at_match"], ensure_ascii=False))
            if record.get("citations"):
                print("  Citations:", ", ".join(str(c["citation"]) for c in record["citations"]))
            if record.get("headword"):
                print("  Headword:", record["headword"])
            if record.get("source_line"):
                print("  Source line:", record["source_line"])
            if source.get("repository"):
                print("  Source:", source["repository"])
            if record.get("source_path"):
                print("  Source file:", record["source_path"])
            if record.get("text"):
                print("  Greek/source text:", record["text"].strip())
            if record.get("source_markup"):
                print("  Editorial markup is present; inspect the complete record and original XML.")
    for warning in result["warnings"]:
        print("Warning:", warning)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
