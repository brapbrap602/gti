"""Glossary pass and LLM translation of raw chapters via OpenRouter."""
import os

# pydantic-ai prints a startup banner on first use unless this is set.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
