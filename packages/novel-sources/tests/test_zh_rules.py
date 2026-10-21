import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import novel_sources
import pytest
from novel_core import Finding, Kind, Paragraph, RawChapter, Separator, SourceSpec, Version
from novel_sources.backends import is_reference, site_key, zh_rules
from novel_sources.clean import CleanRules
from novel_sources.zh_rules import Cleaner, Example, Hit
from novel_sources.zh_tables import COMMON, NOVELS, SITES, rules

NO_SITE = "import:mtl"  # a site key with no layer of its own
LIBRARY_KEEPS = ("……", "“……”", "——", "5555", "××××")


def cleaned(line: str, site: str = NO_SITE, slug: str = "novel") -> tuple:
    """The blocks one kept-raw line becomes through the composed rules for slug and site."""
    return rules(slug, site).version(RawChapter(line, "text"), "", CleanRules(content=()), {}).blocks


def _examples():
    layers = [("common", NO_SITE, "novel", COMMON)]
    layers += [(site, site, "novel", layer) for site, layer in SITES.items()]
    layers += [(slug, NO_SITE, slug, layer) for slug, layer in NOVELS.items()]
    for name, site, slug, layer in layers:
        for cleaner in layer.cleaners:
            for n, ex in enumerate(cleaner.examples, 1):
                yield pytest.param(site, slug, ex, id=f"example-{name}-{cleaner.name}-{n}")


@pytest.mark.parametrize(("site", "slug", "example"), list(_examples()))
def test_every_example_holds_through_the_composed_layers(site, slug, example):
    expected = () if example.after is None else (Paragraph.of(example.after),)
    assert cleaned(example.before, site, slug) == expected


def _keeps():
    layers = [("common", COMMON), *SITES.items(), *NOVELS.items()]
    lines = {line: name for name, layer in reversed(layers) for line in layer.keeps}
    lines |= {line: "library" for line in LIBRARY_KEEPS if line not in lines}
    for n, (line, name) in enumerate(lines.items(), 1):
        for site in (NO_SITE, *SITES):
            yield pytest.param(line, site, id=f"keep-{name}-{n}-{site}")


@pytest.mark.parametrize(("line", "site"), list(_keeps()))
def test_kept_lines_come_through_every_site_unchanged(line, site):
    assert cleaned(line, site) == (Paragraph.of(line),)


@pytest.mark.parametrize(
    "examples",
    [pytest.param((), id="cleaner-needs-example-none"), pytest.param((Example("a", "a"),), id="cleaner-needs-example")],
)
def test_a_cleaner_without_a_changing_example_cannot_be_defined(examples):
    with pytest.raises(ValueError, match="example"):
        Cleaner("noop", lambda line: line, examples)


def test_dash_run_is_rewritten_not_a_separator():
    blocks = cleaned("————", "ixdzs8")
    assert blocks == (Paragraph.of("……"),) and not any(isinstance(b, Separator) for b in blocks)


@pytest.mark.parametrize(
    ("line", "prose"),
    [
        pytest.param("wωw▪▪C〇赵二宝闻言大喜", "赵二宝闻言大喜", id="watermark-glued-before"),
        pytest.param("为我做事？”шшш¤¤￠O", "为我做事？”", id="watermark-glued-after"),
    ],
)
def test_glued_watermark_is_cut_and_the_prose_kept(line, prose):
    assert cleaned(line, "biquges123") == (Paragraph.of(prose),)


# -- checks: synthetic chapters, filler CJK with markers or names placed at chosen spots --------

FILLER = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁律吕调阳云腾致雨露结为霜金生丽水玉出昆冈"


