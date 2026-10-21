"""The zh rules layers: common zh, then per site key, then per novel slug.

A pattern moves from a site to COMMON only after it has been seen on two sites.
Every cleaner carries real before → after lines (short ones) as examples; one
test runs them all through the composed layers, and every `keeps` line through
every site.
"""

from novel_sources.zh_rules import Example, Layer, Markers, ZhRules, compose, drop, rewrite

COMMON = Layer(
    # 还没 is left out: it is an ordinary word.
    markers=Markers(("有没", "是止", "最坏", "坏是", "然前", "退入")),
    # Real prose that looks like noise: pauses, a held breath, crying, scene breaks (import:mtl).
    keeps=("……", "“……”", "——", "5555", "××××××××", "......"),
)

SITES: dict[str, Layer] = {
    "ixdzs8": Layer(
        cleaners=(
            drop(
                "lone-noise", r"[>」。]|[0-9]",
                (Example(">", None), Example("」", None), Example("。", None), Example("7", None)),
            ),
            # A dash run stands for a pause. 「————” waits for the reference diff (gate G2): left alone.
            rewrite(
                "dash-run", r"(?<!「)(?:——){2,}", "……",
                (Example("————", "……"), Example("「————”", "「————”")),
            ),
        ),
    ),
    "biquges123": Layer(
        cleaners=(
            # Obfuscated www…com: look-alike w's, symbols, then C O / ℃ O / ￠O / C〇; often glued to prose.
            rewrite(
                "watermark", r"[wWｗωшщ]{3}[\s▪•¤·.．]*[CcＣ℃￠]\s*[OoＯ〇0о]", "",
                (
                    Example("щщщ ••C O", None),
                    Example("www▪▪℃ O", None),
                    Example("wωw▪▪C〇赵二宝闻言大喜", "赵二宝闻言大喜"),
                    Example("为我做事？”шшш¤¤￠O", "为我做事？”"),
                ),
            ),
        ),
    ),
    "biquge5": Layer(decoy_site=True),
    "biquge345": Layer(decoy_site=True),
}  # fmt: skip

NOVELS: dict[str, Layer] = {
    "in-the-name-of-divine-powers": Layer(names=("陆昭", "叶槿", "李道生")),
}


def rules(slug: str, site: str, notes: str = "") -> ZhRules:
    """The rules for a raw-zh source with this site key, of the novel with this slug."""
    return compose((COMMON, SITES.get(site), NOVELS.get(slug)), slug, site, notes)
