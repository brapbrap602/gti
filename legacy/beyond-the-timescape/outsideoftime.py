import bs4
import requests

FILE_TITLE = "outside_of_time.html"
URL = "https://freewebnovel.com/outside-of-time/chapter-{chapter}.html"


def get_content():
    for chapter in range(1180, 1202):
        print("On chapter: ", chapter)
        r = requests.get(URL.format(chapter=chapter))
        wrap_in_bs4(r.content)


def wrap_in_bs4(content):
    soup = bs4.BeautifulSoup(content, "html.parser")
    ch_content = soup.find(id="article")
    ch_title = soup.find(class_="chapter").text
    try:
        ch_title = ch_title.split('-')[1].strip()
    except Exception as e:
        print(f"excepted {e}")
        ch_title = ch_title.strip()
    ch_content = f"<h1>{ch_title}</h1>" + str(ch_content).replace(ch_title, '')
    write_content(ch_content)


def write_content(cleaned_content):
    if cleaned_content:
        with open(FILE_TITLE, "a", encoding="utf-8") as f:
            cleaned_content = cleaned_content.replace(r" ", " ")
            cleaned_content = cleaned_content.replace(r"Sponsored Content", "")
            f.write(f"\n{cleaned_content}")


get_content()
