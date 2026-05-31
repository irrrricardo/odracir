"""Inspectable optional capabilities for external document tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from odracir.docling_adapter import detect_docling_capability
from odracir.ocr import detect_ocrmypdf_capability


@dataclass(frozen=True)
class CapabilityReport:
    parser_backends: list[dict[str, Any]]
    preprocessors: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_capability_report() -> CapabilityReport:
    docling = detect_docling_capability()
    ocrmypdf = detect_ocrmypdf_capability()
    return CapabilityReport(
        parser_backends=[
            {
                "name": "pymupdf",
                "available": True,
                "detail": "Default lightweight PDF parser backend.",
            },
            docling.as_dict(),
        ],
        preprocessors=[ocrmypdf.as_dict()],
    )


def format_capability_report(report: CapabilityReport) -> str:
    lines = ["Parser backends:"]
    lines.extend(_format_capability(item) for item in report.parser_backends)
    lines.append("Preprocessors:")
    lines.extend(_format_capability(item) for item in report.preprocessors)
    return "\n".join(lines)


def _format_capability(capability: dict[str, Any]) -> str:
    state = "available" if capability["available"] else "unavailable"
    version = capability.get("version")
    suffix = f" ({version})" if version else ""
    return f"- {capability['name']}: {state}{suffix}. {capability['detail']}"
