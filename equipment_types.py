from enum import auto, Enum
from typing import Set, Optional
from dataclasses import dataclass

@dataclass
class EquipmentRequirement:
    """Defines what body parts or capabilities an item needs to be equipped."""
    required_capabilities: Set[str] = None  # General capabilities like "can_grasp"
    covers_body_parts: Set[str] = None  # Body part types this equipment protects/covers
    exclusive_coverage: bool = True  # Whether only one item can cover these parts
    
    def __post_init__(self):
        if self.required_capabilities is None:
            self.required_capabilities = set()
        if self.covers_body_parts is None:
            self.covers_body_parts = set()

class EquipmentType(Enum):
    # Weapons - require any grasping capability
    WEAPON = EquipmentRequirement(
        required_capabilities={"can_grasp"}
    )
    
    # Shields/items - also require grasping capability  
    SHIELD = EquipmentRequirement(
        required_capabilities={"can_grasp"}
    )
    
    # Head protection - covers any head
    HELMET = EquipmentRequirement(
        covers_body_parts={"HEAD"}
    )
    
    # Body armor - covers torso
    ARMOR = EquipmentRequirement(
        covers_body_parts={"TORSO"}
    )
    
    # Leg protection - covers legs
    LEGGINGS = EquipmentRequirement(
        covers_body_parts={"LEFT_LEG", "RIGHT_LEG"},
        exclusive_coverage=False  # Can have separate leg armor per leg
    )
    
    # Foot protection - covers feet  
    BOOTS = EquipmentRequirement(
        covers_body_parts={"LEFT_FOOT", "RIGHT_FOOT"},
        exclusive_coverage=False  # Can have separate boots per foot
    )
    
    # Arm protection - covers arms
    GAUNTLETS = EquipmentRequirement(
        covers_body_parts={"LEFT_ARM", "RIGHT_ARM", "LEFT_HAND", "RIGHT_HAND"},
        exclusive_coverage=False  # Can have separate gauntlets per arm
    )
    
    # Neck protection - covers neck
    GORGET = EquipmentRequirement(
        covers_body_parts={"NECK"}
    )
    
    # Backpack - worn but doesn't require specific body parts to function
    BACKPACK = EquipmentRequirement(
        required_capabilities=set(),  # Just needs to be wearable
        covers_body_parts=set()
    )