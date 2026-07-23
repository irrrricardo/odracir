#!/usr/bin/env python3
"""Run SciEngram Core with the audited ``none`` negation compatibility fix.

SciEngram Core v1 models a canonical claim as a positive proposition family and
uses a paper assertion's polarity as its stance toward that family.  The pinned
Core build recognizes ``no`` and ``does not`` but omits ``none`` from its surface
negation pattern; it also strips ``no`` from the lexical baseline name
``no-change``.  This makes the canonical display semantically misleading.  The
fail-closed wrapper patches only those two lexical cases before invoking the
stock CLI.
"""

from __future__ import annotations

import json
import hashlib
import re
import sys
from pathlib import Path

from sciengram_core import relations
from sciengram_core.version import CORE_VERSION


PATCH_ID = "sciengram-core-negation-none-and-no-change/v2"
UPSTREAM_PATTERN = (
    r"\b(failed to|fails to|does not|did not|cannot|can't|neither|never|without|not|no)\b"
)
PATCHED_PATTERN = (
    r"\b(failed to|fails to|does not|did not|cannot|can't|neither|none(?:\s+of)?|never|without|not|no(?!-))\b"
)


def apply_compatibility_patch() -> dict[str, str]:
    """Patch the pinned regex, refusing unknown upstream implementations."""

    actual = relations.NEGATION_RE.pattern
    if actual != UPSTREAM_PATTERN:
        raise RuntimeError(
            "SciEngram Core NEGATION_RE changed; review the compatibility patch "
            f"before building a release (actual={actual!r})"
        )
    relations.NEGATION_RE = re.compile(PATCHED_PATTERN, re.IGNORECASE)
    return {
        "patch_id": PATCH_ID,
        "upstream_pattern": UPSTREAM_PATTERN,
        "patched_pattern": PATCHED_PATTERN,
        "reason": (
            "Normalize 'none'/'none of' into the positive proposition family, "
            "preserve the lexical comparator name 'no-change', and retain the "
            "source assertion's explicit negative polarity."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    patch = apply_compatibility_patch()
    if arguments == ["--compat-info"]:
        print(json.dumps(_compat_info(patch), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if len(arguments) == 2 and arguments[0] == "--compat-info-output":
        path = Path(arguments[1]).expanduser().resolve()
        payload = _compat_info(patch)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        print(json.dumps({"compatibility_manifest": str(path)}, sort_keys=True))
        return 0
    from sciengram_core.cli import main as core_main

    return core_main(arguments)


def _compat_info(patch: dict[str, str]) -> dict[str, str]:
    upstream_path = Path(relations.__file__).resolve()
    wrapper_path = Path(__file__).resolve()
    return {
        **patch,
        "sciengram_core_version": CORE_VERSION,
        "upstream_relations_path": str(upstream_path),
        "upstream_relations_sha256": _sha256(upstream_path),
        "wrapper_path": str(wrapper_path),
        "wrapper_sha256": _sha256(wrapper_path),
    }


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
