"""Shared types for statement parsers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedTransaction:
    """Normalised transaction ready for database insertion."""

    date: str           # ISO-8601: YYYY-MM-DD
    description: str
    amount: float       # negative = debit/expense, positive = credit/income
    account: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.description = self.description.strip()
        self.amount = round(self.amount, 4)