def filler(n: int) -> str:
    return (FILLER * (n // len(FILLER) + 1))[:n]


def findings(*paragraphs: str, slug: str = "novel", site: str = NO_SITE) -> tuple[Finding, ...]:
    """The findings on a chapter made of these paragraphs, one per line."""
    raw = RawChapter("\n".join(paragraphs), "text")
    return rules(slug, site).version(raw, "第1章 名字", CleanRules(content=()), {}).findings


def sprinkled(total_cjk: int, hits: dict[str, int]) -> list[str]:
    """Paragraphs of filler holding each marker `hits[m]` times, total_cjk CJK chars in all."""
    words = [w for w, n in hits.items() for _ in range(n)]
    each, extra = divmod(total_cjk - sum(len(w) for w in words), len(words))
    return [filler(each + (i < extra)) + w for i, w in enumerate(words)]


@pytest.mark.parametrize(
    ("paragraphs", "detail"),
    [
        pytest.param(
            sprinkled(9000, {"有没": 7, "是止": 7, "最坏": 7, "然前": 6}),
            "有没×7 是止×7 最坏×7 然前×6 (3.0/1000)",
            id="poison-dense-long",
        ),
        pytest.param(
            sprinkled(1800, {"有没": 4, "是止": 4, "退入": 4}),
            "有没×4 是止×4 退入×4 (6.7/1000)",
            id="poison-dense-short",
        ),
        pytest.param(sprinkled(2000, {"还没": 20}), None, id="poison-common-word-only"),
        pytest.param(sprinkled(3200, {"有没": 8}), None, id="poison-few-distinct"),
        pytest.param(sprinkled(9000, {"有没": 2, "是止": 2, "退入": 2}), None, id="poison-sparse"),
    ],
)
def test_poison(paragraphs, detail):
    assert findings(*paragraphs) == (() if detail is None else (Finding("poison", detail),))


DIVINE = "in-the-name-of-divine-powers"
OPENING = ["陆昭" + filler(40), *[filler(40)] * 5]


@pytest.mark.parametrize(
    ("paragraphs", "flagged"),
    [
        pytest.param([*OPENING, *[filler(300)] * 3], True, id="decoy-names-vanish"),
        pytest.param([filler(40)] * 6 + [filler(300)] * 3, False, id="decoy-no-name-in-opening"),
        pytest.param([*OPENING, filler(400)], False, id="decoy-short-rest"),
        pytest.param([*OPENING, *[filler(300)] * 3, "叶槿"], False, id="decoy-name-in-rest"),
    ],
)
def test_decoy_names(paragraphs, flagged):
    found = findings(*paragraphs, slug=DIVINE)
    if flagged:
        assert found == (Finding("decoy-names", "陆昭×1 in the opening, no name in the 900 CJK chars after it"),)
    else:
        assert found == ()


def test_names_are_checked_only_for_their_novel():
    assert findings(*OPENING, *[filler(300)] * 3) == ()


def test_version_keeps_the_raw_and_stamps_the_rev():
    zh = rules("novel", "ixdzs8")
    raw = RawChapter("第1章 名字\n>\n他笑了。————\n", "text", "https://x.test/1")
    v = zh.version(raw, "第1章 名字", CleanRules(content=("div#nothing",)), {"backend": "novel-downloader"})
    assert v.blocks == (Paragraph.of("他笑了。……"),)  # title echo and noise gone; `base` ignored for text
    assert (v.raw, v.rules_rev, dict(v.provenance), v.findings) == (raw, zh.rev, {"backend": "novel-downloader"}, ())


def test_trace_lists_each_rule_that_changed_a_line():
    zh = rules("novel", "ixdzs8")
    assert zh.trace("  第1章 名字\n>\n他笑了。————\n7\n他哭了。") == (
        Hit("lone-noise", ">", None),
        Hit("dash-run", "他笑了。————", "他笑了。……"),
        Hit("lone-noise", "7", None),
    )
    assert rules("novel", NO_SITE).trace(">\n7") == ()


def test_html_raw_is_normalized_by_its_backend_rules_and_only_checked():
    zh = rules(DIVINE, "lncrawl")
    body = "".join(f"<p>{p}</p>" for p in [*OPENING, *[filler(300)] * 3, "——<b>——</b>"])
    v = zh.version(RawChapter(f'<div id="c">{body}</div>'), "第1章", CleanRules(content=("div#c",)), {})
    assert len(v.blocks) == 9  # no cleaners: the dash run is a separator, dropped at the end
    assert [f.check for f in v.findings] == ["decoy-names"]


def test_recheck_keeps_the_blocks_and_gives_new_findings():
    zh = rules(DIVINE, "lncrawl")
    blocks = tuple(Paragraph.of(p) for p in [*OPENING, *[filler(300)] * 3])
    v = zh.recheck(Version(7, 1, "/c/1", "第1章", blocks, "hash", {"backend": "lncrawl"}))
    assert (v.title, v.blocks, v.raw, v.rules_rev) == ("第1章", blocks, None, zh.rev)
    assert [f.check for f in v.findings] == ["decoy-names"]


# -- composition and source specs ------------------------------------------------------------


def test_layers_compose_common_then_site_then_novel():
    assert [c.name for c in rules(DIVINE, "ixdzs8").cleaners] == ["lone-noise", "dash-run"]
    assert rules(DIVINE, "ixdzs8").names == ("陆昭", "叶槿", "李道生")
    assert rules(DIVINE, "ixdzs8").markers == COMMON.markers
    assert rules(DIVINE, "biquge5").decoy_site and not rules(DIVINE, "ixdzs8").decoy_site
    assert len({rules("a", "ixdzs8").rev, rules("b", "ixdzs8").rev, rules("b", "biquge5").rev}) == 3


def test_zh_rules_for_specs():
    ixdzs8 = SourceSpec("novel-downloader", "https://ixdzs8.com/read/12345/", "zh", Kind.RAW_ZH)
    mtl = SourceSpec("import:mtl", "file:///C:/mtl/data/raw/x", "zh", Kind.RAW_ZH)
    english = SourceSpec("lncrawl", "https://novelbin.com/b/x", "en", Kind.OFFICIAL_EN)
    assert (site_key(ixdzs8), site_key(mtl)) == ("ixdzs8", "import:mtl")
    zh = zh_rules(DIVINE, ixdzs8)
    assert zh is not None and zh.rev == rules(DIVINE, "ixdzs8").rev and "」" in zh.notes
    assert zh_rules(DIVINE, english) is None
    assert zh_rules(DIVINE, mtl).notes == ""
    assert is_reference(SourceSpec("novel-downloader", "https://www.qidian.com/book/1035420986/", "zh", Kind.RAW_ZH))
    assert not is_reference(ixdzs8)


# -- rev: whole-file hash, read at import ------------------------------------------------------

RULE_FILES = ("zh_rules.py", "zh_tables.py", "clean.py")
PACKAGE = Path(novel_sources.__file__).parent


def copy_package(root: Path, crlf: bool = False) -> Path:
    """A copy of novel_sources under root, importable ahead of the installed one."""
    shutil.copytree(PACKAGE, root / "novel_sources", ignore=shutil.ignore_patterns("__pycache__", "lnreader_harness"))
    if crlf:
        for name in RULE_FILES:
            path = root / "novel_sources" / name
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return root / "novel_sources"


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


REV_SCRIPT = """
import sys
from pathlib import Path
import novel_sources
assert Path(novel_sources.__file__).parent.resolve() == Path(sys.argv[1]).resolve(), novel_sources.__file__
from novel_sources.zh_tables import rules
print(rules("novel", "ixdzs8").rev)
"""


def rev_in(root: Path | None) -> str:
    """The rev a fresh process computes from the copy under root, or from the installed package."""
    env = dict(os.environ)
    if root:
        env["PYTHONPATH"] = str(root)
    package = root / "novel_sources" if root else PACKAGE
    run = subprocess.run(
        [sys.executable, "-c", REV_SCRIPT, str(package)], capture_output=True, text=True, env=env, check=True
    )
    return run.stdout.strip()


def test_rev_stable_across_processes(tmp_path):
    here = rules("novel", "ixdzs8").rev
    copy_package(tmp_path, crlf=True)
    assert rev_in(None) == here
    assert rev_in(tmp_path) == here


def test_rev_covers_factory_args(tmp_path):
    edit(copy_package(tmp_path) / "zh_tables.py", "(?:——){2,}", "(?:——){3,}")
    assert rev_in(tmp_path) != rules("novel", "ixdzs8").rev


def test_rev_covers_clean(tmp_path):
    edit(copy_package(tmp_path) / "clean.py", "_ECHO_WINDOW = 3", "_ECHO_WINDOW = 4")
    assert rev_in(tmp_path) != rules("novel", "ixdzs8").rev


def test_rev_ignores_notes(tmp_path):
    edit(copy_package(tmp_path) / "zh_notes.py", "formatting artifact", "typesetting artifact")
    assert rev_in(tmp_path) == rules("novel", "ixdzs8").rev


REREAD_SCRIPT = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from novel_sources.zh_tables import rules
before = rules("novel", "ixdzs8").rev
tables = Path(sys.argv[1]) / "novel_sources" / "zh_tables.py"
tables.write_text(tables.read_text(encoding="utf-8").replace("(?:——){2,}", "(?:——){3,}"), encoding="utf-8")
print(before == rules("novel", "ixdzs8").rev)
"""


def test_rev_read_at_import(tmp_path):
    copy_package(tmp_path)
    run = subprocess.run(
        [sys.executable, "-c", REREAD_SCRIPT, str(tmp_path)], capture_output=True, text=True, check=True
    )
    assert run.stdout.strip() == "True"  # the edit on disk does not reach the running process
    assert rev_in(tmp_path) != rules("novel", "ixdzs8").rev  # a fresh process sees it


@pytest.mark.parametrize("module", ["zh_rules", "zh_tables"])
def test_rules_import_guard(module):
    """Rule logic lives only in the hashed files, so they import nothing else from novel_sources."""
    imported = set()
    for node in ast.walk(ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module == "novel_sources":
            imported |= {f"novel_sources.{a.name}" for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    hashed = {f"novel_sources.{Path(f).stem}" for f in RULE_FILES}
    assert {m for m in imported if m.split(".")[0] == "novel_sources"} <= hashed
