from __future__ import annotations

from typing import List, Dict, TYPE_CHECKING
from collections import defaultdict

from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Actor, Item


class Inventory(BaseComponent):
    parent: Actor

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.items: List[Item] = []
    
    def get_display_groups(self) -> List[Dict]:
        """Group identical items for display purposes with quantities."""
        item_groups = defaultdict(list)
        
        # Group items by their display key (name + basic properties)
        for item in self.items:
            key = self._get_item_display_key(item)
            item_groups[key].append(item)
        
        # Convert to display format
        display_groups = []
        for items in item_groups.values():
            representative_item = items[0]
            quantity = len(items)
            display_name = representative_item.name
            if quantity > 1:
                display_name = f"{representative_item.name} (x{quantity})"
            
            display_groups.append({
                'item': representative_item,
                'items': items,  # All items in this group
                'quantity': quantity,
                'display_name': display_name
            })
        
        return display_groups
    
    def _get_item_display_key(self, item: "Item") -> str:
        """Generate a key for grouping identical items in display."""
        # Check if item has equippable component
        if hasattr(item, 'equippable') and item.equippable:
            # Allow projectiles (arrows, bolts, etc.) to stack
            if hasattr(item.equippable, 'equipment_type'):
                eq_type = item.equippable.equipment_type
                # Import here to avoid circular imports
                try:
                    from equipment_types import EquipmentType
                    if eq_type == EquipmentType.PROJECTILE:
                        # Projectiles can stack by name
                        return item.name
                except ImportError:
                    pass
            
            # Other equippables (weapons, armor) shouldn't stack due to durability/enchantments
            return f"{item.name}_{id(item)}"
        
        # Items with different burn durations shouldn't stack
        if hasattr(item, 'burn_duration') and item.burn_duration is not None:
            return f"{item.name}_burn_{item.burn_duration}"
        
        # Items with different liquid amounts shouldn't stack
        if hasattr(item, 'liquid_amount') and item.liquid_amount is not None:
            return f"{item.name}_liquid_{item.liquid_amount}"
        
        # Default grouping by name for stackable items
        return item.name

    def delete(self, item: Item) -> None:
        """Permanently removes an item from the inventory without dropping it on the map."""
        try:
            self.items.remove(item)
        except ValueError:
            pass

    def drop(self, item: Item) -> None:
        """
        Removes an item from the inventory and restores it to the game map, at the player's current location.
        """
        try:
            self.items.remove(item)
        except ValueError:
            return

        # Place on the map at the owner's location
        try:
            item.place(self.parent.x, self.parent.y, self.gamemap)
        except Exception:
            pass

        self.engine.message_log.add_message(f"You dropped the {item.name}.")

    def transfer_to(self, dest, item: "Item") -> bool:
        """Atomically transfer item from this inventory to dest (Inventory or Container-like).
        Returns True on success, False otherwise.
        """
        # Check capacity on dest
        if hasattr(dest, "is_full") and dest.is_full():
            return False
        if hasattr(dest, "capacity") and hasattr(dest, "items") and len(dest.items) >= dest.capacity:
            return False

        # Ensure item is present
        if item not in self.items:
            return False

        # Remove from source and add to dest with proper parent updates
        try:
            self.items.remove(item)
        except ValueError:
            return False

        # If dest has an add API, use it (it will set parent)
        if hasattr(dest, "add"):
            success = dest.add(item)
            if success:
                return True
            # rollback: put item back
            try:
                self.items.append(item)
            except Exception:
                pass
            return False

        # Otherwise assume dest is an Inventory-like
        try:
            item.parent = dest
            dest.items.append(item)
            return True
        except Exception:
            # rollback
            try:
                item.parent = self
                self.items.append(item)
            except Exception:
                pass
            return False