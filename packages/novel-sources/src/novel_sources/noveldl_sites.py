"""Site plugins novel-downloader lacks, registered into its own plugin registry on import.

biquges123 (新笔趣阁; the MtlTings Longevity raws came from it): the novel page lists
every chapter in `div.list`, and a chapter page has its title in `<h1>` and its text
in `<article>`, the layout novel-downloader's shared Biquge1Parser already reads.
Chapter ids are positions (`/50537/1825` is 第1781章), so numbers come from titles.
"""

from typing import Any

from lxml import html
from novel_downloader.infra.book_url_resolver import BookURLInfo, register_extractor
from novel_downloader.plugins.base.fetcher import GenericFetcher
from novel_downloader.plugins.common.parser.biquge1 import Biquge1Parser
from novel_downloader.plugins.registry import registrar
from novel_downloader.schemas import BookInfoDict

BIQUGES123 = "biquges123"


@registrar.register_fetcher(BIQUGES123)
class Biquges123Fetcher(GenericFetcher):
    site_name = BIQUGES123
    BOOK_INFO_URL = "https://www.biquges123.com/{book_id}/"
    CHAPTER_URL = "https://www.biquges123.com/{book_id}/{chapter_id}"


@registrar.register_parser(BIQUGES123)
class Biquges123Parser(Biquge1Parser):
    site_name = BIQUGES123

    def parse_book_info(self, raw_pages: list[str], **kwargs: Any) -> BookInfoDict | None:
        if not raw_pages:
            return None
        tree = html.fromstring(raw_pages[0])
        facts = {}  # "作者：愤怒的乌贼" -> {"作者": "愤怒的乌贼"}
        for line in tree.xpath('//div[@class="info_ct"]/div'):
            key, _, value = line.text_content().partition("：")
            facts[key.strip()] = value.strip()
        chapters = [
            {"title": (a.get("title") or a.text_content()).strip(), "url": href, "chapterId": href.rstrip("/").rsplit("/", 1)[-1]}
            for a in tree.xpath('//div[@class="list"]//a[@href]')
            if (href := a.get("href").strip())
        ]  # fmt: skip
        if not chapters:
            return None
        return {
            "book_name": self._first_str(tree.xpath('//h1[@class="info_title"]/text()')),
            "author": facts.get("作者", ""),
            "cover_url": self._first_str(tree.xpath('//div[@class="info_lt"]/img/@src')),
            "update_time": facts.get("最后更新", ""),
            "serial_status": facts.get("状态", ""),
            "summary": self._join_strs(tree.xpath('//div[@class="des"]/text()')),
            "volumes": [{"volume_name": "正文", "chapters": chapters}],
            "extra": {},
        }


@register_extractor(["www.biquges123.com", "biquges123.com", "m.biquges123.com"])
def _biquges123_url(path: str, query: str) -> BookURLInfo | None:
    parts = [p for p in path.split("/") if p]
    if not parts or not parts[0].isdigit():
        return None
    return {"site_key": BIQUGES123, "book_id": parts[0], "chapter_id": parts[1] if len(parts) > 1 else None}
