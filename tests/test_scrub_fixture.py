import json
import re

from bs4 import BeautifulSoup
from scrub_fixture import scrub_html

PAGE = """<!DOCTYPE html>
<html><head>
<title>Chapter 12: The Fall of Heaven</title>
<meta name="description" content="Lin Feng walks into the mountains.">
<meta property="og:url" content="https://novelbin.me/novel/x/chapter-12">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-1"></script>
<script>gtag('config', 'G-1');</script>
<script type="application/ld+json">{"@type": "Article", "headline": "The Fall", "position": 12}</script>
<style>.ad { display: none }</style>
</head><body>
<!-- chapter content -->
<div id="chr-content" class="chr-c">
<h3>Chapter 12 (2): The Fall</h3>
<p>Lin Feng's sword cut 3 heads, didn't it?</p>
<p><img src="a.png" alt="A red dragon" title="Dragon"></p>
<p>Read latest chapters at novelbin.me</p>
<p>第十二章 天下无敌</p>
</div></body></html>"""

PROSE_WORDS = {"Lin", "Feng", "sword", "heads", "Fall", "Heaven", "dragon", "Dragon", "walks", "mountains"}


def texts(soup):
    return [str(s) for s in soup.find_all(string=True)]


def test_text_keeps_length_digits_punctuation_and_case():
    out = BeautifulSoup(scrub_html(PAGE), "html.parser")
    before = BeautifulSoup(PAGE, "html.parser")
    for old, new in zip(texts(before), texts(out), strict=True):
        assert len(old) == len(new)
        assert re.sub(r"[^\W\d_]", "", old) == re.sub(r"[^\W\d_]", "", new)  # only letters change
        assert [c.isupper() for c in old] == [c.isupper() for c in new]


def test_tags_and_structural_attributes_are_unchanged():
    out = BeautifulSoup(scrub_html(PAGE), "html.parser")
    before = BeautifulSoup(PAGE, "html.parser")
    structural = lambda soup: [
        (t.name, {k: v for k, v in t.attrs.items() if k not in ("alt", "title", "content")})
        for t in soup.find_all(True)
    ]
    assert structural(out) == structural(before)
    assert out.find("meta", property="og:url")["content"] == "https://novelbin.me/novel/x/chapter-12"


def test_no_prose_word_survives_anywhere():
    out = scrub_html(PAGE)
    assert not PROSE_WORDS & set(re.findall(r"[^\W\d_]+", out))
    assert "天下无敌" not in out


def test_numbering_words_survive_for_key_derivation():
    out = BeautifulSoup(scrub_html(PAGE), "html.parser")
    assert out.title.string.startswith("Chapter 12: ")
    assert out.h3.string.startswith("Chapter 12 (2): ")
    assert out.find_all("p")[-1].string.startswith("第十二章 ")


def test_keep_patterns_survive_verbatim():
    out = scrub_html(PAGE, keep=[r"novelbin\.me"])
    assert re.search(r"<p>\w+ \w+ \w+ \w+ novelbin\.me</p>", out)
    assert "Read latest" not in out


def test_scripts_styles_and_comments_kept_but_json_strings_scrubbed():
    out = BeautifulSoup(scrub_html(PAGE), "html.parser")
    scripts = out.find_all("script")
    assert scripts[1].string == "gtag('config', 'G-1');"
    data = json.loads(scripts[2].string)
    assert data["position"] == 12 and data["@type"] == "Article"
    assert data["headline"] != "The Fall" and len(data["headline"]) == len("The Fall")
    assert out.style.string == ".ad { display: none }"
    assert "<!-- chapter content -->" in str(out)


def test_prose_attributes_scrubbed():
    out = BeautifulSoup(scrub_html(PAGE), "html.parser")
    assert out.img["alt"] != "A red dragon" and len(out.img["alt"]) == len("A red dragon")
    assert out.find("meta", attrs={"name": "description"})["content"] != "Lin Feng walks into the mountains."


def test_deterministic():
    assert scrub_html(PAGE) == scrub_html(PAGE)
