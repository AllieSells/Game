from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Effect:
    name: str
    duration: Optional[int] = None  # None = permanent
    description: str = ""
    type: str = "status"  # e.g., "status", "buff", "debuff"

    def tick(self, target):
        """Called each turn to update effect state. Returns True if expired."""
        if self.duration is None:
            return False
        self.duration -= 1
        return self.duration <= 0
