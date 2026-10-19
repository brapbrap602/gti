import json
import os.path
import re
from dataclasses import dataclass

import bs4
import requests

FILE_TITLE = "martial_world-2035-end.txt"
URL = "https://mnovelfree.com/martial-world-241220/chapter-{chapter}"

@dataclass
class ANovel:
    novel_name: str
    _: dict

    def __post_init__(self):
        _ = self._        self.chapter_begin = int(_["chapter_begin"])
        self.chapter_end = int(_["chapter_end"])
        self.link = _["link"]
        self.chapter_regex = _["chapter_regex"]
        self.content_tag = _["content_tag"]
        self.chapter_name_location = _["chapter_name_location"]
        self.file_name = f"{self.novel_name}_{self.chapter_begin}-{self.chapter_end + 1}.txt"
        del self._

    @property
    def urls(self):
        for chapter in range(self.chapter_begin, self.chapter_end + 1):
            yield re.sub(pattern=self.chapter_regex, repl=str(chapter), string=self.link)


@dataclass
class Writer:

    @staticmethod
    def _url_contents(novel):
        for url in novel.urls:
            r = requests.get(url)
            soup = bs4.BeautifulSoup(r.text, "html.parser")
            yield soup

    # @staticmethod
    def chapter_content(self, novel):
        for soup in self._url_contents(novel):
            for item in soup.find_all(novel.content_tag):
                yield item.text

    def get_chapter_name_location(self):
        "chapter_name_location"
        ...

    def write_to_disk(self, novel: ANovel):

        for content in self.chapter_content(novel):
            with open(novel.file_name, 'a') as f:
                f.write(f"\n{content}")


@dataclass
class JsonStuff:
    def __post_init__(self):
        self.path = os.path.join(r'.', "configs.json")
        self.content = json.loads(open(self.path).read())

    def download_novels(self):
        for novel_name, novel_items in self.content.items():
            Writer.write_to_disk(ANovel(novel_name, novel_items))

        return None


JsonStuff().download_novels()

# def get_content():
#     for chapter in range(2035, 2280):
#         r = requests.get(URL.format(chapter=chapter))
#         wrap_in_bs4(r.text)
#
#
# def wrap_in_bs4(content):
#     soup = bs4.BeautifulSoup(content, "html.parser")
#     for item in soup.find_all("p"):
#         if "chapter" in item.text.lower():
#             _ch = f"\n* {item.text} *\n"
#             matches = bool(re.match(r"\n\*\s+Chapter\s+.*\*", string=_ch))
#             print(f"On {item.text}. {' ' * 20}{matches=}")
#             write_content(_ch)
#         elif item.text:
#             write_content(item.text)
#
#
# def write_content(cleaned_content):
#     if cleaned_content:
#         with open(FILE_TITLE, 'a') as f:
#             f.write(f"\n{cleaned_content}")
#
#
# get_content()

