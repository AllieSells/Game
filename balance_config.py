"""Centralized gameplay balance constants.

Use this file to tune character progression and combat without chasing magic
numbers across multiple systems.
"""

from __future__ import annotations

# Trait baseline used across chargen and progression.
BASE_TRAIT_LEVEL = 1

# Character creation / starting pool balance.
STARTING_MANA_BASE = 18
STARTING_MANA_PER_ARCANA_LEVEL = 6 

# Level-up gains.
VIGOR_HP_PER_LEVEL = 10
ARCANA_MANA_PER_LEVEL = 10

# Passive regeneration.
MANA_REGEN_CHANCE = 0.1
MANA_REGEN_FRACTION = 0.03

# Core hit chances.
MELEE_BASE_HIT = 0.6
RANGED_BASE_HIT = 0.5
MIN_HIT_CHANCE = 0.60
MAX_HIT_CHANCE = 0.95

# Accuracy scaling from agility differences.
AGILITY_HIT_BONUS_PER_LEVEL = 0.1
AGILITY_HIT_BONUS_CAP = 0.5

# Damage scaling from traits.
STRENGTH_MELEE_DAMAGE_PER_LEVEL = 0.10
AGILITY_RANGED_DAMAGE_PER_LEVEL = 0.1

# Archery tuning levers.
# Keep these centralized so ranged feel can be adjusted without touching combat logic.
ARROW_BASE_POWER = 6
BOW_BASE_HIT_CHANCE = 0.5
BOW_DEFAULT_MAX_RANGE = 8
ARROW_OBSTACLE_BREAK_CHANCE = 0.2
ARROW_HIT_RECOVERY_CHANCE = 0.8
CHEST_ARROW_BUNDLE_SIZE = 6

# Armor mitigation from affinity traits.
ARMOR_AFFINITY_MITIGATION_PER_LEVEL = 0.05
ARMOR_AFFINITY_MITIGATION_CAP = 0.66

# Equipment defense proficiency scaling.
ARMOR_DEFENSE_SKILL_PER_LEVEL = 0.25

# Proficiency multiplier clamping.
# All weapon/armor/spell skill multipliers are clamped to [0.55, 1.0].
PROFICIENCY_MULTIPLIER_MIN = 0.55
PROFICIENCY_MULTIPLIER_MAX = 5.0

# Weapon skill scaling.
# Level 1 is intentionally weak; skill level raises both hit and damage.
WEAPON_SKILL_BASE_ACCURACY = 0.33
WEAPON_SKILL_BASE_DAMAGE = 0.5
WEAPON_SKILL_ACCURACY_PER_LEVEL = 0.25
WEAPON_SKILL_DAMAGE_PER_LEVEL = 0.2

# Armor skill scaling.
# Low skill reduces effective defense from equipped armor pieces.
ARMOR_SKILL_BASE_DEFENSE = 0.72
ARMOR_SKILL_DEFENSE_PER_LEVEL = 0.10

# Shield block skill scaling.
SHIELD_BLOCK_BASE_CHANCE = 0.15
SHIELD_BLOCK_CHANCE_PER_LEVEL = 0.15
SHIELD_BLOCK_MAX_CHANCE = 0.85

# Tag-to-skill registry used by combat and XP hooks.
# Keep this data-driven so adding a new weapon/armor family only requires a new rule.
WEAPON_TAG_TRAIT_RULES = {
    "blade": (("blades", 1.00),),
    "sword": (("swords", 1.00), ("blades", 0.35)),
    "shortsword": (("swords", 1.00), ("blades", 0.35)),
    "longsword": (("swords", 1.00), ("blades", 0.35)),
    "dagger": (("daggers", 1.00), ("blades", 0.45)),
    "bow": (("agility", 1.00),),
    "ranged": (("agility", 0.75),),
    "weapon": (("blades", 0.60), ("strength", 0.40)),
    "light weapon": (("daggers", 0.60), ("agility", 0.45)),
    "heavy weapon": (("swords", 0.60), ("strength", 0.55)),
}

ARMOR_TAG_TRAIT_RULES = {
    "armor": (("armor", 1.00),),
    "shield": (("shields", 1.00), ("armor", 0.45)),
    "shields": (("shields", 1.00), ("armor", 0.45)),
    "light armor": (("light armor", 1.00), ("armor", 0.55)),
    "medium armor": (("medium armor", 1.00), ("armor", 0.55)),
    "heavy armor": (("heavy armor", 1.00), ("armor", 0.55)),
    "leather": (("light armor", 0.75), ("armor", 0.45)),
    "chain mail": (("medium armor", 0.75), ("armor", 0.45)),
}

# Spell school proficiency scaling.
SPELL_BASE_SUCCESS_CHANCE = 0.2
SPELL_SUCCESS_BONUS_PER_LEVEL = 0.2
SPELL_MIN_SUCCESS_CHANCE = 0.35
SPELL_MAX_SUCCESS_CHANCE = 0.99

# Mana cost on spell fizzle.
SPELL_FIZZLE_MANA_REFUND_FRACTION = -1.5 

# Dodge scaling.
AGILITY_DODGE_BONUS_PER_LEVEL = 0.015
ARMOR_DODGE_BONUS_PER_LEVEL = 0.01
LIGHT_ARMOR_DODGE_PENALTY = 0.00
MEDIUM_ARMOR_DODGE_PENALTY = 0.03
HEAVY_ARMOR_DODGE_PENALTY = 0.07


def trait_delta(level: int, base: int = BASE_TRAIT_LEVEL) -> int:
    """Return trait levels above baseline, clamped at 0 for below-baseline levels."""
    try:
        return max(0, int(level) - int(base))
    except Exception:
        return 0
