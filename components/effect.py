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

class HealingEffect(Effect):
    def __init__(self, total_amount: int, duration: int):
        super().__init__(
            name="Healing",
            duration=duration,
            description=f"Heal {total_amount} HP over {duration} turns.",
            type="buff",
            display=EffectDisplay(glyph=chr(0xE025), fg=(255, 255, 255), label="Healing"),
        )
        self.total_amount = total_amount
        self.amount_per_tick = total_amount // duration if duration > 0 else total_amount

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -= 1
        heal_amount = self.amount_per_tick
        if self.duration == 0:  # Heal any remaining amount on the last tick
            heal_amount = self.total_amount - (self.amount_per_tick * (self.total_amount // self.amount_per_tick - 1))
        target.fighter.heal(heal_amount)
        return self.duration <= 0

class TiredEffect(Effect):
    def __init__(self, duration: int):
        super().__init__(
            name="Tired",
            duration=duration,
            description="Reduced mobility.",
            type="debuff",
            display=EffectDisplay(glyph=chr(0xE026), fg=(255, 255, 255), label="Tired"),
        )
    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -= 1
        return self.duration <= 0
    



class LightEffect(Effect):
    """Applied to a summoned light orb. When it expires the orb is silently
    removed from the map — no death sound, no message."""

    def __init__(self, duration: int):
        super().__init__(
            name="Illuminated",
            duration=duration,
            description="A summoned orb of light that will fade after a time.",
            type="status",
            display=EffectDisplay(glyph=chr(0xE027), fg=(255, 255, 150), label="Illuminated"),
        )

    def tick(self, target):
        if self.duration is None:
            return False
        # Particle is now managed by engine.tick() — no per-turn spawning needed here
        self.duration -= 1
        if self.duration <= 0:
            # Silently remove the orb from the map
            try:
                gm = getattr(target, "gamemap", None)
                if gm is not None:
                    try:
                        gm.entities.remove(target)
                    except (KeyError, ValueError):
                        gm.entities.discard(target)
                target.ai = None
            except Exception:
                pass
            return True
        return False


class Darkness(Effect):
    def __init__(self, duration: Optional[int] = None):
        super().__init__(
            name="Darkness",
            duration=duration,
            description="Engulfed in darkness. Vision is severely limited.",
            type="debuff",
            display=EffectDisplay(glyph=chr(0xE020), fg=(255, 255, 255), label="Darkness"),
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
            display=EffectDisplay(glyph=chr(0xE021), fg=(255, 255, 255), label="Poisoned"),
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
            display=EffectDisplay(glyph=chr(0xE023), fg=(255, 255, 255), label="Darkvision"),
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
            display=EffectDisplay(glyph=chr(0xE022), fg=(255, 255, 255), label="Burning"),
        )
        self.amount = amount  # Store the damage amount

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -= 1
        sounds.play_poison_burn_sound()
        return self.duration <= 0


class BloodyEffect(Effect):
    """Display-only status for blood coating in the effects UI."""

    def __init__(self, duration: Optional[int] = None):
        super().__init__(
            name="Bloody",
            duration=duration,
            description="Covered in blood.",
            type="status",
            display=EffectDisplay(glyph=chr(0xE021), fg=color.sprite_sheet, label="Bloody"),
        )


class WetEffect(Effect):
    """Display-only status for water coating in the effects UI."""

    def __init__(self, duration: Optional[int] = None):
        super().__init__(
            name="Wet",
            duration=duration,
            description="Soaked in water.",
            type="status",
            display=EffectDisplay(glyph=chr(0xE024), fg=color.sprite_sheet, label="Wet"),
        )


class OilyEffect(Effect):
    """Display-only status for oil coating in the effects UI."""

    def __init__(self, duration: Optional[int] = None):
        super().__init__(
            name="Oily",
            duration=duration,
            description="Covered in oil.",
            type="status",
            display=EffectDisplay(glyph="\u2022", fg=(255, 255, 255), label="Oily"),
        )


class SlimyEffect(Effect):
    """Display-only status for slime coating in the effects UI."""

    def __init__(self, duration: Optional[int] = None):
        super().__init__(
            name="Slimy",
            duration=duration,
            description="Covered in slime.",
            type="status",
            display=EffectDisplay(glyph="\u223f", fg=(255, 255, 255), label="Slimy"),
        )