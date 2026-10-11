---
name: graphify-context
description: Use when changing code. Find reuse and impact first.
version: 0.2.0
license: MIT
platforms: [windows]
---

# Graphify code context

This Plugin is current-Profile-only. No scheduler, watcher, automatic Profile deployment, MCP or editing gate.

## Resolve configuration

1. Confirm the task's real project root, not the Profile home. Run `hermes graphify status` to obtain the configured Graphify root and health. For a named Profile invoke its CLI in that same Profile; never switch another Profile's configuration.
2. Read `<graphify_root>/00_Index.md` and the matched project's `00_Project.md`, authored `10_Architecture.md` and `20_Reuse.md`. Never ingest the whole graph as prompt context.
3. Missing configuration: load `graphify-context:setup`. Do not invent a Vault. A remote terminal must be separately installed/configured on that host; local paths are not automatically remote paths.

## Code workflow

- If freshness is uncertain, run `hermes graphify sync --project "<actual-project-root>"` once before substantive work.
- Search all projects for existing equivalents: `hermes graphify query "<feature>"`.
- Trace the real project: `hermes graphify explain "<symbol>" --project "<actual-project-root>"` and `hermes graphify affected "<symbol>" --project "<actual-project-root>"`.
- Read relevant original definitions and ALL callers. Similar names are candidates, not equivalent behavior; AST extraction can miss dynamic dependencies.
- Reuse existing code, make the smallest appropriate change and run real tests.
- After source changes refresh only that project with `hermes graphify sync --project "<actual-project-root>"`. No commit/stash/clean requirement.
- Update Architecture/Reuse only for verified contracts or reusable behavior. Keep user-authored notes, decisions and evidence separate from generated indexes.

## Limits and safety

- v0.2 analyzes supported code under project `source/`, preserving the current integration's scope. It does not automatically relocate an existing src/lib/root layout. If that project's code lives elsewhere, report the unsupported scope and use original search/tests instead of claiming it was indexed.
- Source/cache/vendor/build/runtime/authentication files are excluded. Graphify extraction is code-only with one worker and no LLM semantic extraction.
- Graphs retain project namespaces, directed and parallel relations. Equal names never fabricate cross-project dependencies. A project without supported source gets a project node, not invented code.
- Local extraction is not guaranteed redaction: hardcoded secrets can appear in labels. Do not publish Vault graphs or caches in Git.
- Failure, stale output, missing dependency or busy lock: continue original source search and tests. Do not add approval gates or deny code edits.
- Read JSON `success` and `errors`, not just exit status. Check `indexed_at`, source fingerprint, graph hash and original source locations. Graph success is not test success.
- Preserve `.graphify-owner.json` with the Vault for same-destination reinstall. Never delete/edit the ledger to bypass ownership conflicts. A manual edit to generated output fails closed; authored Architecture/Reuse is preserved.
- Same-machine multiple manually installed Profiles can reference one destination. Multi-PC concurrent writing through cloud sync is not supported; use one writer or separate output folders.
