# timepin-lockbox

Most people start looking for a time-lock when willpower is already running low: late-night spending, doom-scrolling, impulse habits, or anything that benefits from a hard pause.

Marketplace options prove the idea, but they are often single-purpose plastic containers sold at specialty prices.

`timepin-lockbox` takes a simpler path: keep the keypad lockbox, padlock setup, or small safe you already trust, and add a cryptographic time delay on top.

That turns ordinary lock hardware into a practical commitment tool. You choose the delay window, generate a fresh code, lock it in, and remove the "just this once" decision loop until time has actually passed.

It is designed to lock the operator out of immediate access. If the operator can quickly memorize the new PIN, the lockout fails. The UX is intentionally built to reduce that memorization path.

Under the hood, it is a time-delayed PIN lock/unlock CLI backed by `drand` and the `tle` tool from `github.com/drand/tlock`.

## drand in plain English

Think of `drand` as a public countdown clock that releases a new random key on a fixed schedule.

Cloudflare documents and serves this as the Randomness Beacon: a distributed network publishes fresh randomness in numbered rounds, and each round is publicly verifiable. In practice, that means no single machine gets to "decide" the result, and anyone can verify the beacon output once the round arrives.

For this project, `tle` encrypts your PIN so it can only be unlocked when the target round is reached. Before that round, the key material is not available yet. After that round, decryption is deterministic and auditable.

## Polybius-style anti-memorization UX

When a new PIN is generated, the CLI guides you through a keypad grid and reveals each digit as a `(row, column)` lookup step.

This introduces friction at exactly the point where the operator could otherwise imprint and retain the code. You still program the lock intentionally, but the flow is optimized for enforced lockout, not easy recall.

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
uv run python main.py setup
```

If `tle` is not on `PATH` after setup, add Go's bin directory as prompted by the command output.

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

## Notes

- `SHARED_STATE_DIR` controls where lock artifacts are stored. If unset, code currently defaults to `HOME`.
- Lock/unlock behavior depends on the external `tle` binary and drand connectivity.
