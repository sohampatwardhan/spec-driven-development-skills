# Dependency evidence policy

Load this policy only when a feature selects, changes, integrates, or releases a material
third-party dependency. It supplements broad security and authorization review.

## Status and freshness

- Modes are `change`, `main`, and `release`.
- Results are `pass`, `warnings`, `blocked`, `unavailable`, or `invalid`.
- `pass` and explicitly reviewed `warnings` use exit `0`; warnings are never called clean.
- `blocked`, `unavailable`, and `invalid` use exits `1`, `2`, and `3` and fail closed.
- Delivery evidence must be no more than 24 hours old and not future-dated.

## Design contract

For each material dependency, record its exact resolved version, trigger/mode, Markdown links to
the current JSON and Markdown reports, result, and decision. If no material dependency applies,
retain the section with a concise reason. Identify required future `main` and `release` gates.

## Resolution-change contract

A `Dependency resolution: change` leaf owns every applicable exact manifest and lock/resolution
path, including the nearest applicable ancestor workspace lock. Preserve this order:

1. Review Current Technology Evidence and query current documentation when needed.
2. Run `dependency-security-audit` in `change` mode and review both linked reports.
3. Edit dependency resolution and run relevant project tests.
4. Run a fresh post-change `change` audit and review both new linked reports.

The pre/post sequence spans at most seven days; the post report is at most 24 hours old. A task
declaring `none` must not change manifests, locks, versions, pins, or resolution.

## Evidence records

Unchecked leaves use the exact pending records from [artifacts.md](artifacts.md), with safe plain
project-relative `expected_*` paths. Before checking a leaf, replace them with correlated completed
records whose linked targets exist inside the project. Narrative prose cannot replace canonical
fields, links, status, freshness, report review, or exit semantics. Protected-main uses a fresh
`main` record; release uses a fresh `release` record.
