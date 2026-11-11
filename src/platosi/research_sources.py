"""Validated adapters for scholarly name-research sources."""

import html
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlencode, urlsplit


class ResearchSources:
    """Own the source manifest and extraction of bounded reference records."""

    ADAPTERS = {
        "humanistica-plato",
        "athenian-onomasticon",
    }

    def __init__(self, path: Path):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != 2:
            raise ValueError("Name-research source configuration must have version 2")
        sources = value.get("sources")
        synthesis = value.get("synthesis")
        if not isinstance(sources, list) or not isinstance(synthesis, dict):
            raise ValueError("Name-research configuration requires sources and synthesis")
        tokens = synthesis.get("max_tokens")
        if type(tokens) is not int or not 256 <= tokens <= 8192:
            raise ValueError("Name-research max_tokens must be between 256 and 8192")
        seen = set()
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Each research source must be an object")
            for key in ("id", "name", "endpoint", "language"):
                if not isinstance(source.get(key), str) or not source[key].strip():
                    raise ValueError(f"Research source requires a nonempty {key}")
            if source["id"] in seen:
                raise ValueError(f"Duplicate research source ID: {source['id']}")
            seen.add(source["id"])
            endpoint = urlsplit(source["endpoint"])
            if (endpoint.scheme != "https" or not endpoint.hostname
                    or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
                raise ValueError("Research source endpoints must be HTTPS URLs without credentials or queries")
            if not isinstance(source.get("adapter"), str) or source["adapter"] not in self.ADAPTERS:
                raise ValueError(f"Unsupported research source adapter: {source.get('adapter')}")
            if type(source.get("enabled")) is not bool:
                raise ValueError("Research source enabled must be true or false")
            if type(source.get("priority")) is not int:
                raise ValueError("Research source priority must be an integer")
            if type(source.get("limit")) is not int or not 1 <= source["limit"] <= 50:
                raise ValueError("Research source limit must be between 1 and 50")
            minimum = source.get("minimum_statements", 0)
            if type(minimum) is not int or not 0 <= minimum <= 6:
                raise ValueError("Research source minimum_statements must be between 0 and 6")
        self.sources = sorted(sources, key=lambda item: item["priority"])
        self.max_tokens = tokens

    @classmethod
    def request_url(cls, source, lemma):
        """Build a bounded request for one supported scholarly source."""
        adapter = source["adapter"]
        if adapter == "humanistica-plato":
            fragment = urlencode({"adapter": adapter, "lemma": lemma})
            return source["endpoint"] + "#" + fragment
        search_name = cls._name_key(lemma, preserve_case=True).replace("ς", "σ") + "^"
        query = urlencode({"name": search_name, "date1": -1000, "date2": 1000})
        return source["endpoint"] + "?" + query + "#" + urlencode({"adapter": adapter})

    @staticmethod
    def _plain_text(value):
        value = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", value,
                       flags=re.IGNORECASE | re.DOTALL)
        value = re.sub(r"<[^>]+>", " ", value)
        return " ".join(html.unescape(value).split())

    @staticmethod
    def _name_key(value, preserve_case=False):
        normalized = "".join(
            character for character in unicodedata.normalize("NFD", value)
            if not unicodedata.category(character).startswith("M")
        )
        normalized = unicodedata.normalize("NFC", normalized)
        return normalized if preserve_case else normalized.casefold()

    @classmethod
    def parse_humanistica(cls, document, base_url):
        """Extract the compact person dictionary from the site's large edition page."""
        people = []
        pattern = re.compile(
            r'<section\s+class="page"\s+id="(p-[^"]+)">(.*?)</section>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(document):
            section_id, body = match.groups()
            heading = re.search(r"<h2\b[^>]*>(.*?)</h2>", body, re.IGNORECASE | re.DOTALL)
            if heading is None:
                continue
            greek = re.search(
                r'<span\b[^>]*class="greek"[^>]*>(.*?)</span>',
                heading.group(1),
                re.IGNORECASE | re.DOTALL,
            )
            greek_name = cls._plain_text(greek.group(1)) if greek else ""
            title = cls._plain_text(
                re.sub(r"<span\b.*?</span>", "", heading.group(1),
                       flags=re.IGNORECASE | re.DOTALL)
            )
            excerpt = cls._plain_text(body)
            if title and excerpt:
                citations = []
                source_block = re.search(
                    r"<h3\b[^>]*>\s*Sources\s*</h3>\s*<p\b[^>]*>(.*?)</p>",
                    body,
                    re.IGNORECASE | re.DOTALL,
                )
                if source_block is not None:
                    source_html = source_block.group(1)
                    links = list(re.finditer(
                        r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                        source_html,
                        re.IGNORECASE | re.DOTALL,
                    ))
                    for index, link in enumerate(links):
                        url = html.unescape(link.group(1)).strip()
                        parsed = urlsplit(url)
                        if parsed.scheme != "https" or not parsed.hostname:
                            continue
                        end = links[index + 1].start() if index + 1 < len(links) else len(source_html)
                        tail = source_html[link.end():end].split(";", 1)[0]
                        label = " ".join(filter(None, [
                            cls._plain_text(link.group(2)),
                            cls._plain_text(tail),
                        ]))
                        citations.append({"title": label, "url": url})
                people.append({
                    "slug": section_id,
                    "title": title,
                    "greek": greek_name,
                    "url": base_url.rstrip("/") + "/#" + section_id,
                    "excerpt": excerpt,
                    "citations": citations,
                })
        if not people:
            raise ValueError("Humanistica response contained no person records")
        return {"people": people}

    @classmethod
    def filter_humanistica(cls, response, lemma):
        query = cls._name_key(lemma)
        people = response.get("people", []) if isinstance(response, dict) else []
        matches = [
            person for person in people
            if isinstance(person, dict) and query in {
                cls._name_key(person.get("title", "")),
                cls._name_key(person.get("greek", "")),
            }
        ]
        return {"people": matches}

    @classmethod
    def parse_athenian_onomasticon(cls, document):
        """Extract stable person records from the public Onomasticon result page."""
        entries = []
        pattern = re.compile(
            r'<code\s+id="cu-([0-9]+)">([^<]+)</code>.*?</button>\s*</div>'
            r'(.*?)</p>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(document):
            identity, url, body = match.groups()
            excerpt = re.sub(r"^[0-9]+\.\s*", "", cls._plain_text(body))
            if excerpt:
                name = excerpt.split(" of ", 1)[0].strip()
                entries.append({
                    "id": identity,
                    "title": f"{name} — Onomasticon ID {identity}",
                    "url": html.unescape(url).strip(),
                    "excerpt": excerpt,
                })
        return {"entries": entries}

    @staticmethod
    def records(source, response, cached):
        """Extract source text without treating same-name records as one identity."""
        records = []
        if source["adapter"] == "humanistica-plato":
            items = response.get("people", [])
            kind = "plato_prosopography"
        else:
            items = response.get("entries", [])
            kind = "scholarly_prosopography"
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            records.append({
                "kind": kind,
                "title": item.get("title"),
                "url": item.get("url"),
                "excerpt": item.get("excerpt"),
                "minimum_statements": source.get("minimum_statements", 0),
                "citations": item.get("citations", []),
                "names": [item.get("title", ""), item.get("greek", "")],
            })
        valid = []
        for record in records[:source["limit"]]:
            if not all(isinstance(record[key], str) and record[key].strip()
                       for key in ("title", "url", "excerpt")):
                continue
            parsed = urlsplit(record["url"])
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
            valid.append({**record, "provider": source["name"],
                          "source_id": source["id"], "cached": cached})
        return valid

    def retrieve(self, lemma, cached_json):
        """Retrieve only enabled sources and deduplicate URLs across configurations."""
        records, warnings, seen = [], [], set()
        for source in self.sources:
            if not source["enabled"]:
                continue
            try:
                response, cached, _timestamp = cached_json(self.request_url(source, lemma))
                if not isinstance(response, dict) or "error" in response:
                    raise ValueError("Source returned an error or invalid response")
                for record in self.records(source, response, cached):
                    identity = record["url"].rstrip("/")
                    if identity not in seen:
                        seen.add(identity)
                        records.append(record)
            except (OSError, TimeoutError, ValueError, RuntimeError) as error:
                warnings.append(f"{source['name']} lookup failed: {type(error).__name__}: {error}")
        return records, warnings
