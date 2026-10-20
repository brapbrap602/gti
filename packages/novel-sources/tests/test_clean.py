import pytest
from novel_core import Heading, Image, Paragraph, RawChapter, Run, Separator
from novel_sources.clean import CleanError, CleanRules, normalize
from novel_sources.hosts import cut_glued_watermarks, is_watermark, rules_for, site_name

BODY = CleanRules(content=("div#body",))


def page(inner: str) -> RawChapter:
    return RawChapter(f"<html><body><nav>Menu</nav><div id='body'>{inner}</div></body></html>")


def texts(blocks) -> list[str]:
    return [b.text if isinstance(b, Paragraph | Heading) else type(b).__name__ for b in blocks]


# -- the shared walk -------------------------------------------------------------


def test_paragraphs_runs_and_breaks():
    blocks = normalize(page("<p>One <i>two</i> <b>three</b></p>bare text<br>After break<p>  </p>"), BODY)
    assert blocks[0] == Paragraph((Run("One "), Run("two", em=True), Run(" "), Run("three", strong=True)))
    assert texts(blocks) == ["One two three", "bare text", "After break"]


def test_br_wrapping_a_sentence_mid_line_joins_the_lines():
    html = "<p>wiped his forehead with his<br>\r\nsleeve.<br>“Phew.”</p><p>the <i>Hall,<br>including</i> elders</p>"
    blocks = normalize(page(html), BODY)
    assert texts(blocks) == ["wiped his forehead with his sleeve.", "“Phew.”", "the Hall, including elders"]


def test_separators_images_and_headings():
    html = "<p>a</p><hr><p>***</p><p>b</p><p>❄️❄️❄️</p><h3>Interlude</h3><img src='x.png' alt='map'><p>~~~</p>"
    blocks = normalize(page(html), BODY)
    assert texts(blocks) == ["a", "Separator", "b", "Separator", "Interlude", "Image"]
    assert blocks[5] == Image("x.png", "map")
    assert blocks[4] == Heading("Interlude", 3)


def test_dialog_ellipses_are_not_separators():
    assert texts(normalize(page("<p>......</p><p>“...”</p>"), BODY)) == ["......", "“...”"]


def test_scripts_styles_and_ad_slots_are_removed():
    html = "<p>a</p><div><script>var ad = 1;</script></div><style>.x{}</style><ins>ad</ins><p>b</p>"
    assert texts(normalize(page(html), BODY)) == ["a", "b"]


@pytest.mark.parametrize(
    ("title", "first"),
    [
        ("Chapter 12: The Fall", "<h4>Chapter 12: The Fall</h4>"),
        ("Chapter 12: The Fall", "<p>Chapter 12 - The Fall</p>"),
        ("Chapter 55 The Forest (2)", "<p>The Forest (2)</p>"),
        ("Chapter 1584 - Senior White in the nightmare", "<h3>1584 Senior White in the nightmare</h3>"),
        ("Who Let Him Cultivate?! (WX)-Chapter 301: X", "Chapter 301: X"),
    ],
    ids=["heading", "paragraph", "name-only", "number-name", "bare-text"],
)
def test_title_echo_at_the_top_is_dropped(title, first):
    assert texts(normalize(page(f"{first}<p>Story starts.</p>"), BODY, title)) == ["Story starts."]


def test_chapter_mention_later_in_the_body_is_kept():
    html = "<p>a</p><p>b</p><p>c</p><p>Chapter 3 was better.</p>"
    assert texts(normalize(page(html), BODY, "Chapter 4")) == ["a", "b", "c", "Chapter 3 was better."]


def test_text_content():
    raw = RawChapter("Chapter 4\n\nFirst line.\r\n***\nSecond line.\n", "text")
    assert texts(normalize(raw, BODY, "Chapter 4")) == ["First line.", "Separator", "Second line."]


def test_missing_body_is_an_error():
    with pytest.raises(CleanError, match="div#body"):
        normalize(RawChapter("<html><p>no body</p></html>"), BODY)


# -- watermarks and junk lines (real variants from the stored pages) ------------------


@pytest.mark.parametrize(
    "line",
    [
        "This content is taken from freeweɓnovel.cѳm.",
        "This content is taken from freewebnove(l).com",
        "The source of this content is free(w)ebnovel",
        "This chapter is updated by fre(e)webnov(l).com",
        "Read latest chapters at fre(e)novelkiss.com Only",
        "reewebnovel.com",
        "Visit fгeewebɳoveɭ.cøm for the best novel reading experience.",
        "The most uptodate novels are published on frёewebnoѵel.ƈo𝐦.",
        "Original content can be found at novel{f}ire.net",
        "The rightful source is novel~fire~net",
        "Among them was even the This text is hosted at novel_fіre.net",
        "New novel chapters are published on novelbuddy.cσ𝞬.",
    ],
)
def test_watermark_lines(line):
    assert is_watermark(line)


