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

class PoisonEffect(Effect):
    def __init__(self, amount: int, duration: int):
        super().__init__(
            name="Poisoned",
            duration=duration,
            description=f"Take {amount} damage each turn.",
            type="debuff"
        )
        self.amount = amount  # Store the damage amount

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -=1
        target.fighter.take_damage(self.amount)
        return self.duration <= 0
        