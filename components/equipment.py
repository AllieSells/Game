from __future__ import annotations

from typing import Optional, TYPE_CHECKING, Dict, Set

from components.base_component import BaseComponent
from equipment_types import EquipmentType
import color

if TYPE_CHECKING:
    from entity import Actor, Item
    from components.body_parts import BodyPartType

import sounds


class Equipment(BaseComponent):
    parent: Actor

    def __init__(self):
        # Modern modular equipment tracking
        self.equipped_items: Dict[str, Item] = {}  # Maps equipment categories to items
        self.body_part_coverage: Dict[str, Item] = {}  # Maps covered body parts to covering items
        self.grasped_items: Dict[str, Item] = {}  # Maps specific body part names to grasped items

    @property
    def defense_bonus(self) -> int:
        bonus = 0

        # Calculate defense from all equipped items
        for item in self.equipped_items.values():
            if item.equippable is not None:
                bonus += item.equippable.defense_bonus
                
        for item in self.grasped_items.values():
            if item.equippable is not None:
                bonus += item.equippable.defense_bonus

        return bonus

    @property
    def power_bonus(self) -> int:
        bonus = 0

        # Calculate power from all equipped items
        for item in self.equipped_items.values():
            if item.equippable is not None:
                bonus += item.equippable.power_bonus
                
        for item in self.grasped_items.values():
            if item.equippable is not None:
                bonus += item.equippable.power_bonus

        return bonus
    
    def can_equip_item(self, item: Item) -> tuple[bool, str]:
        """Check if an item can be equipped based on body part tags."""
        if not item.equippable:
            return False, "Item is not equippable"
        
        # Use the new tag-based system
        if not hasattr(self.parent, 'body_parts') or not self.parent.body_parts:
            return False, "Entity has no body parts"
        
        # Check based on equipment type
        # Weapons/Shields generally need to be held in one hand (all tags on one part)
        if item.equippable.equipment_type in [EquipmentType.WEAPON, EquipmentType.SHIELD]:
            if not self.parent.body_parts.can_equip_item(item.equippable.required_tags):
                required = ", ".join(item.equippable.required_tags)
                return False, f"No body parts can equip this (requires single part with: {required})"
        else:
            # Armor can span multiple parts (e.g. Torso + Neck). 
            # Check if we have parts matching ALL the required tags cumulatively? 
            # OR just strictly check if we have coverage? 
            # For now, let's relax to: "Do we have parts that match these tags?"
            # Actually, let's assume if any tag matches a part, it can be worn, 
            # but we want to ensure the entity actually HAS the anatomy.
            
            missing_tags = []
            available_tags = set()
            for part in self.parent.body_parts.get_all_parts().values():
                available_tags.update(part.tags)
            
            if not item.equippable.required_tags.issubset(available_tags):
                 return False, f"Anatomy incompatible (requires: {item.equippable.required_tags})"

        return True, "Can equip"

    # Return slot item is in
    def get_slot(self, item: Item) -> Optional[str]:
        # Check equipped_items system
        for eq_type_name, equipped_item in self.equipped_items.items():
            if equipped_item == item:
                return eq_type_name
                
        # Check if it's a grasped item (weapons/shields)
        for body_part_name, grasped_item in self.grasped_items.items():
            if grasped_item == item:
                return body_part_name
                
        return None

    def item_is_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped."""
        return (item in self.equipped_items.values() or 
                item in self.grasped_items.values() or
                item in self.body_part_coverage.values())

    def unequip_message(self, item_name: str) -> None:
        self.parent.gamemap.engine.message_log.add_message(
            f"You remove the {item_name}."
        )

    def equip_message(self, item_name: str) -> None:
        self.parent.gamemap.engine.message_log.add_message(
            f"You equip the {item_name}."
        )

    def equip_to_slot(self, slot: str, item: Item, add_message: bool) -> None:
        """Legacy slot-based equipping (kept for backward compatibility with procgen)."""
        current_item = getattr(self, slot)

        if current_item is not None:
            self.unequip_from_slot(slot, add_message)

        setattr(self, slot, item)

        if add_message:
            self.equip_message(item.name)
        
        self._play_equip_sound(item)

    def unequip_from_slot(self, slot: str, add_message: bool) -> None:
        current_item = None
        
        # Check if it's an equipment type slot
        if slot in self.equipped_items:
            current_item = self.equipped_items[slot]
        else:
            # Check if it's a grasped item by equipment type
            for item in self.grasped_items.values():
                if (hasattr(item, 'equippable') and item.equippable and 
                    item.equippable.equipment_type.name == slot):
                    current_item = item
                    break
        
        if current_item is None:
            return

        if add_message:
            self.unequip_message(current_item.name)
        
        # The actual unequip logic is handled by unequip_item() method
        self.unequip_item(current_item, add_message=False)

    def toggle_equip(self, equippable_item: Item, add_message: bool = True) -> None:
        """Toggle equipping an item using the new modular system."""
        can_equip, reason = self.can_equip_item(equippable_item)
        
        if self.is_item_equipped(equippable_item):
            # Item is equipped, unequip it
            self.unequip_item(equippable_item, add_message)
        elif can_equip:
            # Item can be equipped, equip it
            self.equip_item(equippable_item, add_message)
        else:
            # Cannot equip item
            if add_message:
                from engine import Engine  
                try:
                    # Try to get engine instance for message log
                    engine = Engine.instance
                    engine.message_log.add_message(f"Cannot equip {equippable_item.name}: {reason}", color.impossible)
                except:
                    print(f"Cannot equip {equippable_item.name}: {reason}")
    
    def equip_item(self, item: Item, add_message: bool = True) -> None:
        """Equip an item using the modular system."""
        if not item.equippable:
            return
        
        eq_type = item.equippable.equipment_type
        
        # Handle grasped items (weapons, shields)
        if eq_type in [EquipmentType.WEAPON, EquipmentType.SHIELD]:
            # Find a hand to grasp the item (prefer empty hands, but use occupied ones if needed)
            if hasattr(self.parent, 'body_parts'):
                available_hands = []
                occupied_hands = []
                
                for part_type, part in self.parent.body_parts.body_parts.items():
                    if part.can_grasp and not part.is_destroyed:
                        if part.name not in self.grasped_items:
                            available_hands.append(part)
                        else:
                            occupied_hands.append(part)
                
                # Prefer empty hands, but use occupied ones if no empty hands
                if available_hands:
                    chosen_hand = available_hands[0]
                elif occupied_hands:
                    # Replace item in first occupied hand
                    chosen_hand = occupied_hands[0]
                    old_item = self.grasped_items[chosen_hand.name]
                    if add_message:
                        self.unequip_message(old_item.name)
                else:
                    # No hands at all (shouldn't happen for humanoids)
                    if add_message and hasattr(self.parent, 'gamemap'):
                        self.parent.gamemap.engine.message_log.add_message(
                            f"No hands to hold {item.name}!"
                        )
                    return
                
                self.grasped_items[chosen_hand.name] = item
            else:
                # Fallback if no body parts system
                if len(self.grasped_items) < 2:
                    hand_name = f"hand_{len(self.grasped_items) + 1}"
                    self.grasped_items[hand_name] = item
                else:
                    # Replace item in first hand
                    first_hand = list(self.grasped_items.keys())[0]
                    old_item = self.grasped_items[first_hand]
                    if add_message:
                        self.unequip_message(old_item.name)
                    self.grasped_items[first_hand] = item
        else:
            # Update general equipment tracking for non-grasped items
            eq_type_name = eq_type.name
            self.equipped_items[eq_type_name] = item
        
        if add_message:
            self.equip_message(item.name)
        
        # Play equip sound
        self._play_equip_sound(item)

        # Update body part coverage for armor items
        if eq_type not in [EquipmentType.WEAPON, EquipmentType.SHIELD] and hasattr(self.parent, "body_parts"):
            for part in self.parent.body_parts.get_all_parts().values():
                # Check if this part has the tags required by the item
                if item.equippable.required_tags.issubset(part.tags):
                   self.body_part_coverage[part.name] = item

    def unequip_item(self, item: Item, add_message: bool = True) -> None:
        """Unequip an item using the modular system."""
        if not item.equippable:
            return
        
        eq_type = item.equippable.equipment_type
        
        # Remove from grasped items
        body_parts_to_remove = []
        for body_part_name, grasped_item in self.grasped_items.items():
            if grasped_item == item:
                body_parts_to_remove.append(body_part_name)
        for body_part_name in body_parts_to_remove:
            del self.grasped_items[body_part_name]
        
        # Remove from body part coverage
        parts_to_remove = []
        for part, covering_item in self.body_part_coverage.items():
            if covering_item == item:
                parts_to_remove.append(part)
        for part in parts_to_remove:
            del self.body_part_coverage[part]
        
        # Remove from equipped items
        eq_type_name = eq_type.name
        if eq_type_name in self.equipped_items and self.equipped_items[eq_type_name] == item:
            del self.equipped_items[eq_type_name]
        
        if add_message:
            self.unequip_message(item.name)
        
        # Play unequip sound
        self._play_unequip_sound(item)
    
    def is_item_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped."""
    def is_item_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped."""
        return (item in self.grasped_items.values() or 
                item in self.equipped_items.values() or
                item in self.body_part_coverage.values())

    def get_defense_for_part(self, part_name: str) -> int:
        """Get defense bonus provided by equipment for a specific body part."""
        # Lazy init coverage if needed (handling load/init race conditions)
        # If we have equipped armor but no coverage data, rebuild it naturally
        if not self.body_part_coverage and self.equipped_items and hasattr(self.parent, "body_parts"):
            self._update_all_coverage()

        if part_name in self.body_part_coverage:
            item = self.body_part_coverage[part_name]
            if item.equippable:
                return item.equippable.defense_bonus
        return 0
    
    def _update_all_coverage(self) -> None:
        """Recalculate coverage for all equipped items."""
        from equipment_types import EquipmentType
        
        # Clear existing coverage
        self.body_part_coverage = {}
        
        # helper to process an item
        def process_item(item: Item):
            if not item.equippable: return
            if not hasattr(self.parent, "body_parts"): return
            
            # Skip weapons/shields as they don't provide passive coverage usually
            # (Logic matches equip_item)
            if item.equippable.equipment_type in [EquipmentType.WEAPON, EquipmentType.SHIELD]:
                return

            for part in self.parent.body_parts.get_all_parts().values():
                # For armor, we check intersection rather than subset.
                # If the item has "neck" tag and part has "neck" tag, it covers it.
                # But we ensure we don't accidentally match irrelevant tags 
                # (though body part names are usually good proxies, we use tags)
                
                # Intersection of item requirements and part tags
                # We expect the item to have specific location tags (torso, leg, etc)
                common_tags = item.equippable.required_tags.intersection(part.tags)
                if common_tags:
                    self.body_part_coverage[part.name] = item

        for item in self.equipped_items.values():
            process_item(item)

    def equip_to_specific_hand(self, item: Item, hand_name: str, add_message: bool = True) -> None:
        """Directly equip an item to a specific hand, replacing what's there."""
        if not item.equippable:
            return
        
        eq_type = item.equippable.equipment_type
        if eq_type not in [EquipmentType.WEAPON, EquipmentType.SHIELD]:
            # Not a grasped item, use regular equip
            self.equip_item(item, add_message)
            return
        
        # Check if hand already has something
        if hand_name in self.grasped_items:
            old_item = self.grasped_items[hand_name]
            if add_message:
                self.unequip_message(old_item.name)
        
        # Equip new item to specific hand
        self.grasped_items[hand_name] = item
        
        if add_message:
            self.equip_message(item.name)
        
        # Play equip sound
        self._play_equip_sound(item)

    def unequip_from_specific_hand(self, hand_name: str, add_message: bool = True) -> None:
        """Directly unequip item from a specific hand."""
        if hand_name in self.grasped_items:
            item = self.grasped_items[hand_name]
            del self.grasped_items[hand_name]
            
            if add_message:
                self.unequip_message(item.name)
            
            # Play unequip sound
            self._play_unequip_sound(item)

    def _play_equip_sound(self, item: Item) -> None:
        """Play equipment sound for an item."""
        if hasattr(item, "equip_sound") and item.equip_sound is not None:
            try:
                item.equip_sound()
            except Exception as e:
                print(f"Error playing equip sound: {e}")
    
    def _play_unequip_sound(self, item: Item) -> None:
        """Play unequip sound for an item."""
        if hasattr(item, "unequip_sound") and item.unequip_sound is not None:
            try:
                item.unequip_sound()
            except Exception as e:
                print(f"Error playing unequip sound: {e}")