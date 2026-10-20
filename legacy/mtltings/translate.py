from __future__ import annotations
import os
import json
import re
import textwrap
from datetime import datetime
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Dict

from openai import OpenAI
from tenacity import retry, wait_random_exponential

from logging_utils import logger

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]  # key removed from the legacy copy
GEMINI_2_5_FLASH_LITE_LATEST_OPENROUTER = "google/gemini-2.5-flash-lite"
GEMINI_2_0_FLASH_OPENROUTER = "google/gemini-2.0-flash-001"
GEMINI_2_5_FLASH_OPENROUTER = "google/gemini-2.5-flash"

MODEL_CONFIG: Dict[str, Dict[str, Any]] = {
    GEMINI_2_5_FLASH_LITE_LATEST_OPENROUTER: {
        "api_key": OPENROUTER_API_KEY,
        "base_url": "https://openrouter.ai/api/v1",
    },
    GEMINI_2_0_FLASH_OPENROUTER: {
        "api_key": OPENROUTER_API_KEY,
        "base_url": "https://openrouter.ai/api/v1",
    }, GEMINI_2_5_FLASH_OPENROUTER: {
        "api_key": OPENROUTER_API_KEY,
        "base_url": "https://openrouter.ai/api/v1",
    },
}

TRANSLATION_IDENTITY = textwrap.dedent(
    """
    You are an expert translator specializing in Chinese Xianxia novels.
    Your task is to translate the provided chapters into high-quality, atmospheric English prose.

    CRITICAL INSTRUCTIONS:
    1. PROSE STYLE: Maintain a consistent, traditional Xianxia tone.
    2. NO PINYIN: Translate all names (places, sects, items, techniques) into their English meaning or descriptive equivalents. 
       - e.g., '迷香' -> 'Enchanting Fragrance' (NOT 'Mixiang').
    3. PURE ENGLISH: Do not include Chinese characters or pinyin ANYWHERE in the output, including parentheses.
    4. CHAPTER HEADERS: You MUST preserve the "Chapter X" headers exactly as they appear in the source. The chapter header must contain a chapter number. They act as delimiters for parsing.
    5. CONSISTENCY: Use the provided context from previous chapters to maintain naming and terminology consistency.

    """
)


@dataclass
class Translator:
    def __init__(self, model: str):
        self.model = model
        if model not in MODEL_CONFIG:
            raise ValueError(f"Model {model} not in MODEL_CONFIG")
        self.config = MODEL_CONFIG[model]

    @retry(wait=wait_random_exponential(min=5, max=10))
    def translate_batch(self, context: str, raw_batch: str, num_chapters: int) -> str:
        """Translates a batch of chapters using previous 10 chapters for context"""
        logger.info(f"Translating {num_chapters} chapters...")
        prompt = textwrap.dedent(
            f"""
            REFERENCE CONTEXT (Previous 10 Translated Chapters for consistency):
            {context}

            ---

            TRANSLATE THE FOLLOWING {num_chapters} CHAPTER/S only:
            {raw_batch}
        """
        ).strip()

        client = OpenAI(
            api_key=self.config["api_key"], base_url=self.config.get("base_url")
        )
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": TRANSLATION_IDENTITY},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        return response.choices[0].message.content


