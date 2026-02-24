#!/usr/bin/env bash
set -Eeuo pipefail

# Compatibility wrapper; canonical setup lives in the Typer CLI.
uv run python main.py setup
