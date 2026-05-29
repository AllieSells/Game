from __future__ import annotations

from typing import List, Dict, TYPE_CHECKING

from components.base_component import BaseComponent
import identify as identify_system

if TYPE_CHECKING:
    from entity import Actor, Item


class Inventory(BaseComponent):
    parent: Actor

    def __init__(self, capacity: int, max_weight: float = 50.0):
        # capacity=0 means this actor cannot pick up items at all (NPCs, containers).
        # For the player capacity is kept for legacy compat but weight is the real limit.
        self.capacity    = capacity
        self._max_weight = max_weight
        self.items: List[Item] = []
        self.item_slots: List = []  # positional grid slots — grows dynamically

    @property
    def max_weight(self) -> float:
        # getattr fallback keeps old save files working (they lack _max_weight)
        return getattr(self, '_max_weight', 50.0)

    @max_weight.setter
    def max_weight(self, value: float) -> None:
        self._max_weight = value

    @staticmethod
    def _item_is_arrow(item) -> bool:
        """Return True for ammo items (not quivers)."""
        item_tags = {str(t).strip().lower() for t in getattr(item, 'tags', []) or []}
        eq_type_name = None
        if getattr(item, 'equippable', None):
            eq_type_name = item.equippable.equipment_type.name
        if eq_type_name == 'BACKPACK' or 'quiver' in item_tags:
            return False
        return (
            eq_type_name == 'PROJECTILE'
            or 'arrow' in item_tags
            or 'ammunition' in item_tags
            or 'ammo' in item_tags
        )

    @property
    def current_weight(self) -> float:
        """Total weight of all carried items.

        Arrows/ammo are weightless when the actor has a quiver equipped —
        the quiver absorbs that burden.
        """
        # Check once whether a quiver is equipped.
        has_quiver = False
        equipment = getattr(self.parent, 'equipment', None)
        if equipment and hasattr(equipment, 'get_equipped_quiver'):
            has_quiver = equipment.get_equipped_quiver() is not None

        total = 0.0
        for item in self.items:
            w = getattr(item, 'weight', None)
            if not isinstance(w, (int, float)):
                w = 0.0
            if has_quiver and self._item_is_arrow(item):
                w = 0.0
            total += w * max(1, getattr(item, '_quantity', 1))
        return total

    def can_carry(self, item) -> bool:
        """Return True if this actor can pick up *item* right now.

        * capacity == 0 → actor has no inventory (always False).
        * Otherwise check carry-weight limit.
        """
        if self.capacity == 0:
            return False
        w = getattr(item, 'weight', None)
        item_weight = w if isinstance(w, (int, float)) else 0.0
        return (self.current_weight + item_weight) <= self.max_weight

    def sync_slots(self) -> None:
        """Reconcile item_slots with the items list.

        Called once per frame when the inventory UI is open.  New items are
        assigned to the first free slot; stale entries are cleared.  The list
        grows as needed — there is no upper bound tied to capacity.
        """
        if not hasattr(self, 'item_slots') or self.item_slots is None:
            self.item_slots = []

        # Each item now occupies its own slot; no display grouping/stacking.
        valid_ids = {id(item) for item in self.items}

        # Clear stale slots
        for i, s in enumerate(self.item_slots):
            if s is not None and id(s) not in valid_ids:
                self.item_slots[i] = None

        # Assign unslotted items — extend the list if no free slot exists.
        slotted = {id(s) for s in self.item_slots if s is not None}
        for item in self.items:
            if id(item) not in slotted:
                # Find first None slot
                placed = False
                for i in range(len(self.item_slots)):
                    if self.item_slots[i] is None:
                        self.item_slots[i] = item
                        slotted.add(id(item))
                        placed = True
                        break
                if not placed:
                    # No free slot — append a new one
                    self.item_slots.append(item)
                    slotted.add(id(item))
    
    def get_display_groups(self) -> List[Dict]:
        """Return one display entry per concrete inventory item."""
        return [
            {
                'item': item,
                'items': [item],
                'quantity': 1,
                'display_name': item.name,
            }
            for item in self.items
        ]

    def delete(self, item: Item) -> None:
        """Permanently removes an item from the inventory without dropping it on the map."""
        try:
            self.items.remove(item)
            identify_system.cancel_identification_for_item(self.parent, item, engine=self.engine, quiet=True)
        except ValueError:
            pass

    def drop(self, item: Item) -> None:
        """
        Removes an item from the inventory and restores it to the game map, at the player's current location.
        """
        try:
            self.items.remove(item)
            identify_system.cancel_identification_for_item(self.parent, item, engine=self.engine, quiet=True)
        except ValueError:
            return

        # Place on the map at the owner's location
        try:
            item.place(self.parent.x, self.parent.y, self.gamemap)
        except Exception:
            pass

        shown_name = identify_system.get_display_name(self.engine.player, item)
        self.engine.message_log.add_message(f"You dropped the {shown_name}.")

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
            identify_system.cancel_identification_for_item(self.parent, item, engine=self.engine, quiet=True)
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