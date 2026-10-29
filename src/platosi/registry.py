"""Discover providers from manifests without importing provider-specific code."""

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
from typing import Any


@dataclass
class RegisteredProvider:
    manifest: dict[str, Any]
    directory: Path
    root: Path
    enabled: bool

    def load(self):
        module_path = self.directory / self.manifest["module"]
        spec = importlib.util.spec_from_file_location(
            "platosi_plugin_" + self.manifest["id"].replace("-", "_"), module_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load provider module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.create_provider(self.manifest, self.root)


class Registry:
    def __init__(self, root: Path, plugins: Path | None = None, config: Path | None = None):
        self.root = root.resolve()
        self.plugins = (plugins or self.root / "plugins").resolve()
        self.config = config or self.root / "data" / "plugin-config.json"
        self.overrides = json.loads(self.config.read_text(encoding="utf-8")) if self.config.exists() else {}
        self.providers: dict[str, RegisteredProvider] = {}
        if not self.plugins.is_dir():
            return
        for path in sorted(self.plugins.glob("*/plugin.json")):
            m = json.loads(path.read_text(encoding="utf-8"))
            for field in ("id", "type", "version", "module", "capabilities", "source", "license"):
                if field not in m:
                    raise ValueError(f"{path}: missing required field {field}")
            pid = m["id"]
            if pid in self.providers:
                raise ValueError(f"Duplicate provider id: {pid}")
            m["config"] = {**m.get("config", {}), **self.overrides.get(pid, {}).get("config", {})}
            enabled = self.overrides.get(pid, {}).get("enabled", m.get("enabled_by_default", True))
            self.providers[pid] = RegisteredProvider(m, path.parent, self.root, enabled)

    def set_enabled(self, provider_id: str, enabled: bool):
        if provider_id not in self.providers:
            raise ValueError(f"Unknown provider: {provider_id}")
        self.overrides.setdefault(provider_id, {})["enabled"] = enabled
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(json.dumps(self.overrides, indent=2) + "\n", encoding="utf-8")
        self.providers[provider_id].enabled = enabled

    def active(self, capability: str):
        for registration in self.providers.values():
            if registration.enabled and capability in registration.manifest["capabilities"]:
                provider = registration.load()
                if provider.available():
                    yield registration, provider

    def statuses(self):
        result = []
        for registration in self.providers.values():
            m = registration.manifest
            provider = registration.load() if registration.enabled else None
            available = provider.available() if provider else None
            result.append({"id": m["id"], "type": m["type"], "version": m["version"],
                           "capabilities": m["capabilities"], "enabled": registration.enabled,
                           "available": available, "config": m["config"],
                           "unavailable_reason": ("Source or current index missing; check configuration and rebuild."
                                                  if provider and not available else None),
                           "source": m["source"], "license": m["license"]})
        return result
