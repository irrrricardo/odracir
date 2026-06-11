"""Shared names for future hippocampus memory namespaces."""

from typing import Literal

MemoryNamespace = Literal[
    "literature",
    "conversation",
    "project",
    "skill",
    "user",
    "tool",
    "logic",
]

MEMORY_NAMESPACES: tuple[MemoryNamespace, ...] = (
    "literature",
    "conversation",
    "project",
    "skill",
    "user",
    "tool",
    "logic",
)
