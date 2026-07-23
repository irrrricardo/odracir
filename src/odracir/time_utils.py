"""Shared timestamp helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def china_tz() -> timezone:
    return timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_iso() -> str:
    return datetime.now(china_tz()).isoformat(timespec="seconds")
