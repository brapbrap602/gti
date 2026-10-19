from bs4 import BeautifulSoup

url_base = "https://www.wuxiaworld.com/novel/rmji/rmji-chapter- {}"

# for x in range(1374, 1799):
# for x in range(1374, 1375):
#     r = requests.get(url_base.format(x))
#     print(r.url)
#     soup = BeautifulSoup(r.content, features="html5lib")
#     print(f"On Chapter: {x}")
#     file_name = r"recordofmortalsjourneyafter1374.txt"
#
#     # with open(file_name, 'a', encoding="utf-8") as f:
#     for stuff in soup.find_all('div', {'class': 'chapter-content'}):
#     # for stuff in soup.find_all("br"):
#             # f.write(stuff.text)
#                 # f.write("\n")
#         print(stuff.text)
#         print(stuff)

# import cloudscraper
#
# jar = {"AWSALBCORS": "", "AWSALB": "", "__cfduid": ""}
#
# for x in range(1374, 1375):
#     scraper = cloudscraper.create_scraper()
#
#     content = scraper.get(url_base.format(x), cookies=jar)
#     soup = BeautifulSoup(content.text, features="html5lib")
#     print(content.cookies.keys())
#     print(soup.text)
#     content.cookies.clear()

from selenium import webdriver

for x in range(1789, 1968):
    driver = webdriver.Chrome(
        executable_path=r"C:\Users\HT\Downloads\chromedriver_win32 (1)\chromedriver.exe"
    )
    driver.get(f"https://www.wuxiaworld.com/novel/rmji/rmji-chapter-{x}")
    print(f"on chapter {x}")
    try:
        elem = driver.find_element_by_id("chapter-content")
        with open(r"recordofmortalsjourneyafter1790.txt", "a") as f:
            f.write(BeautifulSoup(elem.text, features="html5lib").text)
            f.write("\n")
    except BaseException as e:
        with open(r"recordofmortalsjourneyafter1790.txt", "a") as f:
            msg = f"ERROR_ERROR_ERROR_ERROR_{e}!!!!!chapter{x}!!!!!!"
            f.write(msg)
            f.write("\n")
    finally:
        driver.close()
