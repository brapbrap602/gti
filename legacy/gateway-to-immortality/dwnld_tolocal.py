import os
import requests
from bs4 import BeautifulSoup


def main():
    # Open the URLs file and read the lines
    with open("urls.txt") as f:
        data = f.readlines()

    urls = [d.strip("\n") for d in data]

    # Create an Gateway To Immortality directory for the files
    output_dir = "Gateway To Immortality"
    os.makedirs(output_dir, exist_ok=True)

    # Iterate through the URLs with enumeration
    for index, url in enumerate(urls, start=1):
        # Send a GET request to the URL
        if index < 2284:
            continue
        print(f"on chapter {index}")
        response = requests.get(url)

        response.raise_for_status()  # Raise an exception for HTTP errors

        # Parse the HTML using BeautifulSoup
        soup = BeautifulSoup(response.text, "html.parser")

        # Locate the <div> with class="bookname" and get the <h1> tag inside
        bookname_div = soup.find("div", class_="bookname")
        title_tag = bookname_div.find("h1")
        title = title_tag.get_text(strip=True)

        # Find the content with id="content"
        content = soup.find(id="content")

        # Write the content to a file if it exists
        if content:
            stripped_content = content.get_text(separator="\n", strip=True)
            stripped_content = stripped_content.replace("章节错误,点此举报(免注册)我们会尽快处理.举报后请耐心等待,并刷新页面。", '')
            stripped_content = stripped_content.replace("请记住本书首发域名：ddyveshu.cc。顶点小说手机版阅读网址：m.ddyveshu.cc", '')
            # Sanitize the title for use as a filename
            filename = os.path.join(output_dir, f"chapter_{index}.html")
            with open(filename, "w", encoding="utf-8") as file:
                # Write the title at the top of the file, separated by <br> tags
                file.write(f"{title}\n\n\n")
                # Write the processed content of the page
                file.write(str(stripped_content))



if __name__ == '__main__':
    main()
