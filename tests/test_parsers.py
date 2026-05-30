from pathlib import Path

import pytest

from odracir.parsers import ParserRegistration, ParserRegistry


def test_parser_registry_routes_registered_parser(tmp_path) -> None:
    source_path = tmp_path / "paper.pdf"
    source_path.write_bytes(b"data")
    registry = ParserRegistry()
    registry.register(
        ParserRegistration(
            name="stub",
            file_types=("pdf",),
            parse=lambda path: {"source": path.name},
        )
    )

    assert registry.parse(source_path, "stub") == {"source": "paper.pdf"}


def test_parser_registry_reports_unknown_parser() -> None:
    registry = ParserRegistry()

    with pytest.raises(ValueError, match="Unknown parser"):
        registry.get("missing")


def test_parser_registry_rejects_unsupported_file_type(tmp_path) -> None:
    registry = ParserRegistry()
    registry.register(
        ParserRegistration(name="pdf-only", file_types=("pdf",), parse=lambda path: {})
    )

    with pytest.raises(ValueError, match="does not support"):
        registry.parse(Path(tmp_path / "notes.txt"), "pdf-only")
