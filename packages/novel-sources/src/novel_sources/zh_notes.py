"""Translator notes: what a translator should know about one raw source's text.

They are added to the translation system instructions for chapters from that
source, site notes first, then the novel's. Not part of the rules revision:
translation keys on the notes themselves.
"""

SITES: dict[str, str] = {
    "ixdzs8": (
        "A 」 right after the name of an item or technique is a formatting artifact, not the end of a quotation."
    ),
}

NOVELS: dict[str, str] = {}


def notes(slug: str, site: str) -> str:
    """The notes for a raw-zh source with this site key, of the novel with this slug; "" for none."""
    return "\n".join(n for n in (SITES.get(site, ""), NOVELS.get(slug, "")) if n)
