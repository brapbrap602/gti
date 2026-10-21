"""A check's verdict on one stored chapter text."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    check: str  # the check's name, e.g. "poison"; a version has at most one finding per check
    detail: str  # its evidence, e.g. "有没×9 是止×4 退入×3 (3.1/1000)"
