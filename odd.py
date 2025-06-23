import re
from pathlib import Path
from bs4 import BeautifulSoup

# --- Configuration ---
# 1. Set the name of your large input file
INPUT_FILE_NAME = "your_large_book_file.html"

# 2. Set the name of the output directory
OUTPUT_DIR_NAME = "odd_ones"

# 3. Set the minimum number of underscores to count a <p> tag
MIN_UNDERSCORES = 15
# --- End of Configuration ---

def process_book():
    output_dir = Path(OUTPUT_DIR_NAME)
    input_file = Path(INPUT_FILE_NAME)

    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_file.is_file():
        print(f"[ERROR] Input file not found: {input_file}")
        return

    print(f"[*] Reading and parsing the input file: {input_file}...")
    try:
        # Using lxml for better performance on large files
        soup = BeautifulSoup(input_file.read_text(encoding='utf-8'), 'lxml')
    except Exception as e:
        print(f"[ERROR] Could not read or parse the file. Error: {e}")
        return

    # Find all divs that act as chapter containers: <div class="calibre" dir="default">
    chapter_divs = soup.find_all('div', class_='calibre', attrs={'dir': 'default'})

    if not chapter_divs:
        print("[WARNING] No chapter dividers found. Please check your HTML structure.")
        return

    print(f"[*] Found {len(chapter_divs)} potential chapters. Processing...")
    chapters_written = 0

    for chapter in chapter_divs:
        # Find the h1 tag like: <h1 class="calibre2">Chapter 126...</h1>
        h1_tag = chapter.find('h1', class_='calibre2')
        if not h1_tag:
            continue # Not a chapter container, skip

        # Extract chapter number using regex: "Chapter" + whitespace + digits
        match = re.search(r'Chapter\s+(\d+)', h1_tag.get_text())
        if not match:
            continue

        chapter_number = match.group(1)

        # Count <p class="calibre5"> tags with many underscores
        p_tags = chapter.find_all('p', class_='calibre5')
        dash_p_tag_count = sum(1 for p in p_tags if p.get_text().count('_') >= MIN_UNDERSCORES)

        # Check if the count is odd (and not zero)
        if dash_p_tag_count > 0 and dash_p_tag_count % 2 != 0:
            print(f"[+] Chapter {chapter_number}: Found {dash_p_tag_count} tags (ODD). Writing to file.")
            
            output_path = output_dir / f"chapter_{chapter_number}.html"
            
            try:
                # .prettify() makes the saved HTML readable
                output_path.write_text(chapter.prettify(), encoding='utf-8')
                chapters_written += 1
            except Exception as e:
                print(f"[ERROR] Could not write to file {output_path}. Error: {e}")

    print("\n-----------------------------------------")
    print(f"[*] Script finished. Wrote {chapters_written} chapters to the '{output_dir}' directory.")
    print("-----------------------------------------")

if __name__ == "__main__":
    process_book()