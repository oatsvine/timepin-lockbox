#!/usr/bin/env bash
set -Eeuo pipefail

# setup.sh — install drand/tlock 'tle' CLI and prep folders.
# NOTE: This script intentionally does NOT touch your Python environment.

ROOT_DIR="${SHARED_STATE_DIR:-/tmp}"
SECRETS_DIR="${ROOT_DIR}/secrets"
LOCKED_DIR="${SECRETS_DIR}/locked"
BACKUPS_DIR="${SECRETS_DIR}/backups"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing dependency: $1" >&2
        exit 127
    }
}

echo "[setup] Checking Go toolchain..."
need go

echo "[setup] Installing tle (drand/tlock) via 'go install'..."
GO_INSTALL_PKG="github.com/drand/tlock/cmd/tle@latest"
go install "${GO_INSTALL_PKG}"

# Ensure $GOPATH/bin or Go bin dir is in PATH for current shell session
if ! command -v tle >/dev/null 2>&1; then
    GO_BIN="$(go env GOPATH)/bin"
    if [[ -x "${GO_BIN}/tle" ]]; then
        echo "[setup] 'tle' installed at ${GO_BIN}/tle but not in PATH."
        echo "[setup] Add this to your shell profile:"
        echo "  export PATH=\"${GO_BIN}:\$PATH\""
    else
        echo "[setup] Could not find 'tle' after install. Check your Go environment." >&2
        exit 1
    fi
else
    echo "[setup] 'tle' is available in PATH."
fi

echo "[setup] Creating folders..."
mkdir -p "${BACKUPS_DIR}" "${LOCKED_DIR}"

echo "[setup] Done."
