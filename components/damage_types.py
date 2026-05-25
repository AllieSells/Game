from enum import Enum

class DamageType(Enum):
    """Central handler for damage types"""
    # Physical traits
    SLASHING = "slashing"
    PIERCING = "piercing"
    BLUDGEONING = "bludgeoning"
    PHYSICAL = "physical"

    # Elemental
    FIRE = "fire"
    POISON = "poison"

    # Magical
    NECROTIC = "necrotic"
    PSYCHIC = "psychic"


    # None fallback
    NONE = "none"