# Hermes_Plugin_00.Graphify

Private distribution of the `graphify-context` Hermes plugin, version **0.2.0**.
It connects project code graphs and a namespace-preserving global graph to an
Obsidian Vault. Obsidian does not need to be running. The initial source boundary
is each project's `source/` directory; arbitrary `src/` or `lib/` layouts are not
promised by this release.

## Requirements and scope

- Hermes with native plugin installation and plugin CLI command support.
- Python for the portable bootstrap and offline tests; Git for native installation.
- `uv` and the external CLI dependency `graphifyy==0.9.77`. Keep this dependency
  isolated with `uv tool`; do not run raw `pip` into the Hermes environment.
- An existing Obsidian Vault and a relative Graphify folder within it.

Windows is the initial tested target. Same-host isolated-home checks are not
fresh-OS installation certification; other operating systems are not yet certified.
There is no new MCP server, scheduler, watcher, automatic other-Profile deployment,
or Hermes Core/Desktop/Gateway source modification. Graphs are advisory caches,
not a requirement to permit editing code. Graph labels and absolute source paths
may be sensitive: keep the Vault and generated graphs private.

## Native install from private GitHub

Repository: `Gary-Y-Lee/Hermes_Plugin_00.Graphify` (**PRIVATE**).
Private access requires an authorized GitHub account and explicit login/consent
through your local Git credential manager or GitHub CLI. Authenticate outside chat;
never paste passwords or tokens into commands, this README, or the package.
No credentials or authentication state are bundled.

Replace `<40-character-commit-SHA>` with the full immutable SHA supplied for the
reviewed publication commit. Do not use a branch name, abbreviated SHA, or the
literal placeholder. From the intended active Hermes Profile:

```text
hermes plugins install Gary-Y-Lee/Hermes_Plugin_00.Graphify/source --ref <40-character-commit-SHA> --no-enable
hermes plugins enable graphify-context --no-allow-tool-override
hermes graphify setup --vault "C:/Notes/MyVault" --folder "Graphify"
hermes graphify status
```

If the validated Graphify CLI is absent, opt into a Profile-local tool installation:

```text
hermes graphify setup --vault "C:/Notes/MyVault" --folder "Graphify" --install-graphify
```

Start a **new Hermes session** after installation/enabling. Bundled skills are
`graphify-context:graphify-context` (code-context workflow) and
`graphify-context:setup` (installation/configuration guidance). Do not install the
legacy `source/profile/` directory as this release's plugin.

## Portable ZIP fallback

Obtain `Hermes_Plugin_Graphify.zip` through an authorized private channel and
extract it into a trusted local folder. Run from the extracted package root:

```text
python source/bootstrap.py --vault "C:/Notes/MyVault" --folder "Graphify"
```

If Graphify is missing, explicitly opt into its isolated dependency install:

```text
python source/bootstrap.py --vault "C:/Notes/MyVault" --folder "Graphify" --install-graphify
```

The only required configuration inputs are the absolute Vault path and its
relative Graphify folder. Runtime and plugin installation locations are discovered,
not additional inputs. Bootstrap resolves the active Hermes home: Hermes's
`get_hermes_home()` when available, then `HERMES_HOME`, with the platform home
fallback (Windows: `LOCALAPPDATA/hermes`). For an explicitly chosen different
Profile, use its active environment and run installation manually; no other Profile
is modified automatically. Start a new session, then inspect `hermes graphify status`.

## Commands

```text
hermes graphify setup --vault "C:/Notes/MyVault" --folder "Graphify"
hermes graphify status
hermes graphify discover
hermes graphify sync --project "C:/Projects/Example"
hermes graphify query "packaging"
hermes graphify query "packaging" --project "C:/Projects/Example"
hermes graphify explain "build" --project "C:/Projects/Example"
hermes graphify affected "build" --project "C:/Projects/Example"
```

`status` without setup reports an unset configuration; it must not invent a Vault.
`query` defaults to the integrated graph; `--project` scopes it to one project.
`explain` and `affected` require the project root. `discover` identifies projects;
`sync` refreshes the selected project's graph and integration. Review the actual
command output for errors and source locations rather than treating a zero exit
status alone as proof that a graph is fresh.

