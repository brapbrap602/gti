"""What the translator returns for one chapter: the structured output it must fill in."""

from pydantic import BaseModel, Field

from novel_translate.glossary import Category


class Para(BaseModel):
    id: int = Field(description="the id of the source paragraph this translates; one output paragraph per source id")
    text: str


class NewTerm(BaseModel):
    zh: str = Field(description="a proper name or fixed term in this chapter that the glossary did not give")
    en: str = Field(description="how you rendered it")
    category: Category


class Translated(BaseModel):
    title: str = Field(description="the chapter title in English, without 'Chapter N'")
    paragraphs: list[Para]
    new_terms: list[NewTerm] = Field(default=[], description="names you had to render yourself")
