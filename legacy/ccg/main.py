import bs4
import requests

FILE_TITLE = "ccg.txt"
URL = (
    "https://www.lightnovelspot.com/novel/cultivation-chat-group/150-chapter-{chapter}"
)


def get_content():
    for chapter in range(1, 1778):
        print("On chapter: ", chapter)
        try:
            r = requests.get(URL.format(chapter=chapter))
            wrap_in_bs4(r.text)
        except BaseException as e:
            print(f"Error on : {chapter} -> {e.__cause__}")
            with open("errors.txt", "a") as f:
                f.write(str(e))


def wrap_in_bs4(content):
    soup = bs4.BeautifulSoup(content, "html.parser")
    write_content(f"\n\t{soup.title.text}\t\n")
    for item in soup.find_all("p"):
        if item.text:
            write_content(item.text)


def write_content(content):
    if content:
        with open(FILE_TITLE, "a", encoding="utf-8") as f:
            clean = content.replace(r" ", " ")
            clean = clean.replace(r"​", "")
            clean = clean.replace(r"‎", "")
            clean = clean.replace(r"‍", "")
            clean = clean.replace(r"­", "")
            clean = clean.replace(r"‌", "")
            clean = clean.replace(r"Updated_at lightnovelspot.com", "")
            clean = clean.replace(r"Cultivation Chat Group (Web Novel) - ", "")
            clean = clean.replace(r" | Light Novel Spot", "")
            if "lightnovelspot" not in clean:
                f.write(f"\n{clean}")


get_content()
