"""Replaceable parser registry for normalized document extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ParseDocument = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class ParserRegistration:
    """A parser implementation and the file types it accepts."""

    name: str
    file_types: tuple[str, ...]
    parse: ParseDocument


class ParserRegistry:
    """Resolve parser implementations without coupling the harness to one library."""

    def __init__(self) -> None:
        self._parsers: dict[str, ParserRegistration] = {}

    def register(self, parser: ParserRegistration) -> None:
        if not parser.name:
            raise ValueError("Parser name must not be empty.")
        if parser.name in self._parsers:
            raise ValueError(f"Parser {parser.name!r} is already registered.")
        self._parsers[parser.name] = parser

    def parse(self, source_path: Path, parser_name: str) -> dict[str, Any]:
        parser = self.get(parser_name)
        file_type = source_path.suffix.lower().lstrip(".")
        if file_type not in parser.file_types:
            supported = ", ".join(parser.file_types)
            raise ValueError(
                f"Parser {parser_name!r} does not support {file_type!r}; "
                f"supported types: {supported}."
            )
        return parser.parse(source_path)

    def get(self, parser_name: str) -> ParserRegistration:
        try:
            return self._parsers[parser_name]
        except KeyError as exc:
            available = ", ".join(self.names()) or "none"
            raise ValueError(
                f"Unknown parser {parser_name!r}. Available parsers: {available}."
            ) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._parsers))
