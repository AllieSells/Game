from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Set

from components.base_component import BaseComponent
from equipment_types import EquipmentType
import proficiency_system as profsys
from balance_config import ARROW_BASE_POWER, BOW_BASE_HIT_CHANCE, BOW_DEFAULT_MAX_RANGE

if TYPE_CHECKING:
    from entity import Actor, Item
    from components.effect import Effect


class Equippable(BaseComponent):
    parent: Item

    def __init__(
        self,
        equipment_type: EquipmentType,
        power_bonus: int = 0,
        defense_bonus: int = 0,
        required_tags: Set[str] | None = None,
        equip_all_matching: bool = True,  # True = cover all matching parts, False = use only one
        base_hit_chance: float | None = None,  # Overrides entity base_hit_chance when set
        mana_regen: float = 0, # Mana regen ratio (additive)
        effect: Effect | None = None,
        effect_cooldown: int = 0,
        effect_duration: int | None = None,
    ):
        self.equipment_type = equipment_type
        self.power_bonus = power_bonus
        self.defense_bonus = defense_bonus
        self.required_tags = required_tags or set()  # Tags that body parts must have to equip this item
        self.equip_all_matching = equip_all_matching  # Whether to equip to all matching parts or just one
        self.base_hit_chance = base_hit_chance  # None = use the attacking entity's base_hit_chance
        self.mana_regen = mana_regen
        self.effect = effect
        self.effect_cooldown = max(0, int(effect_cooldown or 0))
        self.effect_duration = effect_duration


    def apply_effect(self, target: Actor) -> None:
        """Apply this item's effect to target if configured and off cooldown."""
        if not self.effect or target is None:
            return

        # Cooldown is tracked per item instance so two rings can cooldown independently.
        item = getattr(self, "parent", None)
        if item is None:
            return

        remaining = int(getattr(item, "effect_cooldown_remaining", 0) or 0)
        if remaining > 0:
            item.effect_cooldown_remaining = remaining - 1
            return

        effect_instance = self._build_effect_instance()
        if effect_instance is None:
            return

        target_effects = getattr(target, "effects", None)
        if target_effects is None:
            target_effects = []
            setattr(target, "effects", target_effects)

        engine = getattr(getattr(target, "gamemap", None), "engine", None)
        if engine and hasattr(engine, "add_or_refresh_effect"):
            engine.add_or_refresh_effect(target, effect_instance)
        else:
            # Fallback refresh path when engine helper is unavailable.
            refreshed = False
            effect_name = str(getattr(effect_instance, "name", "")).strip().lower()
            for existing in target_effects:
                if str(getattr(existing, "name", "")).strip().lower() == effect_name:
                    if getattr(existing, "duration", None) is None or getattr(effect_instance, "duration", None) is None:
                        existing.duration = None
                    else:
                        existing.duration = max(existing.duration, effect_instance.duration)
                    refreshed = True
                    break
            if not refreshed:
                target_effects.append(effect_instance)

        if self.effect_cooldown > 0:
            # Set cooldown to include both the effect duration and the actual cooldown period
            # so there's a gap after the effect expires before reapplication
            effect_duration = int(getattr(effect_instance, "duration", 0) or 0)
            item.effect_cooldown_remaining = self.effect_cooldown + effect_duration

    def _build_effect_instance(self):
        """Return a fresh effect instance from configured effect template/class/callable."""
        effect_source = self.effect
        if effect_source is None:
            return None

        # Delay import to avoid runtime circulars and keep TYPE_CHECKING-only import clean.
        from components.effect import Effect as RuntimeEffect

        if isinstance(effect_source, RuntimeEffect):
            return copy.deepcopy(effect_source)

        if isinstance(effect_source, type):
            try:
                if self.effect_duration is not None:
                    return effect_source(self.effect_duration)
                return effect_source()
            except TypeError:
                return None

        if callable(effect_source):
            try:
                return effect_source()
            except Exception:
                return None

        return None

    def get_defense(self, actor: Actor | None = None) -> int:
        """Calculate total defense provided by this item for a given wearer."""
        wearers = actor or getattr(self.engine, "player", None)

        if wearers is None:
            return self.defense_bonus

        try:
            item_tags = set(getattr(self.parent, "tags", []) or [])
            armor_profile = profsys.armor_profile(wearers, item_tags)
            return int(round(self.defense_bonus * armor_profile.defense_bonus_multiplier))
        except Exception:
            return self.defense_bonus