Configuration, caches, owner markers and runtime state are local to the active
home/plugin-data and configured Vault, not portable payload. Reinstall with the
same two inputs to reconnect; it does not recover deleted private data. Ownership
markers protect existing records: user-authored edits are preserved and ownership
conflicts must be resolved explicitly, not erased. Back up the Vault separately.
Disable with `hermes plugins disable graphify-context`; this does not constitute
permission to delete the Vault or private runtime state.

The configured destination is bound in Profile-local runtime data. Changing either
input to point at a different root is refused until a separately approved migration;
editing plugin configuration directly does not bypass this check. Modified or
unowned per-project graph inputs are not merged into the global graph: sync reports
an advisory failure and retains the last good integrated graph. Linked cache,
output and lock paths (including Windows junctions) are rejected before writes.

The Python bootstrap/verifier reject shell metacharacters and control characters
in arguments to Windows `.CMD`/`.BAT` launchers (`UNSAFE_BATCH_ARGUMENT`). Such
project paths are not supported through that launcher; quoting or spaces alone do
not make them safe. Native non-batch launchers keep literal argument forwarding.

## Regression checks and maintainer packaging

From the complete source checkout or extracted distribution:

```text
python -B source/test_build_package.py -v
python -B source/test_plugin.py -v
python -B source/test_graphify_ops.py -v
```

Tests are stdlib `unittest`; fixture data is created under `source/`. Packaging tests
are offline. Plugin/operations integration tests require the Graphify 0.9.77 CLI
already available on PATH, but do not make LLM calls. These checks do not require
private GitHub credentials and do not certify a fresh machine.
Do not substitute private live configuration when running downloaded-source tests.

Actual native installation smoke checks, in disposable Hermes homes:

```text
python source/verify_install.py --package "<extracted-package-root>"
python source/verify_install.py --package "<source-checkout-root>" --repository Gary-Y-Lee/Hermes_Plugin_00.Graphify/source --ref <40-character-commit-SHA>
```

The Git mode requires authenticated private repository access. These checks cover
native Plugin Doctor, exact payload bytes, repeat setup, actual extract/query/explain/
affected, zero LLM extraction tokens, preserved authored notes and unchanged other
Profile files. The verifier uses no model credentials or live Vault. `hermes skills
inspect` queries external Skill sources; it is not a bundled Plugin Skill inspector.
Use the bundled names through Agent `skill_view`, with `hermes graphify status`
showing the names and configuration-based startup guidance.

On Windows, do not nest the disposable Hermes home beneath a deeply extracted
package path: native Hermes dependency preparation may exceed Windows path limits
before this Plugin runs. Use `--work-root "C:/ShortProject/source/test-work"` to put
smoke-check fixtures under a short project source path. No system long-path policy
or Hermes source changes are made by this package.

After reviewing the production payload and running offline checks:

```text
python -B source/build_package.py
```

The stdlib builder uses only its literal `ALLOWLIST`. It copies that payload into
`source/release-repo/` and emits `Hermes_Plugin_Graphify.zip` at the project root.
Both contain `README.md`, `LICENSE`, `.gitignore`, `.gitattributes`, the production
files directly under `source/`, the two bundled skills, builder and offline tests.
No recursive project-source copy is used. Missing allowlisted files stop the build.

Existing publication `.git` metadata is untouched and never archived. Unexpected
publication files or directories, symlinks and Windows junctions fail closed before
publication writes; nothing arbitrary is deleted. Review conflicts yourself before
retrying. The ZIP is verified and atomically replaced; publication files are verified
individually, not a transactional Git operation. Run one builder at a time; do not
edit its inputs or publication tree concurrently.

Personal `graphify-config.json`, legacy `source/profile`, schedulers,
`run-discovery.pyw`, runtime/caches, private evidence, worktrees, Git metadata and
credentials are excluded. **Allowlisting is not a secret scanner**: review the
contents of the allowlisted code/tests/docs before committing or releasing.
The builder performs no commit, push, GitHub repository creation, permission change,
installation or live-environment mutation. Private publication and commit-SHA
selection are separate authorized maintainer steps.

## License

MIT for this plugin's source (see `LICENSE`). Hermes and Graphify are separate
projects with their own licenses; their binaries/dependencies are not bundled.
