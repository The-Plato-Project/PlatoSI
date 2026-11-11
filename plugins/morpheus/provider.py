"""In-process Ancient Greek morphology through the pure-Python ikelos port."""

from dataclasses import asdict, is_dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
import re
import unicodedata

from platosi.unicode_search import key


POLICY = "ikelos-morpheus-v1"
FEATURE_VALUES = {
    "aor": "aorist",
    "imperf": "imperfect",
    "pres": "present",
    "perf": "perfect",
    "plup": "pluperfect",
    "fut": "future",
    "futperf": "future perfect",
    "ind": "indicative",
    "subj": "subjunctive",
    "opt": "optative",
    "inf": "infinitive",
    "imperat": "imperative",
    "part": "participle",
    "act": "active",
    "mid": "middle",
    "pass": "passive",
    "mp": "middle/passive",
    "masc": "masculine",
    "fem": "feminine",
    "neut": "neuter",
    "nom": "nominative",
    "gen": "genitive",
    "dat": "dative",
    "acc": "accusative",
    "voc": "vocative",
    "nom/voc": "nominative/vocative",
    "sg": "singular",
    "pl": "plural",
}


class MorpheusProvider:
    def __init__(self, manifest, root):
        del root
        self.manifest = manifest
        config = manifest["config"]
        self.strict_case = config["strict_case"]
        if not isinstance(self.strict_case, bool):
            raise ValueError("Morpheus strict_case must be boolean")
        self.expected_version = config["ikelos_version"]
        if not isinstance(self.expected_version, str) or not self.expected_version:
            raise ValueError("Morpheus ikelos_version must be nonempty text")
        self._ikelos = None

    def _library(self):
        if self._ikelos is None:
            try:
                installed = version("ikelos")
            except PackageNotFoundError as error:
                raise ImportError(
                    "ikelos is not installed; install requirements-morphology-build.txt"
                ) from error
            if installed != self.expected_version:
                raise RuntimeError(
                    f"ikelos {self.expected_version} is required; found {installed}"
                )
            self._ikelos = import_module("ikelos")
        return self._ikelos

    def available(self):
        try:
            self._library()
        except (ImportError, RuntimeError):
            return False
        return True

    @staticmethod
    def _form(form, mode):
        if mode != "exact":
            raise ValueError("Morpheus supports exact NFC input only")
        if (
            not isinstance(form, str)
            or not form
            or len(form) > 200
            or form != form.strip()
            or not any("GREEK" in unicodedata.name(char, "") for char in form)
            or any(
                not (
                    unicodedata.category(char).startswith("M")
                    or (
                        unicodedata.category(char).startswith("L")
                        and "GREEK" in unicodedata.name(char, "")
                    )
                    or char in "'’᾽-"
                )
                for char in form
            )
        ):
            raise ValueError("Morpheus requires one Greek word of at most 200 characters")
        return key(form)

    def analyze(self, form, mode, limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Morpheus limit must be a positive integer")
        return self._analyze_complete(self._form(form, mode))[:limit]

    def analyze_complete(self, form):
        return self._analyze_complete(self._form(form, "exact"))

    def _analyze_complete(self, form):
        records = []
        seen = set()
        for item in self._library().analyze(form, strict_case=self.strict_case):
            if not isinstance(item.lemma, str) or not item.lemma:
                raise ValueError("ikelos returned an invalid lemma")
            match = re.fullmatch(r"([^\s0-9]+)([0-9]+)?", key(item.lemma))
            if match is None:
                raise ValueError("ikelos returned an invalid Greek headword")
            lemma, homograph = match.groups()
            raw = asdict(item) if is_dataclass(item) else {
                name: getattr(item, name)
                for name in (
                    "form", "lemma", "pos", "features", "dialects", "flags",
                    "stemtype", "derivtype", "beta_form", "beta_lemma", "perseus",
                )
            }
            identity = raw["perseus"]
            if identity in seen:
                continue
            seen.add(identity)
            features = {
                "part_of_speech": item.pos,
                **{
                    name: FEATURE_VALUES.get(value, value)
                    for name, value in item.features.items()
                },
            }
            if item.stemtype:
                features["stem_type"] = item.stemtype
            if item.derivtype:
                features["derivation_type"] = item.derivtype
            if item.dialects:
                features["dialect"] = ", ".join(item.dialects)
            records.append({
                "evidence_type": "candidate_analysis",
                "provider": self.manifest["id"],
                "provider_version": self.manifest["version"],
                "source": self.manifest["source"],
                "license": self.manifest["license"],
                "form": form,
                "lemma": lemma,
                "method": "ikelos",
                "classification": "morphological_analysis_candidate",
                "analysis": {
                    "lemma": lemma,
                    "lang": "grc",
                    "headword": item.lemma,
                    "homograph": homograph,
                    "features": features,
                    "proper": lemma[0].isupper(),
                    "proper_basis": "Morpheus headword capitalization",
                    "tag": "; ".join(features.values()),
                    "raw": raw,
                    "engine": {
                        "name": "ikelos",
                        "version": self.expected_version,
                    },
                },
                "settings": {"strict_case": self.strict_case},
                "limitations": "Possible morphological reading from the pure-Python "
                               "Morpheus port; context and referent are not resolved.",
            })
        return records

    def index_identity(self):
        return {
            "provider": self.manifest["id"],
            "provider_version": self.manifest["version"],
            "policy": POLICY,
            "source": self.manifest["source"],
            "strict_case": self.strict_case,
            "ikelos_version": self.expected_version,
        }


def create_provider(manifest, root):
    return MorpheusProvider(manifest, root)
