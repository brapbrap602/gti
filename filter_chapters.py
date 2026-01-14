import argparse
import re


def extract_chapter_number(text):
    # Matches "Chapter 1" or "Chapter 1: Title"
    match = re.search(r"Chapter\s*(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def process_html(input_file, output_file, start_ch, end_ch):
    print(f"Reading {input_file}...")
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        # Fallback for different encodings if utf-8 fails
        with open(input_file, "r", encoding="latin-1") as f:
            content = f.read()

    # 1. Filter Table of Contents (TOC)
    print("Filtering Table of Contents...")
    # Matches the <nav> block regardless of its specific ID or classes
    toc_pattern = re.compile(r'(<nav[^>]*?role="doc-toc"[^>]*>)(.*?)(</nav>)', re.DOTALL)
    toc_match = toc_pattern.search(content)

    if toc_match:
        toc_start_tag = toc_match.group(1)
        toc_inner = toc_match.group(2)
        toc_end_tag = toc_match.group(3)

        # Match each <li> entry in the TOC
        li_pattern = re.compile(r"(<li[^>]*>.*?</li>)", re.DOTALL)
        lis = li_pattern.findall(toc_inner)
        
        filtered_lis = []
        for li in lis:
            num = extract_chapter_number(li)
            if num is not None and start_ch <= num <= end_ch:
                filtered_lis.append(li)

        # Rebuild TOC inner content: Keep the <h2> and the <ol> tags
        h2_match = re.search(r"(<h2[^>]*>.*?</h2>)", toc_inner, re.DOTALL)
        ol_start_match = re.search(r"(<ol[^>]*>)", toc_inner)
        
        h2 = h2_match.group(1) if h2_match else ""
        ol_start = ol_start_match.group(1) if ol_start_match else "<ol>"

        new_toc_content = (
            f"\n      {h2}\n      {ol_start}\n        " 
            + "\n        ".join(filtered_lis) 
            + "\n      </ol>\n    "
        )
        
        content = (
            content[:toc_match.start()] 
            + toc_start_tag 
            + new_toc_content 
            + toc_end_tag 
            + content[toc_match.end():]
        )
    else:
        print("Warning: TOC (<nav role='doc-toc'>) not found. Skipping TOC filter.")

    # 2. Filter Main Content Chapters
    print("Filtering chapters in content...")
    
    # This regex looks for <h1>, <h2>, or <p> tags that contain "Chapter [number]"
    # It is case-insensitive and handles various Calibre class names.
    chapter_regex = re.compile(r'(<(h[1-4]|p)[^>]*>(?:<[^>]+>)*\s*Chapter\s+\d+.*?</\2>)', re.IGNORECASE | re.DOTALL)

    # Find all chapter headers
    all_headers = list(chapter_regex.finditer(content))
    
    if not all_headers:
        print("Error: Could not find any chapter headers in the content.")
        print("Looking for tags like: <h1 ...>Chapter 1</h1> or <p ...>Chapter 1</p>")
        return

    # Keep the head/CSS/meta parts of the file
    first_chapter_idx = all_headers[0].start()
    file_header = content[:first_chapter_idx]
    
    # Extract the footer (everything after the last chapter's likely end)
    # We'll just grab the very end of the file for simplicity
    footer_match = re.search(r"(</body>\s*</html>)", content, re.IGNORECASE)
    file_footer = footer_match.group(1) if footer_match else "</body></html>"

    # Identify which headers fall within our range
    valid_segments = []
    
    for i in range(len(all_headers)):
        header_match = all_headers[i]
        ch_num = extract_chapter_number(header_match.group(1))
        
        if ch_num is not None and start_ch <= ch_num <= end_ch:
            # Start of this chapter
            start_pos = header_match.start()
            # End is the start of the next chapter, or the footer
            if i + 1 < len(all_headers):
                end_pos = all_headers[i+1].start()
            else:
                # If it's the last chapter, look for the footer
                end_pos = content.find("</body>") 
                if end_pos == -1: end_pos = len(content)
            
            valid_segments.append(content[start_pos:end_pos])

    if not valid_segments:
        print(f"No chapters found in range {start_ch} to {end_ch}.")
        return

    # 3. Save Output
    print(f"Saving to {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(file_header)
        f.write("".join(valid_segments))
        f.write("\n" + file_footer)
    
    print(f"Success! Kept {len(valid_segments)} chapters.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter Calibre HTML by chapter range.")
    parser.add_argument("input", help="Input HTML file")
    parser.add_argument("output", help="Output HTML file")
    parser.add_argument("start", type=int, help="Start chapter")
    parser.add_argument("end", type=int, help="End chapter")

    args = parser.parse_args()
    process_html(args.input, args.output, args.start, args.end)
