# 613 Coding Package Rename Design

## Goal

Make the public project, Python distribution, executable command, and import package use the approved 613 Coding naming without retaining legacy aliases.

## Naming Contract

| Surface | New name |
| --- | --- |
| Product | `613 Coding` |
| Repository | `613-coding` |
| Python distribution | `613-coding` |
| Console command | `613-coding` |
| Python import package | `coding613` |
| Persistent state directory | `.613-coding` |
| Keyring service namespace | `613-coding` |

The legacy distribution and command `coding-harness`, import package `coding_harness`, and keyring service namespace `coding-harness` are removed. No compatibility module, secondary console entry point, warning shim, or keyring migration is provided.

## Source And Packaging Changes

Rename `src/coding_harness` to `src/coding613` while preserving its internal module boundaries. Rewrite all production imports, test imports, string-based monkeypatch targets, package-resource paths, and entry-point references to `coding613`.

Set `project.name` to `613-coding` and expose only the `613-coding = "coding613.cli.entrypoint:main"` console script. Regenerate `uv.lock` through `uv`; normalized wheel and metadata names may use `613_coding` as required by Python packaging standards. Keep version `0.1.0` because this repository has not established a published compatibility contract requiring a version migration.

## Runtime And Credential Changes

Change the Docker entrypoint to invoke `613-coding web`. Update the Keyring adapter's default service namespace to `613-coding`; credentials stored under the old namespace intentionally become undiscoverable and must be entered again.

The `.613-coding` persistence directory, SQLite schema, LanceDB layout, domain data, API routes, and application behavior do not change. Existing persisted runs remain readable because the rename changes Python and distribution identifiers, not stored model formats.

## Documentation And Delivery

Update README, deployment instructions, AGENTS workflow text, Docker comments, examples, and other public command references. Historical delivery evidence remains historically accurate and is not mechanically rewritten unless it presents an obsolete command as current guidance.

Build and deploy a new immutable image to `edward@int21`, preserving the current loopback bind, persistent data mount, resource limits, security settings, and reverse-proxy boundary. Verify old persisted run retrieval after the container replacement.

## Testing

Follow TDD by first changing distribution tests to require:

- distribution name `613-coding`;
- exactly one console script named `613-coding` targeting `coding613.cli.entrypoint:main`;
- successful import of `coding613`;
- absence of a `coding_harness` import package in the built wheel;
- Docker entrypoint invocation of `613-coding`.

The focused tests must fail against the current package before the rename. After implementation, run the full offline test suite, Ruff, mypy, `uv lock --check`, `uv build`, installed-wheel CLI smoke, local Docker smoke, GitHub CI, and remote deployment health/persistence smoke.

## Acceptance Criteria

1. `uv build` produces a `613_coding` wheel and `613-coding` distribution metadata.
2. A clean installation exposes `613-coding` and does not expose `coding-harness`.
3. `import coding613` succeeds and `import coding_harness` fails in a clean installation.
4. Source and tests contain no active `coding_harness` import or monkeypatch target.
5. The Docker image starts through `613-coding web` and passes the existing non-root health smoke.
6. The Keyring adapter uses service name `613-coding`.
7. Full local verification and GitHub CI pass.
8. `edward@int21` runs the renamed image at `127.0.0.1:8613`, with existing persisted state intact.

## Non-Goals

- Renaming the Git repository or product display name, which are already correct.
- Changing API paths, database schemas, state directory names, agent behavior, or UI workflows.
- Providing legacy aliases, import shims, credential migration, or dual-published distributions.
