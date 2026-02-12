from enum import auto, Enum

class EquipmentType(Enum):
    """Equipment item categories used by the inventory system."""
    WEAPON = auto()
    SHIELD = auto()
    HELMET = auto()
    ARMOR = auto()
    LEGGINGS = auto()
    BOOTS = auto()
    GAUNTLETS = auto()
    GORGET = auto()
    BACKPACK = auto()