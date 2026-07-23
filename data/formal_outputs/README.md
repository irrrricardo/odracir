# Formal output layout

Formal Odracir output is organized by producer version, horizon, corpus group, and
execution time:

```text
data/formal_outputs/
  2_0_version/
    long_horizon/
      long_1_19/
        group_manifest.json
        preflight-20260713T015531Z/
        preflight-v2-20260713T015531Z/
        run-20260713T015531Z/
    short_horizon/
```

The group label is `<long|short>_<source_group_id>_<effective_count>`. Thus
`long_1_19` means long-horizon source group 1 with 19 representatives after Recon
deduplicated the 20 input PDFs. The count describes corpus scope; it does not change
when an individual attempt partially fails.

Dates remain useful run IDs, but they are never used as the version or corpus-group
identity. A future material Odracir change must first bump at least the minor package
version and use a new version root such as `2_1_version`; a semantics-changing patch
must not be hidden inside the existing `2_0_version` directory.

## Current Odracir 2.0 run

The machine-readable entry points are:

- `2_0_version/version_manifest.json`
- `2_0_version/long_horizon/long_1_19/group_manifest.json`
- `2_0_version/long_horizon/long_1_19/run-20260713T015531Z/run_metadata.json`
- `.../run-20260713T015531Z/selected/extraction`
- `.../run-20260713T015531Z/selected/finalization`

The names inside the migrated historical run, including `full-19-recovered` and
`final-reconciliation`, are preserved byte-for-byte because they occur in manifests
and a chained SHA-256 audit. They are historical attempt names, not templates for new
runs. The `selected/` links and `run_metadata.json` provide the stable semantic view.

`data/formal_outputs/long_horizon` is a read-only compatibility link to
`2_0_version/long_horizon/long_1_19`. It keeps historical absolute paths resolvable;
new commands must never use it as an output destination.

Operational requirements for agents and automation are in `AGENTS.md` in this
directory.
