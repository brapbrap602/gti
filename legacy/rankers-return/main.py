import bs4
import requests

FILE_TITLE = "rankers_return.txt"
URL = "https://lightnovelreader.org/rankers-return-284470/chapter-{chapter}"


def get_content():
    for chapter in range(44, 642):
        print("On chapter: ", chapter)
        r = requests.get(URL.format(chapter=chapter))
        wrap_in_bs4(r.text)


def wrap_in_bs4(content):
    soup = bs4.BeautifulSoup(content, "html.parser")
    for item in soup.find_all("p"):
        if item.text:
            write_content(item.text)


def write_content(cleaned_content):
    if cleaned_content:
        with open(FILE_TITLE, "a", encoding="utf-8") as f:
            cleaned_content = cleaned_content.replace(r" ", " ")
            cleaned_content = cleaned_content.replace(r"Sponsored Content", "")
            f.write(f"\n{cleaned_content}")


get_content()
