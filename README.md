# timelock

Time-delayed PIN lock/unlock CLI backed by `drand` and the `tle` tool from `github.com/drand/tlock`.

This project is managed with the `uv` toolchain.

## What it does

- Generates an acceptable random numeric PIN (default: 8 digits).
- Encrypts the PIN payload with `tle` for a specified duration.
- Rotates the active cipher to `secrets/locked/<name>.tle.pem`.
- Backs up previous lock artifacts in `secrets/backups/`.
- Decrypts and displays the PIN only after unlock time.

## Prerequisites

- Python 3.12+
- `uv`
- Go toolchain (for installing `tle`)

## Setup (uv + tle)

```bash
# from the project directory
uv sync
./setup.sh
```

If `tle` is not on `PATH` after setup, add Go's bin directory as prompted by `setup.sh`.

## Usage

```bash
# lock for 3 days (default lock name: lockbox)
uv run python main.py lock 3d

# unlock
uv run python main.py unlock

# custom lock name and pin length
uv run python main.py lock 12h --lock-name garage --length 6
uv run python main.py unlock --lock-name garage
```

## Development

```bash
# install runtime + dev dependencies
uv sync --group dev

# type check
uv run pyright
```

## Repository layout

- `main.py`: Typer CLI implementation.
- `setup.sh`: installs `tle` and prepares local directories.
- `secrets/`: runtime lock and backup artifacts.

## Notes

- `SHARED_STATE_DIR` controls where lock artifacts are stored. If unset, code currently defaults to `HOME`.
- Lock/unlock behavior depends on the external `tle` binary and drand connectivity.