@pytest.mark.parametrize(
    "line",
    [
        "On Earth, this would’ve been equivalent to self-publishing a novel at his own expense.",
        "He read a novel by the window.",
        "The spider web glowed.",
        "Free web services are not novel.",
        "It was a novel fire technique.",
        "The novel bin was full.",
        "Before transmigrating, Li Fan had read numerous online novels.",
        "“Why does the web of fate entangle us?”",
    ],
)
def test_prose_is_not_a_watermark(line):
    assert not is_watermark(line)


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("“Oh.”freewebnovel.com", "“Oh.”"),
        ("The temple shone at night.freewebnovel.com", "The temple shone at night."),
        ("Li Fan quietly retreated. Thɪs chapter is updatᴇd by novel(ꜰ)ire.net", "Li Fan quietly retreated."),
        ("Li Fan nodded slightly. ᴛʜɪs ᴄʜᴀᴘᴛᴇʀ ɪs ᴜᴘᴅᴀᴛᴇ ʙʏ novel⚑fire.net", "Li Fan nodded slightly."),
        ("No site here. Just a novel.", "No site here. Just a novel."),
    ],
)
def test_glued_watermark_sentence_is_cut(text, kept):
    assert cut_glued_watermarks(text) == kept


def test_common_rules_drop_credits_navigation_and_watermarks():
    long = "Long paragraph " * 20
    html = (
        "<p>Translator: GodBrandy Editor: Kurisu</p><p>Previous Chapter Project Page Support Us on Ko-fi</p>"
        f"<p>Read latest chapters at freewebnovel.com Only.</p><p>“`</p><p>{long}freewebnovel.com</p>"
        "<p>A new text-to-speech function has been added. You can try clicking on the settings!</p>"
        "<p>Please visit  to enjoy reading</p>"
    )
    rules = rules_for("https://novelbin.me/b/x/chapter-1")
    raw = RawChapter(f"<div id='chr-content'>{html}</div>")
    assert texts(normalize(raw, rules)) == [long.strip()]


def test_common_rules_drop_ads_patreon_lines_and_end_marks():
    # As found in stored novelbin pages: a pubfuture banner in a <p>, and pubadx tracking pixels.
    html = (
        '<p>a</p><p><a href="https://pubfuture.com/"><img alt="Ads by Pubfuture" src="https://s3.pubfuture.com/favicon.ico"/></a>'
        '<a href="https://x.epicplay.in/"><img src="https://media.pubfuture.com/2024/10/17/300x250.gif"/></a></p>'
        '<div class="bg-ssp-6327"><div style="display:none"><img src="https://imp9.pubadx.one/rec?f=1"/></div></div>'
        '<p><img src="https://s.w.org/images/core/emoji/11.2.0/svg/2744.svg" alt="❄️"/></p>'
        "<p>Read extra chapters on >>> patreon.com/SpiritStonetranslation</p><p>b</p>"
        "<p>(End of this chapter)</p><p>Spirit.Stone.translation</p><p>The end of this chapter was near.</p>"
    )
    blocks = normalize(RawChapter(f"<div id='chr-content'>{html}</div>"), rules_for("https://novelbin.me/b/x/chapter-1"))
    assert texts(blocks) == ["a", "Image", "b", "The end of this chapter was near."]
    assert blocks[1] == Image("https://s.w.org/images/core/emoji/11.2.0/svg/2744.svg", "❄️")


# -- per-host rules on scrubbed real pages ----------------------------------------------


def test_site_name_ignores_tld_and_www():
    assert site_name("https://www.novelbin.me/x") == site_name("https://novelbin.com/y") == "novelbin"


def test_unknown_host_has_no_rules():
    with pytest.raises(CleanError, match="example.org"):
        rules_for("https://example.org/novel/1")


# Expected counts were checked against each page: its non-empty <p> count equals the
# paragraphs plus separators below plus the lines dropped (freewebnovel: the title echo;
# novelbin: title echo and translator credit; novelbuddy-me: a watermark and a navigation
# line; novelbuddy-com: a watermark).
@pytest.mark.parametrize(
    ("fixture", "url", "title", "paragraphs", "separators"),
    [
        ("freewebnovel", "https://freewebnovel.com/novel/beyond-the-timescape/chapter-176",
         "Chapter 176: Golden Crow Assimilates Myriad Spirits", 41, 2),
        ("novelbin", "https://novelbin.me/novel-book/cultivation-chat-group/chapter-290",
         "Chapter 290: The shrinking big lizard", 57, 4),
        ("novelbuddy-me", "https://novelbuddy.me/surviving-the-game-as-a-barbarian/chapter-28",
         "Chapter 28", 208, 0),
        ("novelbuddy-com", "https://novelbuddy.com/novel/who-let-him-cultivate-wx/chapter-135-apothecary",
         "Who Let Him Cultivate?! (WX)-Chapter 135: Apothecary", 56, 2),
        ("skydemonorder", "https://skydemonorder.com/projects/3801994495-return-of-the-mount-hua-sect/235-what-is",
         "What Is With That One? (5)", 171, 0),
    ],
    ids=["norm-host-freewebnovel", "norm-host-novelbin", "norm-host-novelbuddy-me", "norm-host-novelbuddy-com",
         "norm-host-skydemon"],
)  # fmt: skip
def test_host_page(host_fixtures, fixture, url, title, paragraphs, separators):
    html = (host_fixtures / f"{fixture}.html").read_text(encoding="utf-8")
    blocks = normalize(RawChapter(html, final_url=url), rules_for(url), title)
    assert sum(isinstance(b, Paragraph) for b in blocks) == paragraphs
    assert sum(isinstance(b, Separator) for b in blocks) == separators
    for b in blocks:
        text = b.text if isinstance(b, Paragraph) else ""
        assert not is_watermark(text) and cut_glued_watermarks(text) == text
        assert "Ko-fi" not in text and not text.startswith("Translator:")
        assert "gtag" not in text and "pubfuturetag" not in text
