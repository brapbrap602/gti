"""Text to speech: the TtsEngine seam, the edge-tts engine, and the sentence cache.

The cache stores one MP3 per (voice, sentence text), so editing one sentence of
a chapter re-synthesizes only that sentence, and an interrupted build loses at
most the sentences in flight. An empty file means the engine had nothing to say
for that text; it is cached too, so it is not asked again.
"""

import asyncio
import hashlib
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import edge_tts
from edge_tts.exceptions import NoAudioReceived

DEFAULT_VOICE = "en-US-BrianNeural"
# Requests in flight. The endpoint publishes no limit (per IP, its maintainer believes); each
# request mostly waits on the server (~6 s), so speed grows with this: 2 gave 0.3 sentences/s,
# 8 gave 1.3, 16 gave 2.0 (2026-11-03). Words were reported dropped at ~50 long requests.
DEFAULT_CONCURRENCY = 8


class TtsEngine(Protocol):
    @property
    def voice(self) -> str: ...

    async def synthesize(self, text: str) -> bytes:
        """MP3 bytes for text; empty when there is nothing to say. Raises when the engine fails."""
        ...


class EdgeTts:
    """Microsoft Edge's online voices (unofficial endpoint), with retries and backoff."""

    def __init__(self, voice: str = DEFAULT_VOICE, attempts: int = 5, base_delay: float = 1.0):
        self._voice = voice
        self._attempts = attempts
        self._base_delay = base_delay

    @property
    def voice(self) -> str:
        return self._voice

    async def synthesize(self, text: str) -> bytes:
        for attempt in range(1, self._attempts + 1):
            try:
                audio = bytearray()
                async for chunk in edge_tts.Communicate(text, self._voice).stream():
                    if chunk["type"] == "audio":
                        audio += chunk["data"]
                return bytes(audio)
            except NoAudioReceived:
                # Usually text with nothing to say; sometimes a transient hiccup, so retry first.
                if attempt == self._attempts:
                    return b""
            except Exception:
                if attempt == self._attempts:
                    raise
            await asyncio.sleep(self._base_delay * 2 ** (attempt - 1))
        raise AssertionError("unreachable")


class SentenceCache:
    def __init__(self, folder: Path, engine: TtsEngine):
        self._folder = folder / _safe(engine.voice)
        self._engine = engine
        self.synthesized = 0
        self.reused = 0

    async def render(
        self,
        sentences: Sequence[str],
        limit: asyncio.Semaphore,
        on_sentence: Callable[[int, int], None] | None = None,
    ) -> list[Path]:
        """The cached MP3 of each sentence that has audio, in order; missing ones are synthesized.

        `on_sentence(done, total)` is called with total distinct sentences before any is
        ready (done 0) and after each one is cached or synthesized.
        """
        paths = [self._path(s) for s in sentences]
        unique = dict(zip(paths, sentences))  # a repeated line is synthesized once
        done = 0

        async def ensure(sentence: str, path: Path) -> None:
            nonlocal done
            await self._ensure(sentence, path, limit)
            done += 1
            if on_sentence:
                on_sentence(done, len(unique))

        if on_sentence:
            on_sentence(0, len(unique))
        await asyncio.gather(*(ensure(s, p) for p, s in unique.items()))
        return [p for p in paths if p.stat().st_size > 0]

    async def _ensure(self, sentence: str, path: Path, limit: asyncio.Semaphore) -> None:
        if path.exists():
            self.reused += 1
            return
        async with limit:
            audio = await self._engine.synthesize(sentence)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(audio)
        os.replace(tmp, path)
        self.synthesized += 1

    def _path(self, sentence: str) -> Path:
        digest = hashlib.sha256(f"{self._engine.voice}\0{sentence}".encode()).hexdigest()
        return self._folder / digest[:2] / f"{digest}.mp3"


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