class NovelTranslator:
    def __init__(self, novel_name: str, model: str):
        self.novel_name = novel_name
        self.source_dir = Path("data/raw") / novel_name
        self.output_dir = Path("data/translated") / novel_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.translator = Translator(model=model)

    def process_batches(
        self, start_chapter: int | None = None, end_chapter: int | None = None
    ):
        """Process chapters in batches of 10"""
        all_raw_paths = self._sorted_chapters()
        if not all_raw_paths:
            logger.warning("No chapters found in source directory")
            return

        # Filter by range
        if start_chapter is None:
            start_chapter = self._extract_chapter_number(all_raw_paths[0])

        target_chapters = [
            p for p in all_raw_paths if self._extract_chapter_number(p) >= start_chapter
        ]
        if end_chapter:
            target_chapters = [
                p
                for p in target_chapters
                if self._extract_chapter_number(p) <= end_chapter
            ]

        if not target_chapters:
            logger.info("No chapters in the specified range need processing.")
            return

        # Process in batches of 5
        for i in range(0, len(target_chapters), 5):
            batch_paths = target_chapters[i : i + 5]
            current_start = self._extract_chapter_number(batch_paths[0])

            # Check if batch is already done (partially or fully)
            # To be safe, we check if all files in the batch exist
            missing = False
            for p in batch_paths:
                ch_num = self._extract_chapter_number(p)
                if not (self.output_dir / f"chapter_{ch_num}.html").exists():
                    missing = True
                    break

            if not missing:
                logger.info(
                    f"Skipping batch starting at chapter {current_start} (all chapters exist)"
                )
                continue

            # Try up to 2 times
            for attempt in range(4):
                logger.info(
                    f"Processing batch starting at chapter {current_start} (Attempt {attempt + 1})..."
                )

                # Get context (10 previous translated chapters)
                context_text = self._get_context(current_start)

                # Get raw text for 5 chapters
                raw_batch_text = self._get_raw_batch(batch_paths)

                # Translate
                translated_response = self.translator.translate_batch(
                    context_text, raw_batch_text, len(batch_paths)
                )

                # Parse and save, returns list of missing chapter numbers
                missing_chapters = self._parse_and_save_batch(
                    translated_response, batch_paths
                )

                if not missing_chapters:
                    break

                if attempt == 0:
                    logger.warning(
                        f"Failed to parse chapters {missing_chapters} on attempt 1. Retrying..."
                    )
                else:
                    logger.error(
                        f"Failed to parse chapters {missing_chapters} after {attempt} attempts. Logging to failed_translations.json"
                    )
                    self._log_failure(missing_chapters)

    def _log_failure(self, missing_chapters: List[int]):
        """Log failed chapters to a JSON file as a flat list of chapter numbers"""
        failure_file = Path("failed_translations.json")
        ch_numbers = set()

        if failure_file.exists():
            try:
                data = json.loads(failure_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, int):
                            ch_numbers.add(item)
            except Exception as e:
                logger.error(f"Could not read {failure_file}: {e}")

        ch_numbers.update(missing_chapters)
        sorted_failures = sorted(list(ch_numbers))

        failure_file.write_text(json.dumps(sorted_failures, indent=4), encoding="utf-8")

    def _get_context(self, current_start: int) -> str:
        """Load up to 10 previous translated chapters for context"""
        prev_chapters = []
        # Look back for the nearest 10 chapters
        all_translated = sorted(
            self.output_dir.glob("chapter_*.html"),
            key=lambda x: self._extract_chapter_number(x),
        )
        # Filter for those before current_start
        context_paths = [
            p for p in all_translated if self._extract_chapter_number(p) < current_start
        ][-10:]

        for p in context_paths:
            content = p.read_text(encoding="utf-8")
            # Just take the text content, strip tags if necessary?
            # For now, providing the full html (or text) is fine.
            prev_chapters.append(
                f"Source chapter number: Chapter {self._extract_chapter_number(p)}\n{content}"
            )

        return (
            "\n\n".join(prev_chapters)
            if prev_chapters
            else "No previous context available."
        )

    def _get_raw_batch(self, batch_paths: List[Path]) -> str:
        """Combine 5 raw chapters into a single string with headers"""
        batch_content = []
        for p in batch_paths:
            ch_num = self._extract_chapter_number(p)
            content = p.read_text(encoding="utf-8")
            # Ensure the header is clear
            batch_content.append(f"Chapter {ch_num}\n{content}")
        return "\n\n".join(batch_content)

    def _parse_and_save_batch(
        self, response: str, batch_paths: List[Path]
    ) -> List[int]:
        """Split the LLM response by chapter header and save individual files. Returns missing chapter numbers."""
        # Split by "Chapter X" headers. We use a capturing group to keep the headers.
        # Pattern: Start of line, "Chapter" followed by digits, maybe some title, then newline.
        parts = re.split(r"(?im)^(Chapter\s+\d+.*)$", response)

        # parts will look like ['', 'Chapter 1000', 'Content...', 'Chapter 1001', 'Content...', ...]
        # We pair ['Chapter 1000', 'Content...'] together.

        chapters_found: Dict[int, str] = {}
        for i in range(1, len(parts), 2):
            header = parts[i]
            content = parts[i + 1] if i + 1 < len(parts) else ""

            match = re.search(r"(\d+)", header)
            if match:
                ch_num = int(match.group(1))
                chapters_found[ch_num] = (header + "\n" + content).strip()

        missing = []
        # Save the ones we were expecting
        for p in batch_paths:
            ch_num = self._extract_chapter_number(p)
            if ch_num in chapters_found:
                output_path = self.output_dir / f"chapter_{ch_num}.html"
                output_path.write_text(chapters_found[ch_num], encoding="utf-8")
                logger.info(f"Successfully saved chapter {ch_num}")
            else:
                logger.error(f"Failed to find chapter {ch_num} in LLM response!")
                missing.append(ch_num)

        return missing

    def _sorted_chapters(self) -> List[Path]:
        return sorted(
            self.source_dir.iterdir(), key=lambda p: self._extract_chapter_number(p)
        )

    @staticmethod
    def _extract_chapter_number(path: Path) -> int:
        match = re.search(r"chapter_(\d+)", path.stem.lower())
        return int(match.group(1)) if match else 0


def main():
    NOVEL = "my_longevity_simulation"
    parser = ArgumentParser()
    parser.add_argument("-s", "--start-ch", type=int, default=None)
    parser.add_argument("-e", "--end-ch", type=int, default=None)
    parser.add_argument(
        "--model", type=str, default=GEMINI_2_5_FLASH_OPENROUTER
    )
    args = parser.parse_args()

    if not (Path("data/raw") / NOVEL).exists():
        raise SystemExit(f"Source directory not found: data/raw/{NOVEL}")

    novel_translator = NovelTranslator(novel_name=NOVEL, model=args.model)
    novel_translator.process_batches(args.start_ch, args.end_ch)


if __name__ == "__main__":
    main()
