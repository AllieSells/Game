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

    def __init__(self, weapon: Optional[Item] = None, backpack: Optional[Item] = None, armor: Optional[Item] = None, offhand: Optional[Item] = None):
        # Legacy slot system for backward compatibility
        self.weapon = weapon
        self.backpack = backpack
        self.armor = armor
        self.offhand = offhand
        
        # New modular equipment tracking
        self.equipped_items: Dict[str, Item] = {}  # Maps equipment categories to items
        self.body_part_coverage: Dict[str, Item] = {}  # Maps covered body parts to covering items
        self.grasped_items: Set[Item] = set()  # Items currently being grasped
        
        # Sync legacy items into new system
        if weapon:
            self.grasped_items.add(weapon)
        if armor:
            self.equipped_items["ARMOR"] = armor
        if backpack:
            self.equipped_items["BACKPACK"] = backpack
        if offhand:
            self.grasped_items.add(offhand)

    @property
    def defense_bonus(self) -> int:
        bonus = 0

        if self.weapon is not None and self.weapon.equippable is not None:
            bonus += self.weapon.equippable.defense_bonus

        if self.armor is not None and self.armor.equippable is not None:
            bonus += self.armor.equippable.defense_bonus

        if self.offhand is not None and self.offhand.equippable is not None:
            bonus += self.offhand.equippable.defense_bonus

        return bonus

    @property
    def power_bonus(self) -> int:
        bonus = 0

        if self.weapon is not None and self.weapon.equippable is not None:
            bonus += self.weapon.equippable.power_bonus

        if self.armor is not None and self.armor.equippable is not None:
            bonus += self.armor.equippable.power_bonus

        if self.offhand is not None and self.offhand.equippable is not None:
            bonus += self.offhand.equippable.power_bonus

        return bonus
    
    def can_equip_item(self, item: Item) -> tuple[bool, str]:
        """Check if an item can be equipped based on body part tags."""
        if not item.equippable:
            return False, "Item is not equippable"
        
        # Use the new tag-based system
        if not hasattr(self.parent, 'body_parts') or not self.parent.body_parts:
            return False, "Entity has no body parts"
        
        # Check if any body part has all required tags
        if not self.parent.body_parts.can_equip_item(item.equippable.required_tags):
            required = ", ".join(item.equippable.required_tags)
            return False, f"No body parts can equip this (requires: {required})"
        
        return True, "Can equip"

    # Return slot item is in
    def get_slot(self, item: Item) -> Optional[str]:
        if self.weapon == item:
            return "weapon"
        elif self.armor == item:
            return "armor"
        elif self.offhand == item:
            return "offhand"
        elif self.backpack == item:
            return "backpack"
        return None

    def item_is_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped (legacy method, use is_item_equipped)."""
        return self.is_item_equipped(item)

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
        current_item = getattr(self, slot)
        
        if current_item is None:
            return

        if add_message:
            self.unequip_message(current_item.name)
        
        # Play unequip sound
        if hasattr(current_item, "unequip_sound") and current_item.unequip_sound is not None:
            try:
                current_item.unequip_sound()
            except Exception as e:
                print(f"Error calling unequip sound: {e}")

        # Clean up both legacy slot and new modular system
        setattr(self, slot, None)
        
        # Also remove from new modular system
        if current_item in self.grasped_items:
            self.grasped_items.remove(current_item)
        
        # Remove from equipped items
        items_to_remove = []
        for eq_type_name, item in self.equipped_items.items():
            if item == current_item:
                items_to_remove.append(eq_type_name)
        for eq_type_name in items_to_remove:
            del self.equipped_items[eq_type_name]
        
        # Remove from body part coverage
        parts_to_remove = []
        for part, item in self.body_part_coverage.items():
            if item == current_item:
                parts_to_remove.append(part)
        for part in parts_to_remove:
            del self.body_part_coverage[part]

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
            self.grasped_items.add(item)
            # Update legacy slots for backward compatibility  
            if eq_type == EquipmentType.WEAPON:
                if not self.weapon:
                    self.weapon = item
                elif not self.offhand:
                    self.offhand = item
            elif eq_type == EquipmentType.SHIELD:
                if not self.offhand:
                    self.offhand = item
                elif not self.weapon:
                    self.weapon = item
        
        # Update general equipment tracking
        eq_type_name = eq_type.name
        if eq_type_name not in ["WEAPON", "SHIELD"]:  # These go in grasped_items
            self.equipped_items[eq_type_name] = item
            
            # Update legacy slots
            if eq_type_name == "ARMOR":
                self.armor = item
            elif eq_type_name == "BACKPACK":
                self.backpack = item
        
        if add_message:
            self.equip_message(item.name)
        
        # Play equip sound
        self._play_equip_sound(item)

    def unequip_item(self, item: Item, add_message: bool = True) -> None:
        """Unequip an item using the modular system."""
        if not item.equippable:
            return
        
        eq_type = item.equippable.equipment_type
        
        # Remove from grasped items
        if item in self.grasped_items:
            self.grasped_items.remove(item)
            # Update legacy slots
            if self.weapon == item:
                self.weapon = None
            elif self.offhand == item:
                self.offhand = None
        
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
            
            # Update legacy slots
            if eq_type_name == "ARMOR":
                self.armor = None
            elif eq_type_name == "BACKPACK":
                self.backpack = None
        
        if add_message:
            self.unequip_message(item.name)
        
        # Play unequip sound
        self._play_unequip_sound(item)
    
    def is_item_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped."""
        return (item in self.grasped_items or 
                item in self.equipped_items.values() or
                item in self.body_part_coverage.values())
    
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