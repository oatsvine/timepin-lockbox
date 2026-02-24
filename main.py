#!/usr/bin/env python3
"""
Minimal timelock CLI for Master Lock 5423D-style keypad subsets (order-agnostic).

- N-digit pin `[0-9]`
- Rotation: previous pem is copied to lockbox-YYYYMMDDTHHMMSSZ.tle.pem
- Decrypt prints JSON payload to stdout only

Usage:
  # Lock new code until local time
  ./bin/tlock_cli.py lock 3d

  # Decrypt (reads static pem by default) → stdout
  ./bin/tlock_cli.py unlock
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from math import gcd
from pathlib import Path
from typing import Any, Dict

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown
from secrets import randbelow

# ── Hard constants (no configurables) ─────────────────────────────────────────
LOCK_NAME = "lockbox"  # static logical name stored in payload
DRAND_ENDPOINT = "https://drand.cloudflare.com/"  # fixed endpoint
DRAND_CHAINHASH = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"

ROOT_DIR = Path(os.environ.get("SHARED_STATE_DIR", "HOME"))
SECRETS_DIR = ROOT_DIR / "secrets"
LOCKED_DIR = SECRETS_DIR / "locked"
BACKUPS_DIR = SECRETS_DIR / "backups"

for d in (LOCKED_DIR, BACKUPS_DIR):
    os.makedirs(d, exist_ok=True)


# --- Keypad grid (phone-like) ---
KEYPAD = [
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    [" ", "0", " "],  # 0 at row 4, col 2
]
POS = {
    d: (r + 1, c + 1)
    for r, row in enumerate(KEYPAD)
    for c, d in enumerate(row)
    if d.strip()
}

# --- Minimal, high-impact disallow rules (regenerate if any trip) ---
# Derived from DataGenetics' PIN analysis: avoid years (19xx/20xx),
# straight +/-1 sequences (e.g., 1234/4321), repeated pairs (1212),
# heavy repeats (000, 111), and straight keypad lines like 2580.
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
TRIPLE_RE = re.compile(r"(.)\1\1")  # any '000'/'111' run
PAIR_REPEAT_RE = re.compile(r"(\d\d)\1")  # 'ABAB' anywhere


def has_pm1_run(s: str) -> bool:
    """Any 4-long ascending or descending step-by-1 run."""
    ds = [int(x) for x in s]
    for i in range(len(ds) - 3):
        a, b, c, d = ds[i : i + 4]
        if (b - a == 1 and c - b == 1 and d - c == 1) or (
            b - a == -1 and c - b == -1 and d - c == -1
        ):
            return True
    return False


def _norm(dx: int, dy: int):
    if dx == 0 and dy == 0:
        return (0, 0)
    g = gcd(abs(dx), abs(dy))
    return (dx // g, dy // g)


def has_keypad_straight(s: str) -> bool:
    """Any 4-digit straight line on the keypad (row/col/diag)."""
    coords = [POS[ch] for ch in s]
    for i in range(len(coords) - 3):
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = coords[i : i + 4]
        v1 = _norm(x1 - x0, y1 - y0)
        v2 = _norm(x2 - x1, y2 - y1)
        v3 = _norm(x3 - x2, y3 - y2)
        if v1 != (0, 0) and v1 == v2 == v3:
            return True
    return False


def acceptable(pin: str) -> bool:
    if YEAR_RE.search(pin):  # avoid 19xx/20xx anywhere
        return False
    if TRIPLE_RE.search(pin):  # avoid any 'xxx'
        return False
    if PAIR_REPEAT_RE.search(pin):  # avoid 'abab'
        return False
    if has_pm1_run(pin):  # avoid 4-long +/-1 runs
        return False
    if has_keypad_straight(pin):  # avoid keypad straight lines
        return False
    return True


def random_pin(length: int) -> str:
    # Draw uniformly from 00000000..99999999; regenerate until acceptable.
    attempts = 0
    while True:
        logger.debug(f"Generating random pin (attempt {attempts})...")
        s = str(randbelow(10**length)).zfill(length)
        if acceptable(s):
            return s


def run_tle_encrypt(plaintext_bytes: bytes, duration: str, out_path: Path) -> None:
    with tempfile.NamedTemporaryFile(prefix="tlock_", delete=False) as tf:
        tf_path = tf.name
        tf.write(plaintext_bytes)
        tf.flush()
        os.fsync(tf.fileno())
    try:
        cmd = [
            "tle",
            "--encrypt",
            "-D",
            duration,
            "-n",
            DRAND_ENDPOINT,
            "-c",
            DRAND_CHAINHASH,
            "--armor",
            "-o",
            str(out_path),
            tf_path,
        ]
        logger.debug(f"Encrypting via drand mainnet → {out_path.name} (-D {duration})")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"tle encrypt failed ({res.returncode}): {res.stderr.strip()}")
            raise typer.Exit(res.returncode)
    finally:
        # overwrite temp then unlink
        try:
            with open(tf_path, "r+b") as f:
                size = f.seek(0, os.SEEK_END)
                f.seek(0)
                f.write(os.urandom(size))
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass
        try:
            os.unlink(tf_path)
        except Exception:
            pass


def run_tle_decrypt(pem_file: Path) -> Dict[str, Any]:
    logger.debug(f"Decrypting cipher → {pem_file}")
    res = subprocess.run(
        ["tle", "--decrypt", str(pem_file)], text=True, capture_output=True
    )
    if res.returncode > 0:
        msg = res.stderr.strip()
        # too early to decrypt: expected round 24002262 > 23135579 current round
        if m := re.match(r".*?(\d+)\s*>\s*(\d+)", msg):
            t = int(m.group(1))
            c = int(m.group(2))
            delta = timedelta(seconds=(t - c) * 3)
            logger.error(f"{delta} remaining until unlock (at round {t})")
        else:
            logger.error(f"Failed ({res.returncode}): {msg}")
        raise typer.Exit(res.returncode)
    return json.loads(res.stdout)


def backup_existing_static_pem(lock_name: str) -> None:
    pem_file = LOCKED_DIR / f"{lock_name}.tle.pem"
    meta_file = pem_file.with_suffix(".json")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for f in [meta_file, pem_file]:
        if not f.is_file():
            continue
        bf = Path(BACKUPS_DIR) / f"{f.stem}-{timestamp}{f.suffix}"
        shutil.copy2(f, bf)
        logger.debug(f"Backed up {bf}")


# ── Commands ─────────────────────────────────────────────────────────────────
console = Console()


# --- Display: Polybius-style, step-by-step decoding ---
def print_keypad() -> None:
    table = Table(
        title="Keypad Grid",
        show_header=True,
        header_style="bold",
    )
    table.add_column("R\\C", justify="center")
    for c in (1, 2, 3):
        table.add_column(f"[blue]{c}[/blue]", justify="center")
    for r, row in enumerate(KEYPAD, start=1):
        table.add_row(
            f"[green]{r}[/green]", *(cell if cell.strip() else " " for cell in row)
        )
    console.print(table)


def step_decode(pin: str) -> None:
    print_keypad()
    for i, d in enumerate(pin, start=1):
        r, c = POS[d]
        console.print(f"[{i}] ([green]{r}[/green], [blue]{c}[/blue])")
    console.print(
        "\nResolve the PIN on the grid, look up the "
        "[bold](Row, Column)[/bold] coordinate to find each digit. "
        "Program the PIN in you safe without writing it down.\n",
        style="italic",
    )
    console.print(
        "\nPress Enter to confirm successfully programmed PIN.", style="green"
    )
    input()


app = typer.Typer(
    add_completion=False,
    help="Timelock keypad subset via drand/tlock with pinned mainnet chain",
)


@app.command()
def setup() -> None:
    """
    Installs tle via Go and prepares local secrets directories.
    """
    logger.info("[setup] Checking Go toolchain...")
    if not shutil.which("go"):
        logger.error("Missing dependency: go")
        raise typer.Exit(127)

    logger.info("[setup] Installing tle (drand/tlock) via 'go install'...")
    go_install_pkg = "github.com/drand/tlock/cmd/tle@latest"
    res = subprocess.run(
        ["go", "install", go_install_pkg], text=True, capture_output=True
    )
    if res.returncode != 0:
        logger.error(
            f"[setup] go install failed ({res.returncode}): {res.stderr.strip()}"
        )
        raise typer.Exit(res.returncode)

    if shutil.which("tle"):
        logger.info("[setup] 'tle' is available in PATH.")
    else:
        gopath_result = subprocess.run(
            ["go", "env", "GOPATH"], text=True, capture_output=True
        )
        if gopath_result.returncode != 0:
            logger.error(f"Failed to read GOPATH: {gopath_result.stderr.strip()}")
            raise typer.Exit(gopath_result.returncode)
        go_bin = Path(gopath_result.stdout.strip()) / "bin"
        candidate = go_bin / "tle"
        if candidate.is_file():
            console.print(
                "Important: 'tle' installed but not in PATH.\n"
                "Add this to your shell profile:\n"
                f'  export PATH="{go_bin}:$PATH"\n\n'
            )
        else:
            logger.error(
                "[setup] Could not find 'tle' after install. Check your Go environment."
            )
            raise typer.Exit(1)

    logger.info("[setup] Creating folders...")
    for directory in (BACKUPS_DIR, LOCKED_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    console.print(
        f"Created secrets directories → {SECRETS_DIR}\n"
        f"  - Locked ciphers: {LOCKED_DIR.relative_to(SECRETS_DIR)}\n"
        f"  - Backups: {BACKUPS_DIR.relative_to(SECRETS_DIR)}\n"
    )


@app.command()
def lock(
    duration: str = typer.Argument(
        help='Number followed by one of these units: "ns", "us" (or "µs"), "ms", "s", "m", "h", "d", "M", "y"'
    ),
    lock_name: str = typer.Option(
        help="Logical lock name (used for filenames)",
        default=LOCK_NAME,
    ),
    length: int = typer.Option(help="Number of digits in the PIN code", default=8),
) -> None:
    """
    Locks a new random keypad subset code until the specified duration from now.
    """
    pin = random_pin(length)

    tmp_out = Path("/tmp") / f"{lock_name}.tle.pem"
    doc = {
        "schema": "tlock-keypad-subset/1",
        "name": lock_name,
        "pin": list(pin),
        "length": len(pin),
        "duration": duration,
        "drand": {"endpoint": DRAND_ENDPOINT, "chainhash": DRAND_CHAINHASH},
    }
    plaintext = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")
    run_tle_encrypt(plaintext, duration, tmp_out)
    logger.info(f"Encrypted new {len(pin)}-digit pin; cypher staged in {tmp_out}")

    step_decode(pin)
    logger.debug(f"Pin entry complete; rotating cipher → {lock_name}...")

    # Rotation: backup existing pem (if any), then write new static pem atomically
    backup_existing_static_pem(lock_name)
    pem_out = LOCKED_DIR / f"{lock_name}.tle.pem"
    shutil.move(tmp_out, pem_out)
    meta_out = pem_out.with_suffix(".json")
    doc = {
        "schema": "tlock-keypad-subset/1",
        "name": lock_name,
        "duration": duration,
        "drand": {"endpoint": DRAND_ENDPOINT, "chainhash": DRAND_CHAINHASH},
    }
    meta_out.write_text(json.dumps(doc, indent=2))
    logger.debug(f"Successfully saved cipher → {pem_out}")
    console.print(
        Markdown(
            f"*Cipher file:* `{pem_out.name}`\n```json\n{meta_out.read_text()}\n```\n"
        )
    )
    console.print(f"Always keep a backup → {LOCKED_DIR}", style="bold yellow")


@app.command()
def unlock(
    lock_name: str = typer.Option(
        help="Logical lock name (used for filenames)",
        default=LOCK_NAME,
    ),
) -> None:
    """
    Decrypts the usual static pem and writes plaintext JSON to stdout only.
    """
    pem_out = LOCKED_DIR / f"{lock_name}.tle.pem"
    if not os.path.isfile(pem_out):
        logger.error(f"Static pem not found: {pem_out}")
        raise typer.Exit(2)
    meta_file = pem_out.with_suffix(".json")
    if meta_file.is_file():
        console.print(
            Markdown(
                f"*Cipher file:* `{pem_out}`\n```json\n{meta_file.read_text()}\n```"
            )
        )
    secret = run_tle_decrypt(pem_out)
    console.print(
        Markdown(f"**Plaintext Payload**\n```json\n{json.dumps(secret, indent=2)}\n```")
    )
    console.print(f"PIN: [blue]{'-'.join(secret['pin'])}[/blue]")


if __name__ == "__main__":
    app()
