"""Check a bounded set of canonical forms with one explicitly selected provider."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platosi.canonical_text import CanonicalCorpus
from platosi.dialogue_lexicon import tokens, utf16_offset
from platosi.reader_api import ReaderApi
from platosi.unicode_search import key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dialogue", required=True)
    parser.add_argument("--section", required=True, help="Exact Stephanus section, e.g. 327b")
    parser.add_argument("--word", required=True, help="Selected canonical Greek form")
    parser.add_argument("--offset", type=int, help="UTF-16 offset when the form occurs more than once in the section")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--form", action="append", default=[], help="Another exact canonical form to check (repeatable)")
    parser.add_argument("--max-new-forms", type=int, default=0, help="0 uses cached evidence only; maximum 20")
    parser.add_argument("--summary", action="store_true", help="Omit raw analyses and passage locations from output")
    args = parser.parse_args()
    api = ReaderApi(args.root)
    try:
        work = CanonicalCorpus(args.root).work(args.dialogue)
        sections = [section for section in work["sections"] if section["stephanus"] == args.section]
        if len(sections) != 1:
            parser.error("Select an existing Stephanus section")
        passage = "\n".join(segment["text"] for segment in sections[0]["segments"])
        candidates = [(start, end) for start, end, form in tokens(passage) if key(form) == key(args.word)
                      and (args.offset is None or utf16_offset(passage, start) == args.offset)]
        if len(candidates) != 1:
            parser.error("Select exactly one occurrence; use --offset with its UTF-16 start offset if necessary")
        start, end = candidates[0]
        location = {"dialogue": args.dialogue, "text_version": work["text_version"],
                    "start": {"stephanus": args.section, "offset": utf16_offset(passage, start)},
                    "end": {"stephanus": args.section, "offset": utf16_offset(passage, end)}}
        result = api.execute("linguistics.verify-occurrences", {
            "location": location, "provider": args.provider, "forms": args.form,
            "max_new_forms": args.max_new_forms,
        })
        if args.summary:
            result = {"contract": result["contract"], "status": result["status"], "coverage": result["coverage"],
                      "readings": [{k: v for k, v in reading.items() if k != "forms"} for reading in result["readings"]],
                      "form_checks": [{k: v for k, v in check.items() if k != "analyses"} for check in result["form_checks"]],
                      "warnings": result["warnings"], "limitations": result["limitations"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeError) as error:
        parser.error(str(error))
    finally:
        api.close()


if __name__ == "__main__":
    main()
