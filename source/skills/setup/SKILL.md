---
name: setup
description: Use when installing Graphify. Configure Vault and folder safely.
version: 0.2.1
license: MIT
platforms: [windows]
---

# Install Graphify code context

## Inputs and scope

Ask only for an existing absolute Obsidian Vault path and the Graphify folder relative to that Vault, e.g. `AgentData/Graphify`. Discover Hermes/Python/Graphify runtime paths. Installation affects the intended current Profile only; no other/future Profile deployment, scheduler, watcher or Core modifications.

The public repository is `gary3207/Hermes_Plugin_00.Graphify`. Private forks require their own authorized access; installation does not restore authentication, project source code or private Vault history. Never obtain a token/password in chat or include authentication in config or commands.

## Native Git installation

1. Read Repository README and inspect the intended source. Resolve the exact reviewed 40-character commit SHA.
2. Install `hermes plugins install gary3207/Hermes_Plugin_00.Graphify/source --ref <exact-SHA>` in the intended Profile. Honor capability/dependency consent. Never bypass native scanning.
3. If not explicitly disabled by the user, enable with `hermes plugins enable graphify-context --no-allow-tool-override`. Do not silently override explicit disablement.
4. Verify fresh CLI discovery and Plugin version with `hermes plugins list --plain --no-bundled` and `hermes graphify --help`.
5. Run `hermes graphify setup --vault "<Vault>" --folder "<relative-folder>"`. If Graphify 0.9.77 is absent, obtain consent and add `--install-graphify`; it uses an isolated uv tool environment, not raw pip in the Hermes environment.

## ZIP/local bootstrap alternative

Extract the distribution without mixing it with runtime or Vault data. Run `python source/bootstrap.py --vault "<Vault>" --folder "<relative-folder>"` using an available Python. It discovers the Hermes launcher, installs only its allowlisted Plugin files in the current Profile and runs setup. An optional `--home` is for an explicitly selected isolated test home; never guess another Profile. Unknown collision or user-edited installed payload must be preserved, not forcibly replaced.

## Verify and hand off

- `hermes graphify status`: actual configured destination, dependency, ownership ledger and last-run errors.
- Use a small temporary project containing `source/` to run `sync --project`, `query`, `explain` and `affected`. Confirm actual source file locations, call relationships and zero LLM extraction tokens.
- Run a second setup with identical inputs and check unchanged indexes. Preserve authored notes and existing ledger. Unknown existing Graphify files without ownership evidence must not be automatically adopted based on `generated: true` alone.
- A destination change requires separate migration. Same Vault/folder with preserved ownership ledger can reconnect after local runtime loss. Moving to another PC requires source/project reconnection; old absolute paths are not proof of available source.
- Start a new session to receive configuration-based guidance; never rewrite a live session's past system prompt.
- Report setup/configuration, extraction/query tests and fresh-OS verification separately. A same-host disposable home is not a clean PC test.
- Disable/uninstall with the native Plugin manager; Vault data is retained. No scheduled task is created by this package.

Graphify failures are advisory for code editing, but installation verification must report errors and incomplete steps rather than declaring success.
