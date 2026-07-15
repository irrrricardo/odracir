# Formal output operating rules

These rules apply recursively to `data/formal_outputs/`.

## Canonical hierarchy

Every formal run must use this hierarchy:

```text
data/formal_outputs/
  <major>_<minor>_version/
    <long_horizon|short_horizon>/
      <group_label>/
        run-<YYYYMMDDTHHMMSSZ>/
```

- The version directory records the Odracir producer version, for example
  `2_0_version`. A material change to extraction, prompts, storage contracts,
  canonicalization, quality policy, Recon, or batching requires at least a minor
  package-version bump and a new version directory before producing formal output.
  Patch-only changes that affect formal output are not allowed, because the directory
  label intentionally uses `<major>_<minor>`.
- A group label has the form `<long|short>_<source_group_id>_<effective_count>`.
  `effective_count` is the number of Recon representatives after byte-identical PDF
  deduplication, not the raw PDF count and not the number of successful packets.
- A timestamp distinguishes executions of the same version and group. It must never
  be the only corpus identifier.
- New writes must target the real versioned path. Never write through a legacy
  compatibility symlink at the root of `formal_outputs`.

## Required run metadata

Each run must contain `run_metadata.json` with at least:

- layout and producer versions;
- source revision;
- horizon, source group ID, group label, raw input count, and effective count;
- UTC run ID;
- paths to input indexes and preflight artifacts;
- named attempts and their purpose/configuration;
- selected extraction, assembly, finalization, and release artifacts;
- success/failure counts and relevant content digests.

Paths added by repository-maintained metadata must be relative to the run or group
root. Do not introduce new machine-specific absolute paths.

## Attempt and selection names

- Put experimental executions under a semantic stage and an explicit attempt ID,
  such as `attempts/extraction/provenance_fewshot/` or
  `attempts/recovery/failed_papers_pass_1/`.
- Do not create new ambiguous names such as `final`, `final-v2`, `full-19`, `retry2`,
  or `final-reconciliation`.
- Record the chosen artifacts in `run_metadata.json` and expose stable semantic
  pointers under `selected/`, using names such as `extraction` and `finalization`.
  Selection is metadata; it must not erase unsuccessful or superseded attempts.

## Integrity and relocation

- Treat completed run artifacts as immutable. Do not edit generated manifests,
  content-addressed files, `.sha256` files, receipts, ledgers, or audit reports to
  make a path look newer.
- If a historical relocation is necessary, move the complete artifact tree without
  changing bytes, add a documented read-only compatibility link when old absolute
  paths must remain resolvable, and verify the existing checksum chain.
- A compatibility link is never a canonical destination for a new run.
- Preserve user-owned corpus inputs and unrelated working-tree changes.

## Handoff checks

Before declaring a formal-output change complete, verify:

1. the canonical version/horizon/group/run path exists;
2. group counts agree with Recon and run metadata;
3. selected pointers resolve to the declared artifacts;
4. historical compatibility paths still resolve when retained;
5. existing checksum and audit verification still passes;
6. `git status` contains no unintended corpus-input changes.
