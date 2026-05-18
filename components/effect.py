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

    def get_defense_multiplier(self) -> float:
        """Return a multiplier for damage mitigation based on this effect."""
        return 1.0


def has_effect_name(target, *names: str) -> bool:
    """Return True when target has any effect matching one of the provided names."""
    if target is None:
        return False
    wanted = {str(name).strip().lower() for name in names if str(name).strip()}
    if not wanted:
        return False
    for effect in getattr(target, "effects", []) or []:
        effect_name = str(getattr(effect, "name", "")).strip().lower()
        if effect_name in wanted:
            return True
    return False


def is_invisible(target) -> bool:
    """Centralized invisibility check used by AI and rendering."""
    return has_effect_name(target, "Invisible", "Invisibility")

class SaturatedEffect(Effect):
    """Marker buff granted when the player is well-fed (saturation >= 75).

    Does not manipulate passive_healing directly — the turn_manager reads
    player.saturation to decide whether boosted regen applies.  This effect
    is removed by _update_player_state when saturation falls below the
    threshold, so its duration is permanent (None) by design.
    """
    def __init__(self):
        super().__init__(
            name="Saturated",
            duration=None,
            description="Well-fed. Natural regeneration is enhanced.",
            type="Saturated",
            display=EffectDisplay(glyph=chr(0xE028), fg=(255, 255, 255), label="Saturated"),
        )

    def tick(self, target):
        return False  # Removed by _update_player_state when saturation drops


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


class HungryEffect(Effect):
    def __init__(self):
        import color as _color
        super().__init__(
            name="Hungry",
            duration=None,
            description="You're hungry.",
            type="Hungry",
            display=EffectDisplay(glyph=chr(0xE029), fg=_color.yellow, label="Hungry"),
        )

    def tick(self, target):
        return False  # Removed by StarvingEffect / SaturatedEffect, not by timer


class StarvingEffect(Effect):
    def __init__(self):
        import color as _color
        super().__init__(
            name="Starving",
            duration=None,
            description="You're starving!",
            type="Starving",
            display=EffectDisplay(glyph=chr(0xE02A), fg=_color.red, label="Starving"),
        )
        self._damage_counter: int = 0

    def tick(self, target):
        self._damage_counter += 1
        if self._damage_counter >= 10:  # Deal damage every 10 turns
            self._damage_counter = 0
            if hasattr(target, 'fighter') and target.fighter:
                target.fighter.take_damage(1, causes_bleeding=False)
        return False  # Removed by SaturatedEffect / food consumption, not by timer



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
        
## Magic effects

class SleepEffect(Effect):
    """Skip all turns until effect ends, or takes damage."""
    def __init__(self, duration: int):
        super().__init__(
            name="Sleep",
            duration=duration,
            description="Asleep. Cannot take actions until awoken.",
            type="debuff",
            display=EffectDisplay(glyph=chr(0xE02D), fg=(255, 255, 255), label="Sleep"),
        )
    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -= 1
        return self.duration <= 0

class IronskinEffect(Effect):
    """Applies x1.5 defense to target"""

    def __init__(self, duration: int, multiplier: float = 1.0):
        super().__init__(
            name="Ironskin",
            duration=duration,
            description="Your skin hardens, increasing your defense.",
            type="buff",
            display=EffectDisplay(glyph=chr(0xE02C), fg=(255, 255, 255), label="Ironskin"),
        )
        self.multiplier = multiplier

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -= 1
        return self.duration <= 0

    def get_defense_multiplier(self) -> float:
        return 2.0 * self.multiplier

class LightEffect(Effect):
    """Applied to a summoned light orb. When it expires the orb is silently
    removed from the map — no death sound, no message."""

    def __init__(self, duration: int):
        super().__init__(
            name="Illuminated",
            duration=duration,
            description="You glow brilliantly.",
            type="status",
            display=EffectDisplay(glyph=chr(0xE027), fg=(255, 255, 255), label="Illuminated"),
        )

    def tick(self, target):
        if self.duration is None:
            return False
        # Particle is now managed by engine.tick() — no per-turn spawning needed here
        self.duration -= 1
        if self.duration <= 0:
            # Only despawn summoned orb entities; non-orb targets should just lose the effect.
            try:
                target_type = str(getattr(target, "type", "") or "").strip().lower()
                target_name = str(getattr(target, "name", "") or "").strip().lower()
                is_light_orb = target_type == "orb" or target_name == "orb of light"
                if is_light_orb:
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


class InvisibilityEffect(Effect):
    def __init__(self, duration: int):
        super().__init__(
            name="Invisible",
            duration=duration,
            description="Invisible to enemies.",
            type="buff",
            display=EffectDisplay(glyph=chr(0xE02B), fg=(255, 255, 255), label="Invisible"),
        )

    def tick(self, target):
        if self.duration is None:
            return False
        self.duration -= 1
        return self.duration <= 0
    
    def get_message(self):
        if self.duration == 0:
            return ("You are visible once again.", color.green)

    

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

        return self.duration == 0
    
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
        target.fighter.take_damage(self.amount, causes_bleeding=False)
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


# ============================================================================
# DEBUG CONSOLE EFFECT REGISTRY
# ============================================================================

def get_effect_by_name(effect_name: str, duration: int = 100) -> Optional[Effect]:
    """
    Get an effect instance by name (case-insensitive).
    Used by debug console: "effect darkvision", "effect sleep", etc.
    
    Args:
        effect_name: Name of the effect (e.g., "darkvision", "sleep", "poison")
        duration: How long the effect lasts (in turns). Ignored for permanent effects.
    
    Returns:
        An Effect instance or None if not found.
    """
    name = effect_name.strip().lower()
    
    # Map effect names to their constructors with default parameters
    registry = {
        "sleep": lambda d: SleepEffect(duration=d),
        "darkvision": lambda d: DarkvisionEffect(duration=d),
        "invisibility": lambda d: InvisibilityEffect(duration=d),
        "invisible": lambda d: InvisibilityEffect(duration=d),
        "ironskin": lambda d: IronskinEffect(duration=d),
        "burning": lambda d: BurningEffect(amount=3, duration=d),
        "poison": lambda d: PoisonEffect(amount=2, duration=d),
        "poisoned": lambda d: PoisonEffect(amount=2, duration=d),
        "tired": lambda d: TiredEffect(duration=d),
        "darkness": lambda d: Darkness(duration=d),
        "healing": lambda d: HealingEffect(total_amount=50, duration=d),
        "saturated": lambda d: SaturatedEffect(),
        "hungry": lambda d: HungryEffect(),
        "starving": lambda d: StarvingEffect(),
        "wet": lambda d: WetEffect(duration=d),
        "oily": lambda d: OilyEffect(duration=d),
        "slimy": lambda d: SlimyEffect(duration=d),
        "bloody": lambda d: BloodyEffect(duration=d),
        "light": lambda d: LightEffect(duration=d),
    }
    
    if name in registry:
        return registry[name](duration)
    
    return None


def list_available_effects() -> list[str]:
    """Return a list of all available effect names for debug console."""
    return sorted([
        "sleep", "darkvision", "invisibility", "ironskin", "burning", "poison",
        "tired", "darkness", "healing", "saturated", "hungry", "starving",
        "wet", "oily", "slimy", "bloody", "light"
    ])