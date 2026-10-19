import requests
from bs4 import BeautifulSoup

stuff = {
    "Genesis": 50,
    "Exodus": 40,
    "Leviticus": 27,
    "Numbers": 36,
    "Deuteronomy": 34,
    "Joshua": 24,
    "Judges": 21,
    "Ruth": 4,
    "1+Samuel": 31,
    "2+Samuel": 24,
    "1+Kings": 22,
    "2+Kings": 25,
    "1+Chronicles": 29,
    "2+Chronicles": 36,
    "Ezra": 10,
    "Nehemiah": 13,
    "Esther": 10,
    "Job": 42,
    "Psalms": 150,
    "Proverbs": 31,
    "Ecclesiastes": 12,
    "Song of Songs": 8,
    "Isaiah": 66,
    "Jeremiah": 52,
    "Lamentations": 5,
    "Ezekiel": 48,
    "Daniel": 12,
    "Hosea": 14,
    "Joel": 3,
    "Amos": 9,
    "Obadiah": 1,
    "Jonah": 4,
    "Micah": 7,
    "Nahum": 3,
    "Habakkuk": 3,
    "Zephaniah": 3,
    "Haggai": 2,
    "Zechariah": 14,
    "Malachi": 4,
    "Matthew": 28,
    "Mark": 16,
    "Luke": 24,
    "John": 21,
    "Acts": 28,
    "James": 5,
    "1+Peter": 5,
    "2+Peter": 3,
    "1+John": 5,
    "2+John": 1,
    "3+John": 1,
    "Jude": 1,
    "Romans": 16,
    "1+Corinthians": 16,
    "2+Corinthians": 13,
    "Galatians": 6,
    "Ephesians": 6,
    "Philippians": 4,
    "Colossians": 4,
    "1+Thessalonians": 5,
    "2+Thessalonians": 3,
    "1+Timothy": 6,
    "2+Timothy": 4,
    "Titus": 3,
    "Philemon": 1,
    "Hebrews": 13,
    "Revelation": 22,
}


def write_stuff(book, title):
    with open(f"{title}.txt", "a", encoding="utf-8") as f:
        f.write(book)


def write_from_gateway(stuff):
    for book_name_cap, number_of_chapters in stuff.items():
        a_book = ["\n", f'A Bible Book: {book_name_cap.replace("+", " ")}', "\n"]
        for book_chapter in range(1, number_of_chapters + 1):
            url = f"https://www.biblegateway.com/passage/?search={book_name_cap}+{book_chapter}&version=ESV"
            r = requests.get(url)
            soup = BeautifulSoup(r.content, features="lxml")
            print(f"book: {book_name_cap}, chapter {book_chapter}")

            a_chapter = []
            for stuff in soup.find_all("p"):
                a_chapter.append(stuff.text)

            a_book.extend(a_chapter)
            a_chapter = []

        write_stuff("\n".join(a_book), title="biblegateway")
        a_book = []


def write_from_esv_org(stuff):
    for book_name_cap, number_of_chapters in stuff.items():
        a_book = ["\n", f'A Bible Book: {book_name_cap.replace("+", " ")}', "\n\n"]
        for book_chapter in range(1, number_of_chapters + 1):
            url = f"https://www.esv.org/{book_name_cap}+{book_chapter}/"
            r = requests.get(url)
            soup = BeautifulSoup(r.content, features="lxml")
            print(f"book: {book_name_cap}, chapter {book_chapter}")

            a_chapter = ["\n\n"]

            for things in soup.find_all("u"):
                if len(a_chapter) % 30 == 0:
                    a_chapter.append("\n")
                a_chapter.append(things.text)

            a_book.extend(a_chapter)
            a_chapter = ["\n\n"]

        write_stuff("".join(a_book), title="from_esv_org")
        a_book = []


# write_from_tagteway(stuff)
write_from_esv_org(
    stuff,
)
