"""Provider contracts. Results are JSON-compatible, source-attributed records."""

from typing import Any, Protocol
from platosi.cancellation import Cancellation


class Provider(Protocol):
    def build(self) -> dict[str, Any]: ...
    def available(self) -> bool: ...


class CorpusProvider(Provider, Protocol):
    def search(self, query: str, mode: str, limit: int) -> list[dict[str, Any]]: ...
    def passage(self, edition: str, citation: str) -> list[dict[str, Any]]: ...


class ReadingProvider(Protocol):
    def reading(self, edition: str, citation: str) -> list[dict[str, Any]]: ...


class DictionaryProvider(Provider, Protocol):
    def lookup(self, headword: str, mode: str, limit: int) -> list[dict[str, Any]]: ...


class MorphologyProvider(Provider, Protocol):
    def analyze(self, form: str, mode: str, limit: int) -> list[dict[str, Any]]: ...


class LanguageModelProvider(Protocol):
    def available(self) -> bool: ...
    def list_models(self) -> list[dict[str, Any]]: ...
    def generate(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]: ...


class ChatLanguageModelProvider(LanguageModelProvider, Protocol):
    def chat(self, messages: list[dict[str, str]], options: dict[str, Any],
             cancellation: Cancellation) -> dict[str, Any]: ...


class ScholarlyResourceProvider(Protocol):
    def retrieve(self, query: dict[str, Any]) -> list[dict[str, Any]]: ...
