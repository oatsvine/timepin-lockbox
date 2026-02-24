#!/usr/bin/env python3
"""
Minimal timelock CLI for Master Lock 5423D-style keypad subsets (order-agnostic).

- Alphabet hardcoded to 0123456789*#
- Subset size randomized uniformly
- Static output: secrets/locked/lockbox.tle.pem
- Rotation: previous pem is copied to secrets/locked/backups/lockbox-YYYYMMDDTHHMMSSZ.tle.pem
- Decrypt prints JSON payload to stdout only

Usage:
  # Lock new code until local time
  ./bin/tlock_cli.py lock 3d

  # Decrypt (reads static pem by default) → stdout
  ./bin/tlock_cli.py decrypt
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import typer
from loguru import logger

app = typer.Typer(
    add_completion=False,
    help="Timelock keypad subset via drand/tlock with pinned mainnet chain",
)

# ── Hard constants (no configurables) ─────────────────────────────────────────
ALPHABET: Tuple[str, ...] = tuple(
    "0123456789*#"
)  # 12 buttons, order-agnostic, no repeats
LOCK_NAME = "lockbox"  # static logical name stored in payload
DRAND_ENDPOINT = "https://drand.cloudflare.com/"  # fixed endpoint
DRAND_CHAINHASH = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"

ROOT_DIR = os.environ.get("SHARED_STATE_DIR", "/tmp")
SECRETS = os.path.join(ROOT_DIR, "secrets")
LOCKED = os.path.join(SECRETS, "locked")
BACKUPS = os.path.join(SECRETS, "backups")
STATIC_PEM = os.path.join(LOCKED, f"{LOCK_NAME}.tle.pem")

for d in (LOCKED, BACKUPS):
    os.makedirs(d, exist_ok=True)


# ── Helpers ──────────────────────────────────────────────────────────────────


def choose_k_random() -> int:
    return secrets.choice([5, 6, 7, 8])


def sample_subset(k: int) -> List[str]:
    items = list(ALPHABET)
    for i in range(len(items) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        items[i], items[j] = items[j], items[i]
    return items[:k]


def canonical_sort(code: Sequence[str]) -> List[str]:
    idx = {ch: i for i, ch in enumerate(ALPHABET)}
    return sorted(code, key=lambda c: idx[c])


def build_payload(code_sorted: Sequence[str], duration: str) -> bytes:
    doc = {
        "schema": "tlock-keypad-subset/1",
        "name": LOCK_NAME,
        "alphabet": "".join(ALPHABET),
        "code": list(code_sorted),
        "length": len(code_sorted),
        "duration": duration,
        "drand": {"endpoint": DRAND_ENDPOINT, "chainhash": DRAND_CHAINHASH},
    }
    return json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")


def run_tle_encrypt(plaintext_bytes: bytes, duration: str, out_path: str) -> None:
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
            out_path,
            tf_path,
        ]
        logger.info(f"Encrypting via drand mainnet → {out_path}")
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


def run_tle_decrypt(cipher_path: str) -> Dict[str, Any]:
    logger.info(f"Decrypting via tle → {cipher_path}")
    res = subprocess.run(
        ["tle", "--decrypt", cipher_path], text=True, capture_output=True
    )
    if res.returncode > 0:
        msg = res.stderr.strip()
        delta = "?"
        # too early to decrypt: expected round 24002262 > 23135579 current round
        if m := re.match(r".*?(\d+)\s*>\s*(\d+)", msg):
            target_secs = int(m.group(1))
            now_secs = int(m.group(2))
            logger.debug(f"target={target_secs} now={now_secs}")
            delta = timedelta(seconds=target_secs - now_secs)
        logger.error(f"Failed ({res.returncode}): {msg} (wait {delta})")
        raise typer.Exit(res.returncode)
    return json.loads(res.stdout)


def backup_existing_static_pem() -> None:
    pem_file = Path(STATIC_PEM)
    meta_file = pem_file.with_suffix(".json")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for f in [meta_file, pem_file]:
        if not f.is_file():
            continue
        bf = Path(BACKUPS) / f"{f.stem}-{timestamp}{f.suffix}"
        shutil.copy2(f, bf)
        logger.info(f"Backed up {bf}")


# ── Commands ─────────────────────────────────────────────────────────────────
@app.command()
def lock(
    duration: str = typer.Argument(
        help='Number followed by one of these units: "ns", "us" (or "µs"), "ms", "s", "m", "h", "d", "M", "y"'
    ),
) -> None:
    """
    Generate random *subset* (k∈{5-8}) from hardcoded alphabet, print set + one practice
    order to stdout, confirm, timelock to static pem (with backup of previous), wipe memory.
    """
    k = choose_k_random()
    code = sample_subset(k)
    code_final = code[:]
    random.shuffle(code_final)

    # Secret to stdout (operator-facing); no extra chatter
    print("\n================= KEYPAD CODE =================")
    print("  '" + "-".join(code_final) + f"'    (k={k})")
    print("=================================================\n")
    print(f"Unlocks in: {duration}\n")
    print(
        "Flip cams ON for exactly these buttons. Verify: CLEAR → press all (any order) → OPEN."
    )
    input(
        "When done and verified, press any key to proceed with encryption and storage."
    )

    doc = {
        "schema": "tlock-keypad-subset/1",
        "name": LOCK_NAME,
        "alphabet": "".join(ALPHABET),
        "duration": duration,
        "drand": {"endpoint": DRAND_ENDPOINT, "chainhash": DRAND_CHAINHASH},
    }
    meta_out = Path(STATIC_PEM).with_suffix(".json")
    meta_out.write_text(json.dumps(doc, indent=2))
    # Rotation: backup existing pem (if any), then write new static pem atomically
    backup_existing_static_pem()
    tmp_out = STATIC_PEM + ".tmp"
    plaintext = build_payload(code_final, duration)
    run_tle_encrypt(plaintext, duration, tmp_out)
    os.replace(tmp_out, STATIC_PEM)
    logger.info(f"Wrote static pem → {STATIC_PEM}")


@app.command()
def decrypt() -> None:
    """
    Decrypts the usual static pem and writes plaintext JSON to stdout only.
    """
    if not os.path.isfile(STATIC_PEM):
        logger.error(f"Static pem not found: {STATIC_PEM}")
        raise typer.Exit(2)
    secret = run_tle_decrypt(STATIC_PEM)
    print(json.dumps(secret, indent=2))
    print("\n================= KEYPAD CODE =================")
    print("  '" + "-".join(secret["code"]) + f"'    (k={secret['length']})")
    print("=================================================\n")


# ── Entrypoint ────────────────────────────────────────────────────────────────
def main():
    app()


if __name__ == "__main__":
    main()
