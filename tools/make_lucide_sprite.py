"""Build nov serve's icon sprite from a lucide-static release.

Each icon becomes a `<symbol id="NAME">` holding the source SVG's shapes; the app draws
one with `<svg class="icon"><use href="/static/vendor/lucide.svg#NAME"/></svg>`, and the
`.icon` class supplies the stroke settings the source SVGs set on their root.

    uv run python tools/make_lucide_sprite.py path/to/lucide-static/package/icons

lucide-static is ISC licensed; its LICENSE ships next to the sprite.
"""

import re
import sys
from pathlib import Path

ICONS = (
    "activity", "arrow-down", "arrow-up", "book-open", "check", "chevron-down", "chevron-right",
    "circle-alert", "circle-check", "clock", "external-link", "file-text", "git-compare", "globe",
    "hammer", "languages", "layers", "library", "list", "loader", "panel-left", "pin", "pin-off",
    "plus", "refresh-cw", "rotate-ccw", "search", "square", "triangle-alert", "x",
)  # fmt: skip
OUT = Path(__file__).resolve().parent.parent / "packages/novel-app/src/novel_app/web/static/vendor/lucide.svg"


def symbol(name: str, svg: str) -> str:
    """The shapes inside one icon's <svg>, as a symbol with its viewBox."""
    body = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S)
    if body is None:
        raise ValueError(f"{name}: no <svg> element")
    shapes = " ".join(line.strip() for line in body.group(1).strip().splitlines())
    return f'<symbol id="{name}" viewBox="0 0 24 24">{shapes}</symbol>'


def sprite(icons: Path) -> str:
    symbols = "\n".join(symbol(name, (icons / f"{name}.svg").read_text(encoding="utf-8")) for name in ICONS)
    return f'<svg xmlns="http://www.w3.org/2000/svg">\n{symbols}\n</svg>\n'


if __name__ == "__main__":
    OUT.write_text(sprite(Path(sys.argv[1])), encoding="utf-8", newline="\n")
    print(f"{len(ICONS)} icons -> {OUT}")
