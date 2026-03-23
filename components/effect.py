from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import sounds
import color

ColorRGB = tuple[int, int, int]
Glyph = str | int


@dataclass(frozen=True)
class EffectDisplay:
    glyph: Glyph = "?"
    fg: ColorRGB = (255, 255, 255)
    bg: Optional[ColorRGB] = None
    label: Optional[str] = None

@dataclass
class Effect:
    name: str
    duration: Optional[int] = None  # None = permanent
    description: str = ""
    type: str = "status"  # e.g., "status", "buff", "debuff"
    display: EffectDisplay = field(default_factory=EffectDisplay)

    def tick(self, target):
        """Called each turn to update effect state. Returns True if expired."""
        if self.duration is None:
            return False
        self.duration -= 1
        return self.duration <= 0

    def get_display(self) -> EffectDisplay:
        if self.display.label is not None:
            return self.display
        return EffectDisplay(
            glyph=self.display.glyph,
            fg=self.display.fg,
            bg=self.display.bg,
            label=self.name,
        )

class Darkness(Effect):
    def __init__(self, duration: Optional[int] = None):
        super().__init__(
            name="Darkness",
            duration=duration,
            description="Engulfed in darkness. Vision is severely limited.",
            type="debuff",
            display=EffectDisplay(glyph=0xE020, fg=(140, 90, 220), label="Darkness"),
        )

    def tick(self, target):
        return super().tick(target)


class PoisonEffect(Effect):
    def __init__(self, amount: int, duration: int):
        super().__init__(
            name="Poisoned",
            duration=duration,
            description=f"Take {amount} damage each turn.",
            type="debuff",
            display=EffectDisplay(glyph="P", fg=(80, 220, 120), label="Poisoned"),
        )
        self.amount = amount  # Store the damage amount

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -=1
        sounds.play_poison_burn_sound()
        target.fighter.take_damage(self.amount, causes_bleeding=False)
        return self.duration <= 0
        
class DarkvisionEffect(Effect):
    def __init__(self, duration: int):
        super().__init__(
            name="Darkvision",
            duration=duration,
            description="See in the dark.",
            type="buff",
            display=EffectDisplay(glyph=chr(0xE023), fg=(180, 180, 255), label="Darkvision"),
        )

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -= 1
        return self.duration <= 0
    
    def get_message(self):
        if self.duration == 0:
            return ("Darkness once again engulfs you...", color.purple)
        
class BurningEffect(Effect):
    """Simple designator class. Does no damage."""

    def __init__(self, amount: int, duration: int):
        super().__init__(
            name="Burning",
            duration=duration,
            description=f"Take {amount} fire damage each turn.",
            type="debuff",
            display=EffectDisplay(glyph=chr(0xE022), fg=(255, 120, 40), label="Burning"),
        )
        self.amount = amount  # Store the damage amount

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -=1
        sounds.play_fire_burn_sound()
        return self.duration <= 0


class BloodyEffect(Effect):
    """Display-only status for blood coating grouping in the effects UI."""

    def __init__(self, duration: Optional[int] = None):
        super().__init__(
            name="Bloody",
            duration=duration,
            description="Covered in blood.",
            type="status",
            display=EffectDisplay(glyph=chr(0xE021), fg=color.sprite_sheet, label="Bloody"),
        )