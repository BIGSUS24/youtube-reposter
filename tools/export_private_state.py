"""Create a local-only, portable account bundle for a Termux phone.

Never commit the output directory.  Transfer it directly (USB/Drive) to the
phone, then use termux/import-private-state.sh to import it.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    ROOT / "config.yaml",
    ROOT / "credentials" / "client_secret.json",
    ROOT / "credentials" / "token.json",
    ROOT / "shorts.db",
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tools/export_private_state.py <output-directory>")

    output = Path(sys.argv[1]).expanduser().resolve()
    missing = [str(path) for path in REQUIRED if not path.is_file()]
    if missing:
        raise SystemExit("Missing required file(s):\n" + "\n".join(missing))
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty directory: {output}")

    (output / "credentials").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "config.yaml", output / "config.yaml")
    shutil.copy2(
        ROOT / "credentials" / "client_secret.json",
        output / "credentials" / "client_secret.json",
    )
    shutil.copy2(ROOT / "credentials" / "token.json", output / "credentials" / "token.json")
    if (ROOT / "state.json").is_file():
        shutil.copy2(ROOT / "state.json", output / "state.json")

    # SQLite's online backup API produces a consistent DB even while the bot
    # is running and its WAL file is changing.
    with sqlite3.connect(ROOT / "shorts.db") as source, sqlite3.connect(output / "shorts.db") as target:
        source.backup(target)

    print(f"Private bundle created at: {output}")
    print("Transfer this folder locally to the phone; do not upload or commit it.")


if __name__ == "__main__":
    main()
