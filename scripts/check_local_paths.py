"""List tracked text files that carry absolute local paths (home directories, night-run scratch dirs).

Run before any `git push`: `python scripts/check_local_paths.py` exits 1 and prints file:line for every hit, so what
would be published is reviewed first (MERGE_PLAN.md). `--repo` checks another checkout.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# built from parts so this file does not match itself
PATTERN = re.compile(
    "|".join(
        [
            "/" + r"Users/[^/\s]+/",
            "/" + r"home/[^/\s]+/",
            "/" + "private/tmp/",
            "/" + r"tmp/j\d+\w*",
            "~" + "/night/",
        ]
    )
)


def hits(repo: Path) -> list[str]:
    files = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    out = []
    for name in filter(None, files.decode().split("\0")):
        path = repo / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        out += [
            f"{name}:{i}: {line.strip()[:160]}"
            for i, line in enumerate(text.splitlines(), 1)
            if PATTERN.search(line)
        ]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    found = hits(parser.parse_args().repo)
    print("\n".join(found) if found else "no absolute local paths in tracked files")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
