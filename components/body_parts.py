"""
Body Parts System

A modular system for tracking body parts on entities.
Supports different anatomy types, injury tracking, and body part-specific effects.
"""

from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, TYPE_CHECKING
from components.base_component import BaseComponent
from entity import T
from liquid_system import LiquidType
import random

if TYPE_CHECKING:
    from entity import Actor

# Import hit difficulty modifiers from actions module
# Avoid circular import by importing at function level
def _get_body_part_modifiers():
    from actions import BODY_PART_MODIFIERS
    return BODY_PART_MODIFIERS


class BodyPartType(Enum):
    """Types of body parts."""
    # Core parts
    HEAD = auto()
    NECK = auto()
    TORSO = auto()
    
    # Arms
    LEFT_ARM = auto()
    RIGHT_ARM = auto()
    LEFT_HAND = auto()
    RIGHT_HAND = auto()
    
    # Legs  
    LEFT_LEG = auto()
    RIGHT_LEG = auto()
    LEFT_FOOT = auto()
    RIGHT_FOOT = auto()

    # Other legs
    FRONT_LEFT_LEG = auto()
    FRONT_RIGHT_LEG = auto()
    SECOND_LEFT_LEG = auto()
    SECOND_RIGHT_LEG = auto()
    THIRD_LEFT_LEG = auto()
    THIRD_RIGHT_LEG = auto()
    BACK_LEFT_LEG = auto()
    BACK_RIGHT_LEG = auto()
    
    # Animal-specific
    TAIL = auto()
    WINGS = auto()
    
    # Insect-specific
    THORAX = auto()
    ABDOMEN = auto()
    ANTENNA = auto()
    MANDIBLES = auto()


class AnatomyType(Enum):
    """Different creature anatomy layouts."""
    HUMANOID = auto()
    QUADRUPED = auto()
    INSECT = auto()
    ARACHNID = auto()
    BIRD = auto()
    SIMPLE = auto()  # Basic creatures


@dataclass
class BodyPart:
    """Represents a single body part."""
    part_type: BodyPartType
    name: str
    max_hp_ratio: float  # Relative HP compared to total entity HP
    max_hp: int = 0  # Calculated max HP for this part
    current_hp: int = None
    is_vital: bool = False  # Death if destroyed
    is_limb: bool = False   # Can be severed/disabled
    can_grasp: bool = False  # Can equip weapons/shields
    protection: int = 0     # Natural armor
    tags: Set[str] = field(default_factory=set)  # Equipment tags this part can accommodate (e.g., "hand", "grasp", "manipulate")
    status_effects: Set[str] = field(default_factory=set)
    coating = LiquidType.NONE  # Type of liquid coating this part has (e.g., blood, slime, oil)
    coating_age: int = 0  # Age of the coating for evaporation tracking
    
    def __post_init__(self):
        if self.current_hp is None:
            self.current_hp = self.max_hp
    @property
    def is_destroyed(self) -> bool:
        """Check if body part is completely destroyed."""
        return self.current_hp <= 0
    
    @property
    def is_damaged(self) -> bool:
        """Check if body part has taken any damage."""
        return self.current_hp < self.max_hp
    
    @property
    def damage_level_float(self) -> float:
        """Get damage level as a float (0.0 = no damage, 1.0 = destroyed)."""
        if self.max_hp <= 0:
            return 1.0
        return 1.0 - (self.current_hp / self.max_hp)
    @property
    def damage_level_text(self) -> str:
        """Get description of damage level."""
        if not self.is_damaged:
            return "healthy"
        
        damage_ratio = self.current_hp / self.max_hp
        if damage_ratio > 0.75:
            return "damaged"
        elif damage_ratio > 0.5:
            return "wounded"
        elif damage_ratio > 0.25:
            return "badly wounded"
        elif damage_ratio > 0:
            return "severely wounded"
        else:
            return "destroyed"
    
    def take_damage(self, amount: int) -> int:
        """Deal damage to this body part. Returns actual damage dealt."""
        actual_damage = min(amount, self.current_hp)
        self.current_hp -= actual_damage
        return actual_damage
    
    def heal(self, amount: int) -> int:
        """Heal this body part. Returns actual healing done."""
        actual_healing = min(amount, self.max_hp - self.current_hp)
        self.current_hp += actual_healing
        return actual_healing


