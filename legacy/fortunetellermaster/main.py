from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions

options = FirefoxOptions()
options.add_argument("--headless")
driver = webdriver.Firefox(
    executable_path=r"C:\Users\HT\Documents\geckodriver-v0.30.0-win64-1\geckodriver.exe",
    options=options,
)

with open(r"C:\Users\HT\Documents\code\fortunetellermaster\links.txt") as f:
    for link in f.readlines():
        link = link.replace("\n", "")
        if link:
            print(f"On Chapter: {link}")
            driver.get(link)
            text = driver.find_element(By.CLASS_NAME, "entry-content").text
            with open("fortunetellermaster.txt", "a", encoding="utf-8") as f:
                f.write(
                    link.replace("\n", "")
                    .split("ftm/")[1]
                    .replace("/", "")
                    .replace("-", " ")
                )
                f.write("\n")
                f.write(text)
                f.write("\n")
