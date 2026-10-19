"""Chapter blocks as HTML, shared by the site and the EPUB builder."""

from markupsafe import Markup, escape
from novel_core import Block, Heading, Image, Note, Paragraph, Separator, System


def block_html(block: Block, remote_images: bool = True) -> Markup:
    """One block as HTML. Without `remote_images`, an image becomes its alt text (empty when it has none).

    EPUB readers don't fetch remote files, and the images sources link to are emoji and ads.
    """
    match block:
        case Paragraph(runs):
            inner = Markup("").join(_run_html(r.text, r.em, r.strong) for r in runs)
            return Markup("<p>{}</p>").format(inner)
        case Heading(text, level):
            tag = f"h{min(max(level, 3), 6)}"  # h1/h2 belong to the page and the chapter title
            return Markup(f"<{tag}>{{}}</{tag}>").format(text)
        case Separator():
            return Markup('<hr class="separator">')
        case Image(src, alt) if remote_images:
            return Markup('<img src="{}" alt="{}" loading="lazy">').format(src, alt)
        case Image(_, alt):
            return Markup("<p>{}</p>").format(alt) if alt.strip() else Markup("")
        case System(text):
            return Markup('<p class="system">{}</p>').format(text)
        case Note(text):
            return Markup('<aside class="note">{}</aside>').format(text)
    raise TypeError(f"unknown block {block!r}")


def _run_html(text: str, em: bool, strong: bool) -> Markup:
    html = escape(text)
    if em:
        html = Markup("<em>{}</em>").format(html)
    if strong:
        html = Markup("<strong>{}</strong>").format(html)
    return html