class BodyParts(BaseComponent):
    """Component for managing entity body parts."""
    
    parent: Actor
    
    def __init__(self, anatomy_type: AnatomyType = AnatomyType.HUMANOID, max_hp: int = 100):
        self.anatomy_type = anatomy_type
        self.max_hp = max_hp  # Store parent's max HP for calculating body part HP
        self.body_parts: Dict[BodyPartType, BodyPart] = {}
        self.vital_parts_destroyed = 0
        
        # Initialize body parts based on anatomy type
        self._initialize_anatomy(anatomy_type)
    
    def _initialize_anatomy(self, anatomy_type: AnatomyType) -> None:
        """Initialize body parts based on anatomy type."""
        if anatomy_type == AnatomyType.HUMANOID:
            self._create_humanoid_anatomy()
        elif anatomy_type == AnatomyType.ARACHNID:
            self._create_arachnid_anatomy()
        else:  # SIMPLE
            self._create_simple_anatomy()

    def _create_arachnid_anatomy(self) -> None:
        """Create arachnid body parts (spiders, scorpions, etc.)."""
        parent_max_hp = self.max_hp
        
        self.body_parts = {
            BodyPartType.THORAX: BodyPart(
                BodyPartType.THORAX, "thorax", 1.0, max_hp=parent_max_hp, is_vital=True,
                tags={"thorax", "armor"}
            ),
            BodyPartType.FRONT_LEFT_LEG: BodyPart(
                BodyPartType.FRONT_LEFT_LEG, "front left leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "left", "front_left_leg"}
            ),
            BodyPartType.FRONT_RIGHT_LEG: BodyPart(
                BodyPartType.FRONT_RIGHT_LEG, "front right leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "right", "front_right_leg"}
            ),
            BodyPartType.SECOND_LEFT_LEG: BodyPart(
                BodyPartType.SECOND_LEFT_LEG, "second left leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "left", "second_left_leg"}
            ),
            BodyPartType.SECOND_RIGHT_LEG: BodyPart(
                BodyPartType.SECOND_RIGHT_LEG, "second right leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "right", "second_right_leg"}
            ),
            BodyPartType.THIRD_LEFT_LEG: BodyPart(
                BodyPartType.THIRD_LEFT_LEG, "third left leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "left", "third_left_leg"}
            ),
            BodyPartType.THIRD_RIGHT_LEG: BodyPart(
                BodyPartType.THIRD_RIGHT_LEG, "third right leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "right", "third_right_leg"}
            ),
            BodyPartType.BACK_LEFT_LEG: BodyPart(
                BodyPartType.BACK_LEFT_LEG, "back left leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "left", "back_left_leg"}
            ),
            BodyPartType.BACK_RIGHT_LEG: BodyPart(
                BodyPartType.BACK_RIGHT_LEG, "back right leg", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "right", "back_right_leg"}
            ),
            BodyPartType.ABDOMEN: BodyPart(
                BodyPartType.ABDOMEN, "abdomen", .5, max_hp=int(0.5 * parent_max_hp), is_vital=True,
                tags={"abdomen", "armor"}
            )
        }
    
    
    def _create_humanoid_anatomy(self) -> None:
        """Create humanoid body parts (humans, elves, orcs, etc.)."""
        # Use the max_hp passed in during initialization
        parent_max_hp = self.max_hp
        
        self.body_parts = {
            BodyPartType.HEAD: BodyPart(
                BodyPartType.HEAD, "head", .5, max_hp=int(0.5 * parent_max_hp), is_vital=True,
                tags={"head", "armor", "cranium"}
            ),
            BodyPartType.NECK: BodyPart(
                BodyPartType.NECK, "neck", .267, max_hp=int(0.267 * parent_max_hp), is_vital=True,
                tags={"neck", "armor", "cranium"}
            ),
            BodyPartType.TORSO: BodyPart(
                BodyPartType.TORSO, "torso", 1.0, max_hp=int(1.0 * parent_max_hp), is_vital=True,
                tags={"torso", "armor", "core"}
            ),
            BodyPartType.LEFT_ARM: BodyPart(
                BodyPartType.LEFT_ARM, "left arm", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"arm", "armor", "left", "left_arm", "upper_limbs"}
            ),
            BodyPartType.RIGHT_ARM: BodyPart(
                BodyPartType.RIGHT_ARM, "right arm", .4, max_hp=int(0.4 * parent_max_hp), is_limb=True,
                tags={"arm", "armor", "right", "right_arm", "upper_limbs"}
            ),
            BodyPartType.LEFT_HAND: BodyPart(
                BodyPartType.LEFT_HAND, "left hand", .167, max_hp=int(0.167 * parent_max_hp), is_limb=True, can_grasp=True,
                tags={"hand", "grasp", "manipulate", "hold", "use", "left", "left_hand", "upper_limbs"}
            ),
            BodyPartType.RIGHT_HAND: BodyPart(
                BodyPartType.RIGHT_HAND, "right hand", .167, max_hp=int(0.167 * parent_max_hp), is_limb=True, can_grasp=True,
                tags={"hand", "grasp", "manipulate", "hold", "use", "right", "right_hand", "upper_limbs"}
            ),
            BodyPartType.LEFT_LEG: BodyPart(
                BodyPartType.LEFT_LEG, "left leg", .5, max_hp=int(0.5 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "left", "left_leg", "lower_limbs"}
            ),
            BodyPartType.RIGHT_LEG: BodyPart(
                BodyPartType.RIGHT_LEG, "right leg", .5, max_hp=int(0.5 * parent_max_hp), is_limb=True,
                tags={"leg", "locomotion", "right", "right_leg", "lower_limbs"}
            ),
            BodyPartType.LEFT_FOOT: BodyPart(
                BodyPartType.LEFT_FOOT, "left foot", .2, max_hp=int(0.2 * parent_max_hp), is_limb=True,
                tags={"foot", "locomotion", "armor", "left", "left_foot", "lower_limbs"}
            ),
            BodyPartType.RIGHT_FOOT: BodyPart(
                BodyPartType.RIGHT_FOOT, "right foot", .2, max_hp=int(0.2 * parent_max_hp), is_limb=True,
                tags={"foot", "locomotion", "armor", "right", "right_foot", "lower_limbs"}
            ),
        }
    
    def _create_simple_anatomy(self) -> None:
        """Create simple anatomy (slimes, golems, etc.)."""
        parent_max_hp = self.max_hp
        
        self.body_parts = {
            BodyPartType.TORSO: BodyPart(
                BodyPartType.TORSO, "body", 1.0, max_hp=parent_max_hp, is_vital=True, protection=1,
                tags={"torso", "armor"}
            ),
        }
    
    def get_all_parts(self) -> Dict[BodyPartType, BodyPart]:
        """Get all body parts."""
        return self.body_parts.copy()
    
    def get_part(self, part_type: BodyPartType) -> Optional[BodyPart]:
        """Get specific body part."""
        return self.body_parts.get(part_type)
    
    def get_vital_parts(self) -> List[BodyPart]:
        """Get all vital body parts."""
        return [part for part in self.body_parts.values() if part.is_vital]
    
    def get_limbs(self) -> List[BodyPart]:
        """Get all limbs."""
        return [part for part in self.body_parts.values() if part.is_limb]
    
    def get_weapon_hands(self) -> List[BodyPart]:
        """Get body parts that can hold weapons."""
        return [part for part in self.body_parts.values() 
                if part.can_hold_items and not part.is_destroyed]
    
    def get_damaged_parts(self) -> List[BodyPart]:
        """Get all damaged body parts."""
        return [part for part in self.body_parts.values() if part.is_damaged]
    
    def get_destroyed_parts(self) -> List[BodyPart]:
        """Get all destroyed body parts."""
        return [part for part in self.body_parts.values() if part.is_destroyed]
    
    def get_random_part(self) -> Optional[BodyPart]:
        """Get a random body part."""
        if not self.body_parts:
            return None
        return random.choice(list(self.body_parts.values()))
    
    def get_part_health_ratio(self, part: BodyPart) -> float:
        """Get a body part's current health as a decimal ratio (0.0 to 1.0)."""
        if part.max_hp <= 0:
            return 0.0
        return part.current_hp / part.max_hp
    
    def damage_random_part(self, damage: int) -> Optional[BodyPart]:
        """Damage a random body part. Returns the damaged part."""
        available_parts = [part for part in self.body_parts.values() 
                         if not part.is_destroyed]
        
        if not available_parts:
            return None
        
        # Use hit difficulty modifiers from BODY_PART_MODIFIERS to calculate weights
        # Higher modifier = easier to hit = higher weight
        modifiers = _get_body_part_modifiers()
        weights = []
        for part in available_parts:
            part_type_name = part.part_type.name
            # Look up hit difficulty in BODY_PART_MODIFIERS
            hit_difficulty = 0
            if part_type_name in modifiers:
                hit_difficulty = modifiers[part_type_name][1]
            else:
                # Check for partial matches
                for key in modifiers:
                    if key in part_type_name:
                        hit_difficulty = modifiers[key][1]
                        break
            # Convert to weight: base 100 + modifier (so TORSO=115, HEAD=70, etc.)
            weights.append(max(1, 100 + hit_difficulty))
        
        damaged_part = random.choices(available_parts, weights=weights)[0]
        actual_damage = damaged_part.take_damage(damage)
        
        return damaged_part if actual_damage > 0 else None
    
    def damage_specific_part(self, part_type: BodyPartType, damage: int) -> Optional[BodyPart]:
        """Damage a specific body part. Returns the damaged part."""
        part = self.get_part(part_type)
        if part and not part.is_destroyed:
            actual_damage = part.take_damage(damage)
            return part if actual_damage > 0 else None
        return None
    
    def is_alive(self) -> bool:
        """Check if entity is still alive (no vital parts destroyed)."""
        vital_parts = self.get_vital_parts()
        return all(not part.is_destroyed for part in vital_parts)
    
    def can_move(self) -> bool:
        """Check if entity can move (has working legs/locomotion)."""
        if self.anatomy_type == AnatomyType.SIMPLE:
            return not self.body_parts[BodyPartType.TORSO].is_destroyed
        
        # Check if at least one leg is functional
        legs = [part for part_type, part in self.body_parts.items() 
                if part_type in [BodyPartType.LEFT_LEG, BodyPartType.RIGHT_LEG, 
                               BodyPartType.LEFT_FOOT, BodyPartType.RIGHT_FOOT,
                               BodyPartType.FRONT_LEFT_LEG, BodyPartType.FRONT_RIGHT_LEG,
                               BodyPartType.SECOND_LEFT_LEG, BodyPartType.SECOND_RIGHT_LEG,
                               BodyPartType.THIRD_LEFT_LEG, BodyPartType.THIRD_RIGHT_LEG,
                               BodyPartType.BACK_LEFT_LEG, BodyPartType.BACK_RIGHT_LEG]
                and not part.is_destroyed]
        
        return len(legs) > 0
    
    def can_use_hands(self) -> bool:
        """Check if entity has functional hands/weapon grips."""
        hands = self.get_weapon_hands()
        return len(hands) > 0
    

    
    def get_movement_penalty(self) -> float:
        """Get movement speed penalty based on leg damage (0.0 = no penalty, 1.0 = can't move)."""
        if self.anatomy_type == AnatomyType.SIMPLE:
            torso = self.body_parts.get(BodyPartType.TORSO)
            if torso:
                return 1.0 - (torso.current_hp / torso.max_hp)
            return 0.0
        
        leg_parts = [
            BodyPartType.LEFT_LEG, BodyPartType.RIGHT_LEG,
            BodyPartType.LEFT_FOOT, BodyPartType.RIGHT_FOOT,
            BodyPartType.FRONT_LEFT_LEG, BodyPartType.FRONT_RIGHT_LEG,
            BodyPartType.SECOND_LEFT_LEG, BodyPartType.SECOND_RIGHT_LEG,
            BodyPartType.THIRD_LEFT_LEG, BodyPartType.THIRD_RIGHT_LEG,
            BodyPartType.BACK_LEFT_LEG, BodyPartType.BACK_RIGHT_LEG
        ]
        
        total_legs = 0
        functional_legs = 0
        
        for part_type in leg_parts:
            part = self.get_part(part_type)
            if part:
                total_legs += 1
                if not part.is_destroyed:
                    functional_legs += 1
        
        if total_legs == 0:
            return 0.0
        
        leg_ratio = functional_legs / total_legs
        return 1.0 - leg_ratio
    
    def get_manipulation_penalty(self) -> float:
        """Get manipulation penalty based on hand/arm damage (0.0 = no penalty, 1.0 = can't manipulate)."""
        if self.anatomy_type == AnatomyType.SIMPLE:
            return 0.0  # Simple creatures don't have manipulation limbs
        
        hand_parts = [
            BodyPartType.LEFT_HAND, BodyPartType.RIGHT_HAND,
            BodyPartType.LEFT_ARM, BodyPartType.RIGHT_ARM
        ]
        
        total_hands = 0
        functional_hands = 0
        
        for part_type in hand_parts:
            part = self.get_part(part_type)
            if part:
                total_hands += 1
                if not part.is_destroyed:
                    functional_hands += 1
        
        if total_hands == 0:
            return 0.0
        
        hand_ratio = functional_hands / total_hands
        return 1.0 - hand_ratio
    
    def heal_all_parts(self, amount: int) -> int:
        """Heal all body parts equally. Returns total healing done."""
        total_healing = 0
        for part in self.body_parts.values():
            total_healing += part.heal(amount)
        return total_healing
    
    def set_max_health(self, new_max_hp: int) -> None:
        """Set new max health and redistribute to body parts based on existing health ratios."""
        self.max_hp = new_max_hp
        
        for part in self.body_parts.values():
            # Preserve current health percentage
            health_ratio = part.current_hp / part.max_hp if part.max_hp > 0 else 1.0
            
            # Update max HP based on part's proportion of total health
            part.max_hp = int(part.max_hp_ratio * new_max_hp)
            
            # Maintain same health percentage, but don't exceed new max
            part.current_hp = min(int(part.max_hp * health_ratio), part.max_hp)
    
    def get_status_description(self) -> List[str]:
        """Get detailed status of all body parts."""
        descriptions = []
        
        for part in self.body_parts.values():
            status_parts = []
            
            # Add damage status
            if part.is_destroyed:
                status_parts.append("destroyed")
            elif part.is_damaged:
                status_parts.append(part.damage_level_text)
                
            # Add coating status
            if part.coating != LiquidType.NONE:
                coating_name = part.coating.get_display_name()
                status_parts.append(f"coated in {coating_name}")
            
            # Build description
            if status_parts:
                descriptions.append(f"{part.name}: {', '.join(status_parts)}")
            elif part.coating == LiquidType.NONE and not part.is_damaged:
                # Only show healthy parts if they're not coated and not damaged
                continue
        
        if not descriptions:
            descriptions.append("All body parts are healthy.")
        
        return descriptions
    
    def can_equip_item(self, required_tags: Set[str]) -> bool:
        """Check if any body part has all required tags to equip an item."""
        for part in self.body_parts.values():
            if not part.is_destroyed and required_tags.issubset(part.tags):
                return True
        return False
    
    def get_parts_matching_tags(self, required_tags: Set[str]) -> List[BodyPart]:
        """Get all undestroyed body parts that have all required tags."""
        matching = []
        for part in self.body_parts.values():
            if not part.is_destroyed and required_tags.issubset(part.tags):
                matching.append(part)
        return matching