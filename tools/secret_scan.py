"""Find API-key-shaped strings in files.

Run as a script to scan every file tracked by git (CI does this):

    uv run python tools/secret_scan.py
"""

import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "google": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "openrouter": re.compile(r"sk-or-[0-9A-Za-z_\-]{20,}"),
    "anthropic": re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}"),
    "openai": re.compile(r"sk-(?:proj-)?[0-9A-Za-z]{32,}"),
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    kind: str

    def __str__(self) -> str:
        # Never include the matched text: findings end up in logs.
        return f"{self.path}:{self.line}: {self.kind} key"


class SecretsFound(Exception):
    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__("possible secrets found:\n" + "\n".join(map(str, findings)))


def scan_text(text: str, path: Path) -> list[Finding]:
    return [
        Finding(path, lineno, kind)
        for lineno, line in enumerate(text.splitlines(), start=1)
        for kind, pattern in PATTERNS.items()
        if pattern.search(line)
    ]


def scan_files(paths: Iterable[Path]) -> list[Finding]:
    """Scan text files; binary files (anything that is not UTF-8) are skipped."""
    findings: list[Finding] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(text, path))
    return findings


def tracked_files(repo: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, check=True, capture_output=True
    ).stdout.decode("utf-8")
    return [repo / name for name in out.split("\0") if name]


def main() -> int:
    repo = Path.cwd()
    findings = scan_files(p for p in tracked_files(repo) if p.is_file())
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
