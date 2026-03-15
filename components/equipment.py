from __future__ import annotations

from typing import Optional, TYPE_CHECKING, Dict, Set

from components.base_component import BaseComponent
from equipment_types import EquipmentType
import color

if TYPE_CHECKING:
    from entity import Actor, Item
    from components.entity.body.body_parts import BodyPartType

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
        # Get all unique equipped items efficiently  
        all_items = set(self.equipped_items.values()) | set(self.grasped_items.values()) | set(self.body_part_coverage.values())
        
        bonus = 0
        for item in all_items:
            if item.equippable is None:
                continue
            
            item_defense = item.equippable.defense_bonus
            
            # Apply light armor skill bonus if applicable
            modifier = 0
            if 'light armor' in item.equippable.parent.tags:
                modifier = self.parent.level.traits['light armor']['level'] - 1
            
            bonus += item_defense + modifier

        return bonus

    def has_item_equipped(self, item_name: str) -> bool:
        """Check if player has a specific item equipped (optimized for common checks like torches)."""
        try:
            # Check all equipment systems in one efficient loop
            all_items = (
                list(self.grasped_items.values()) +
                list(self.body_part_coverage.values()) + 
                list(self.equipped_items.values())
            )
            return any(hasattr(item, 'name') and item.name == item_name for item in all_items)
        except Exception:
            return False

    @property
    def power_bonus(self) -> int:
        # Get all unique equipped items efficiently
        all_items = set(self.equipped_items.values()) | set(self.grasped_items.values()) | set(self.body_part_coverage.values())
        
        return sum(item.equippable.power_bonus for item in all_items if item.equippable is not None)
    
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
                    self.engine.debug_log(f"Cannot equip {equippable_item.name}: {reason}", handler=self.__class__.__name__, event="EquipError")
    
    def equip_item(self, item: Item, add_message: bool = True) -> None:
        """Equip an item using the modular system."""
        if not item.equippable:
            return
        
        eq_type = item.equippable.equipment_type
        
        # First, unequip any items that would conflict with this one
        if hasattr(self.parent, "body_parts"):
            equip_all = getattr(item.equippable, 'equip_all_matching', False)
            conflicting_items = set()
            
            # Find all body parts this item would cover
            parts_to_cover = []
            for part in self.parent.body_parts.get_all_parts().values():
                if item.equippable.required_tags.issubset(part.tags):
                    parts_to_cover.append(part)
                    if not equip_all:
                        break  # Only need first match if not equipping to all
            
            # Check for existing items on those parts
            for part in parts_to_cover:
                if part.name in self.body_part_coverage:
                    conflicting_items.add(self.body_part_coverage[part.name])
            
            # Unequip all conflicting items
            for conflicting_item in conflicting_items:
                if conflicting_item != item:  # Don't unequip the item we're trying to equip
                    self.unequip_item(conflicting_item, add_message)
        
        # Update general equipment tracking
        eq_type_name = eq_type.name
        self.equipped_items[eq_type_name] = item
        
        if add_message:
            self.equip_message(item.name)
        
        # Play equip sound
        self._play_equip_sound(item)

        # Update body part coverage for all items
        if hasattr(self.parent, "body_parts"):
            equip_all = getattr(item.equippable, 'equip_all_matching', False)
            self.engine.debug_log(f"DEBUG: Equipping item: {item.name}: equip_all_matching={equip_all}, required_tags={item.equippable.required_tags}", handler=self.__class__.__name__, event="EquipDebug")
            all_parts = self.parent.body_parts.get_all_parts()
            self.engine.debug_log(f"DEBUG: Equipping item: All parts: { {name: part.tags for name, part in all_parts.items()} }", handler=self.__class__.__name__, event="EquipDebug")

            if equip_all:
                # Cover all matching body parts (like leggings on both legs)
                for part in all_parts.values():
                    match = item.equippable.required_tags.issubset(part.tags)
                    self.engine.debug_log(f"DEBUG: Equipping item:   Part '{part.name}' tags={part.tags} -> match={match}", handler=self.__class__.__name__, event="EquipDebug")
                    if match:
                        self.body_part_coverage[part.name] = item
                self.engine.debug_log(f"DEBUG: Equipping item: body_part_coverage after equip: {list(self.body_part_coverage.keys())}", handler=self.__class__.__name__, event="EquipDebug")
            else:
                # Cover only one matching body part - prefer right hand over left hand for weapons
                target_part = None
                
                # For hand-based items, prefer right hand
                if "hand" in item.equippable.required_tags:
                    # First try to find right hand
                    for part in self.parent.body_parts.get_all_parts().values():
                        if item.equippable.required_tags.issubset(part.tags) and "right" in part.tags:
                            target_part = part
                            break
                    
                    # If right hand not available, try left hand
                    if not target_part:
                        for part in self.parent.body_parts.get_all_parts().values():
                            if item.equippable.required_tags.issubset(part.tags) and "left" in part.tags:
                                target_part = part
                                break
                else:
                    # For non-hand items, just take the first match
                    for part in self.parent.body_parts.get_all_parts().values():
                        if item.equippable.required_tags.issubset(part.tags):
                            target_part = part
                            break
                
                if target_part:
                    self.body_part_coverage[target_part.name] = item

    def unequip_item(self, item: Item, add_message: bool = True) -> None:
        """Unequip an item using the modular system."""
        if not item.equippable:
            return
        
        eq_type = item.equippable.equipment_type
        
        # Remove from all tracking systems (optimized with dict comprehensions)
        self.grasped_items = {k: v for k, v in self.grasped_items.items() if v != item}
        self.body_part_coverage = {k: v for k, v in self.body_part_coverage.items() if v != item}
        
        # Remove from equipped items
        eq_type_name = eq_type.name
        if eq_type_name in self.equipped_items and self.equipped_items[eq_type_name] == item:
            del self.equipped_items[eq_type_name]
        
        if add_message:
            self.unequip_message(item.name)
        
        # Play unequip sound
        self._play_unequip_sound(item)
    
    def is_item_equipped(self, item: Item) -> bool:
        """Check if an item is currently equipped (optimized)."""
        return (item in self.grasped_items.values() or 
                item in self.equipped_items.values() or
                item in self.body_part_coverage.values())

    def get_armor_tags_for_part(self, part_name: str) -> Set[str]:
        # Get equipped item tags for a specific body part
        if part_name in self.body_part_coverage:
            item = self.body_part_coverage[part_name]
            if item.equippable:
                return item.tags
        return None

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
        """Directly equip an item to a specific hand, replacing what's there.
        If equip_all_matching is True, equips to ALL matching parts instead."""
        if not item.equippable:
            return
        
        equip_all = getattr(item.equippable, 'equip_all_matching', False)

        # If the item covers all matching parts, delegate to equip_item which handles that correctly
        if equip_all:
            self.equip_item(item, add_message)
            return

        eq_type = item.equippable.equipment_type
        
        # First, unequip any conflicting items
        self.unequip_from_specific_hand(hand_name, add_message)
        
        # Update general equipment tracking
        eq_type_name = eq_type.name
        self.equipped_items[eq_type_name] = item
        
        # Add to body part coverage for the specific hand
        if hasattr(self.parent, "body_parts"):
            for part in self.parent.body_parts.get_all_parts().values():
                if part.name == hand_name and item.equippable.required_tags.issubset(part.tags):
                    self.body_part_coverage[part.name] = item
                    break
        
        if add_message:
            self.equip_message(item.name)
        
        # Play equip sound
        self._play_equip_sound(item)

    def unequip_from_specific_hand(self, hand_name: str, add_message: bool = True) -> None:
        """Directly unequip item from a specific hand.
        If the item has equip_all_matching, unequips from ALL matching parts instead."""
        item_to_unequip = None
        
        # Check grasped_items first (legacy system)
        if hand_name in self.grasped_items:
            item_to_unequip = self.grasped_items[hand_name]
        # Check body_part_coverage (modern system)
        elif hand_name in self.body_part_coverage:
            item_to_unequip = self.body_part_coverage[hand_name]
        
        if item_to_unequip:
            # If equip_all_matching, delegate to unequip_item which clears all coverage at once
            if getattr(item_to_unequip.equippable, 'equip_all_matching', False):
                self.unequip_item(item_to_unequip, add_message)
                return

            # Otherwise remove only from the specific hand
            if hand_name in self.grasped_items:
                del self.grasped_items[hand_name]
            elif hand_name in self.body_part_coverage:
                del self.body_part_coverage[hand_name]
            
            # Also remove from equipped_items if it's there
            if item_to_unequip.equippable:
                eq_type_name = item_to_unequip.equippable.equipment_type.name
                if eq_type_name in self.equipped_items and self.equipped_items[eq_type_name] == item_to_unequip:
                    del self.equipped_items[eq_type_name]
            
            if add_message:
                self.unequip_message(item_to_unequip.name)
            
            self._play_unequip_sound(item_to_unequip)

    def _play_equip_sound(self, item: Item) -> None:
        """Play equipment sound for an item."""
        # Skip sounds during world generation or level transitions
        try:
            engine = self.parent.gamemap.engine
            if getattr(engine, 'is_generating_world', False) or getattr(engine, 'is_transitioning_level', False):
                return
        except Exception:
            pass
            
        if hasattr(item, "equip_sound") and item.equip_sound is not None:
            try:
                item.equip_sound()
            except Exception as e:
                try:
                    engine = self.parent.gamemap.engine
                    if hasattr(engine, 'debug_log'):
                        engine.debug_log(f"Error playing equip sound: {e}", handler=self.__class__.__name__, event="EquipSoundError")
                except Exception:
                    pass
    
    def _play_unequip_sound(self, item: Item) -> None:
        """Play unequip sound for an item."""
        # Skip sounds during world generation or level transitions
        try:
            engine = self.parent.gamemap.engine
            if getattr(engine, 'is_generating_world', False) or getattr(engine, 'is_transitioning_level', False):
                return
        except Exception:
            pass
            
        if hasattr(item, "unequip_sound") and item.unequip_sound is not None:
            try:
                item.unequip_sound()
            except Exception as e:
                try:
                    engine = self.parent.gamemap.engine
                    if hasattr(engine, 'debug_log'):
                        engine.debug_log(f"Error playing unequip sound: {e}", handler=self.__class__.__name__, event="UnequipSoundError")
                except Exception:
                    pass