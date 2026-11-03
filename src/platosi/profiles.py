"""Persistent reader preferences and per-inquiry provider selection."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


def _validate_resources(resources: Any) -> list[str]:
    if not isinstance(resources, list) or any(
        not isinstance(item, str) or not item or item.strip() != item for item in resources
    ):
        raise ValueError("Resources must be a list of nonempty provider IDs without surrounding whitespace")
    if len(set(resources)) != len(resources):
        raise ValueError("Resource IDs must not be repeated")
    return resources


class Profiles:
    def __init__(self, root: Path):
        self.path = root / "data" / "reader-profiles.json"
        self.profiles = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        if not isinstance(self.profiles, dict):
            raise ValueError("Reader profiles must be a JSON object")
        for name, profile in self.profiles.items():
            self._validate(name, profile)

    @staticmethod
    def _validate(name: str, profile: Any) -> None:
        if not isinstance(name, str) or not name or name.strip() != name:
            raise ValueError("Profile name must be nonempty and have no surrounding whitespace")
        if not isinstance(profile, dict) or set(profile) != {"resources", "text_first"}:
            raise ValueError(f"Profile {name!r} must contain resources and text_first")
        _validate_resources(profile["resources"])
        if not isinstance(profile["text_first"], bool):
            raise ValueError(f"Profile {name!r} text_first must be a boolean")

    def get(self, name: str) -> dict[str, Any]:
        if name not in self.profiles:
            raise ValueError(f"Unknown reader profile: {name}")
        return self.profiles[name]

    def save(self, name: str, resources: list[str], text_first: bool) -> None:
        profile = {"resources": resources, "text_first": text_first}
        self._validate(name, profile)
        updated = {**self.profiles, name: profile}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".reader-profiles-", suffix=".tmp", delete=False
            ) as output:
                temporary = Path(output.name)
                json.dump(updated, output, ensure_ascii=False, indent=2)
                output.write("\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.profiles = updated


def select(registry, capability: str, profile: dict[str, Any] | None = None,
           include: list[str] | None = None, exclude: list[str] | None = None,
           *, tolerate_errors: bool = False):
    """Resolve an inquiry without changing reader preferences or provider state."""
    include = _validate_resources(include or [])
    exclude = _validate_resources(exclude or [])
    conflicts = set(include) & set(exclude)
    if conflicts:
        raise ValueError(f"Cannot both include and exclude: {', '.join(sorted(conflicts))}")
    explicit = bool(include)
    ids = include if explicit else (
        profile["resources"] if profile is not None else list(registry.providers)
    )
    selected = []
    active = []
    for provider_id in ids:
        if provider_id in exclude:
            continue
        registration = registry.providers.get(provider_id)
        state = {"id": provider_id, "installed": registration is not None,
                 "enabled": None, "available": None, "reason": None}
        selected.append(state)
        if registration is None:
            state["reason"] = "not installed"
            continue
        state["enabled"] = registration.enabled
        manifest = registration.manifest
        if profile is not None and profile["text_first"] and not explicit and manifest["type"] != "corpus":
            state["reason"] = "text-first mode"
        elif not registration.enabled:
            state["reason"] = "disabled"
        elif capability not in manifest["capabilities"]:
            state["reason"] = f"does not support {capability}"
        else:
            try:
                provider = registration.load()
                state["available"] = provider.available()
                if state["available"]:
                    active.append((registration, provider))
                else:
                    state["reason"] = "source or current index unavailable"
            except (OSError, RuntimeError, ValueError, ImportError, sqlite3.Error) as error:
                if not tolerate_errors:
                    raise
                state["available"] = False
                state["reason"] = f"provider error: {error}"
    return selected, active