class Arrow(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.PROJECTILE, power_bonus=ARROW_BASE_POWER, required_tags={"hand", "grasp"})

class SteelArrow(Arrow):
    def __init__(self) -> None:
        super().__init__()
        self.power_bonus = ARROW_BASE_POWER * 2

class Bow(Equippable):
    def __init__(self) -> None:
        super().__init__(
            equipment_type=EquipmentType.RANGED,
            power_bonus=0,
            required_tags={"hand", "grasp"},
            base_hit_chance=BOW_BASE_HIT_CHANCE,
        )
        self.max_range = BOW_DEFAULT_MAX_RANGE

class Dagger(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=2, required_tags={"hand", "grasp"}, equip_all_matching=False)

class MythrilDagger(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=6, required_tags={"hand", "grasp"}, equip_all_matching=False)

class Shortsword(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=4, required_tags={"hand", "grasp"}, equip_all_matching=False)

class Longsword(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=6, required_tags={"hand", "grasp"}, equip_all_matching=True)

# Leather

class LeatherCap(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.HELMET, defense_bonus=1, required_tags={"head", "neck"}, equip_all_matching=True)

class LeatherLeggings(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.LEGGINGS, defense_bonus=1, required_tags={"leg"}, equip_all_matching=True)

class LeatherBoot(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BOOTS, defense_bonus=1, required_tags={"foot"}, equip_all_matching=True)

class LeatherArmor(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=1, required_tags={"torso"}, equip_all_matching=True)


# Chain mail

class ChainMailHelmet(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.HELMET, defense_bonus=3, required_tags={"head", "neck"})
        
class ChainMailArmor(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=5, required_tags={"torso"})

class ChainMailLeggings(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.LEGGINGS, defense_bonus=3, required_tags={"leg"})

# Plate

class PlateHelmet(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.HELMET, defense_bonus=6, required_tags={"head", "neck"})

class PlateArmor(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=10, required_tags={"torso"})

class ApprenticeRobe(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=1, required_tags={"torso"}, equip_all_matching=True, mana_regen=0.1)

class ScholarRobe(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=2, required_tags={"torso"}, equip_all_matching=True, mana_regen=0.15)

class MasterRobe(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=3, required_tags={"torso"}, equip_all_matching=True, mana_regen=0.2)


class devtool(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=1000, required_tags={"hand", "grasp"})

class Torch(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=0, required_tags={"hand", "hold", "use"}, equip_all_matching=False)

class Shield(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.SHIELD, defense_bonus=2, required_tags={"hand", "grasp"})

class Helmet(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.HELMET, defense_bonus=1, required_tags={"head", "neck"})

class Boots(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BOOTS, defense_bonus=1, required_tags={"foot"})

class Gauntlets(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.GAUNTLETS, defense_bonus=1, required_tags={"arm"})

class Leggings(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.LEGGINGS, defense_bonus=1, required_tags={"leg"})

class Backpack(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BACKPACK, power_bonus=0, required_tags={"torso", "back"})


class Quiver(Equippable):
    def __init__(self) -> None:
        # Uses BACKPACK slot category; treated as a non-covering back item by equipment logic.
        super().__init__(equipment_type=EquipmentType.BACKPACK, power_bonus=0, required_tags={"torso"})

class Ring(Equippable):
    def __init__(
        self,
        effect: Effect | type[Effect] | None = None,
        effect_cooldown: int = 0,
        effect_duration: int | None = None,
    ) -> None:
        # Rings are a special case: no body-part requirements and up to 2 equipped.
        super().__init__(
            equipment_type=EquipmentType.RING,
            power_bonus=0,
            required_tags=set(),
            equip_all_matching=False,
            effect=effect,
            effect_cooldown=effect_cooldown,
            effect_duration=effect_duration,
        )

class RoundShield(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.SHIELD, defense_bonus=3, required_tags={"hand", "grasp"}, equip_all_matching=False)