import argparse
import json
import logging
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from openai import OpenAI

# Try to import from translate, if not possible define constants locally
try:
    from translate import OPENROUTER_API_KEY, GEMINI_2_0_FLASH_OPENROUTER as DEFAULT_MODEL
except ImportError:
    import os
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    DEFAULT_MODEL = "google/gemini-2.0-flash-001"

from logging_utils import logger

@dataclass
class ChapterSummary:
    number: int
    title: str
    sentences: List[str]

class Summarizer:
    def __init__(self, model: str):
        self.model = model
        self.client = OpenAI(
            api_key=OPENROUTER_API_KEY, 
            base_url="https://openrouter.ai/api/v1"
        )

    def summarize(self, content: str) -> List[str]:
        """Summarizes content into exactly 20 sentences."""
        if not content.strip():
            return []

        prompt = textwrap.dedent(
            f"""
            Summarize the following chapter content into exactly 20 sentences. 
            Return ONLY the 20 sentences, one per line. No other text.

            CONTENT:
            {content}
            """
        ).strip()

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a literary assistant that provides concise 20-sentence summaries of novel chapters."},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
            )
            
            summary_text = response.choices[0].message.content.strip()
            # Split by newline and filter out empty lines, ensuring we get sentences
            sentences = [s.strip() for s in summary_text.split('\n') if s.strip()]
            return sentences[:20]
        except Exception as e:
            logger.error(f"Error calling OpenRouter: {e}")
            return []

def parse_index_all(file_path: Path) -> List[tuple[int, str, str]]:
    """Parses index_all.html and returns a list of (number, title, content) tuples."""
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return []

    logger.info(f"Reading source file: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    
    # Regex for chapter headers: <h1 id="calibre_link-61" class="calibre1">Chapter 429: A Lion's Demands</h1>
    header_pattern = re.compile(r'<h1 id="calibre_link-\d+" class="calibre1">Chapter (\d+)(?::\s*(.*?))?</h1>', re.IGNORECASE)
    
    matches = list(header_pattern.finditer(content))
    chapters = []
    
    for i, match in enumerate(matches):
        ch_num = int(match.group(1))
        # Title is group 2, if None use chapter number
        raw_title = match.group(2)
        title = raw_title.strip() if raw_title else f"Chapter {ch_num}"
        
        # Content is between this header and the next header
        start_pos = match.end()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(content)
        
        ch_content = content[start_pos:end_pos].strip()
        
        chapters.append((ch_num, title, ch_content))
        
    logger.info(f"Parsed {len(chapters)} chapters from index_all.html")
    return chapters

def main():
    parser = argparse.ArgumentParser(description="Summarize chapters from index_all.html.")
    parser.add_argument("start", type=int, nargs='?', help="Start chapter number.")
    parser.add_argument("end", type=int, nargs='?', help="End chapter number.")
    parser.add_argument("-s", "--start-ch", dest="start_opt", type=int, help="Start chapter number (flag).")
    parser.add_argument("-e", "--end-ch", dest="end_opt", type=int, help="End chapter number (flag).")
    parser.add_argument("--src", type=str, default=r"C:\Users\HT\Documents\code\github_pages\longevity simulation\index_all.html", help="Source index_all.html path.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="OpenRouter model to use.")
    args = parser.parse_args()

    start_chapter = args.start_opt if args.start_opt is not None else args.start
    end_chapter = args.end_opt if args.end_opt is not None else args.end

    if start_chapter is None:
        parser.print_help()
        return

    # Default end_chapter to start_chapter if not provided
    if end_chapter is None:
        end_chapter = start_chapter

    logger.info(f"Target range: {start_chapter} to {end_chapter}")

    all_chapters = parse_index_all(Path(args.src))
    
    # Filter by range
    target_chapters = [
        (num, title, content) for num, title, content in all_chapters 
        if start_chapter <= num <= end_chapter
    ]

    if not target_chapters:
        logger.warning(f"No chapters found in range {start_chapter}-{end_chapter}.")
        return

    summarizer = Summarizer(args.model)
    summaries = []

    for num, title, content in target_chapters:
        logger.info(f"Summarizing Chapter {num}: {title}...")
        sentences = summarizer.summarize(content)
        if sentences:
            summaries.append(ChapterSummary(number=num, title=title, sentences=sentences))
        else:
            logger.warning(f"Failed to summarize Chapter {num}.")

    if summaries:
        output_file = Path(f"summaries_ch{start_chapter}-{end_chapter}.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump([s.__dict__ for s in summaries], f, indent=4, ensure_ascii=False)
        logger.info(f"Saved {len(summaries)} summaries to {output_file}")
    else:
        logger.error("No summaries were generated.")

if __name__ == "__main__":
    main()
