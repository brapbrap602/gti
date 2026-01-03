import argparse
import re


def extract_chapter_number(text):
    match = re.search(r"Chapter\s+(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def process_html(input_file, output_file, start_ch, end_ch):
    print(f"Reading {input_file}...")
    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    print("Filtering Table of Contents...")
    # Find the TOC nav block
    toc_nav_pattern = re.compile(
        r'(<nav[^>]*id="toc_main"[^>]*>)(.*?)(</nav>)', re.DOTALL
    )
    toc_nav_match = toc_nav_pattern.search(content)

    if toc_nav_match:
        toc_nav_start = toc_nav_match.group(1)
        toc_inner = toc_nav_match.group(2)
        toc_nav_end = toc_nav_match.group(3)

        # Filter <li> items within TOC
        li_pattern = re.compile(r"(<li[^>]*>.*?</li>)", re.DOTALL)
        lis = li_pattern.findall(toc_inner)
        filtered_lis = []
        for li in lis:
            ch_num = extract_chapter_number(li)
            if ch_num is not None and start_ch <= ch_num <= end_ch:
                filtered_lis.append(li)

        # Reconstruct TOC inner part (assuming there's an <ol> wrapper)
        ol_start_match = re.search(r"<ol[^>]*>", toc_inner)
        ol_start = (
            ol_start_match.group(0) if ol_start_match else '<ol class="calibre2">'
        )

        h2_match = re.search(r"<h2[^>]*>.*?</h2>", toc_inner)
        h2 = (
            h2_match.group(0)
            if h2_match
            else '<h2 class="calibre1">Table of Contents</h2>'
        )

        new_toc_inner = (
            f"\n        {h2}\n        {ol_start}\n          "
            + "\n          ".join(filtered_lis)
            + "\n        </ol>\n      "
        )
        content = (
            content[: toc_nav_match.start()]
            + toc_nav_start
            + new_toc_inner
            + toc_nav_end
            + content[toc_nav_match.end() :]
        )

    # 2. Filter Content
    print("Filtering chapters in content...")
    # Find all h1 headers with calibre1 class
    h1_pattern = re.compile(r'(<h1[^>]*class="calibre1"[^>]*>.*?</h1>)', re.DOTALL)

    # Split content by h1 tags, keeping the h1 tags in the result
    # We find where the first h1 starts to preserve the header
    first_h1_match = h1_pattern.search(content)
    if not first_h1_match:
        print("No chapter headers found (h1 class='calibre1').")
        return

    header = content[: first_h1_match.start()]
    body_and_footer = content[first_h1_match.start() :]

    # Detect the footer (last closing tags)
    footer_match = re.search(r"</body>\s*</html>", body_and_footer, re.IGNORECASE)
    footer = footer_match.group(0) if footer_match else "</body></html>"
    # Content part to be filtered
    content_to_filter = (
        body_and_footer[: footer_match.start()] if footer_match else body_and_footer
    )

    # Split the main content by H1s
    chunks = h1_pattern.split(content_to_filter)
    # chunks[0] is empty because split starts at first delimiter
    # chunks[1] = H1_1, chunks[2] = Content_1, ...

    result_parts = [header]
    for i in range(1, len(chunks), 2):
        h1 = chunks[i]
        chunk_content = chunks[i + 1] if i + 1 < len(chunks) else ""

        ch_num = extract_chapter_number(h1)
        if ch_num is not None and start_ch <= ch_num <= end_ch:
            result_parts.append(h1)
            result_parts.append(chunk_content)

    result_parts.append(footer)

    print(f"Saving to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("".join(result_parts))
    print("Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Filter chapters in an HTML file (Regex Optimized)."
    )
    parser.add_argument("input", help="Path to the input HTML file")
    parser.add_argument("output", help="Path to the output HTML file")
    parser.add_argument("start", type=int, help="Starting chapter number (inclusive)")
    parser.add_argument("end", type=int, help="Ending chapter number (inclusive)")

    args = parser.parse_args()
    process_html(args.input, args.output, args.start, args.end)
