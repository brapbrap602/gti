"""Freeze old scraper scripts into legacy/<slug>/ for reference.

Copies the top-level .py files of each source folder. Every file is scanned for
API keys first; if any is found nothing is copied.

    uv run python tools/copy_legacy.py legacy ../mounthua "../Cultivation Chat Group"
"""

import re
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

from secret_scan import SecretsFound, scan_files


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def copy_legacy(sources: Iterable[Path], dest_root: Path) -> list[Path]:
    """Return the created destination folders.

    Raises SecretsFound (naming each file) or FileExistsError before writing anything.
    """
    plan: dict[Path, list[Path]] = {}
    for source in sources:
        dest = dest_root / slug(source.name)
        if dest in plan:
            raise ValueError(f"{source} and another source both map to {dest}")
        if dest.exists():
            raise FileExistsError(f"{dest} already exists")
        plan[dest] = sorted(source.glob("*.py"))

    findings = scan_files(f for files in plan.values() for f in files)
    if findings:
        raise SecretsFound(findings)

    for dest, files in plan.items():
        dest.mkdir(parents=True)
        for f in files:
            shutil.copy2(f, dest / f.name)
    return list(plan)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        created = copy_legacy([Path(a) for a in argv[1:]], Path(argv[0]))
    except (SecretsFound, FileExistsError, ValueError) as e:
        print(f"aborted, nothing copied: {e}", file=sys.stderr)
        return 1
    for dest in created:
        print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
