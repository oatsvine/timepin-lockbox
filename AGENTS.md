# AGENTS.md

This file defines contribution rules for humans and coding agents in this repository.

## Scope

These instructions apply to the full repository rooted at this directory.

## Toolchain (required)

- Use `uv` for Python environment, dependency, and command execution tasks.
- Do not introduce `pip`, `pip-tools`, Poetry, Pipenv, or Conda workflows.
- Use `uv sync` to materialize environments.
- Use `uv run ...` for project commands.

## Dependency management

- Runtime dependencies belong in `[project].dependencies` in `pyproject.toml`.
- Development-only tools belong in `[dependency-groups].dev`.
- Keep dependency edits minimal and purpose-driven.

## Code and behavior constraints

- Preserve the CLI behavior in `main.py` unless explicitly requested.
- Keep secrets and lock artifacts out of docs/examples unless redacted.
- Avoid changing storage paths or cryptographic flow without explicit approval.

## Validation before handoff

Run these checks when relevant:

```bash
uv sync --group dev
uv run pyright
```

If a check cannot run, state exactly why.

## Documentation expectations

- Keep README aligned with actual commands and current file layout.
- Prefer explicit, copy-pasteable `uv` commands.
- Document external prerequisites (`Go`, `tle`) clearly.
