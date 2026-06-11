"""Architectural boundary for Odracir's memory brain region."""

HIPPOCAMPUS_NAME = "hippocampus"

HIPPOCAMPUS_BOUNDARY = {
    "role": "memory brain region",
    "owns": [
        "durable memory substrate",
        "memory namespaces",
        "memory links",
        "retrieval-ready context",
        "memory provenance",
    ],
    "does_not_own": [
        "global task orchestration",
        "agent routing",
        "provider selection",
        "permission policy",
        "final answer evaluation",
    ],
}
