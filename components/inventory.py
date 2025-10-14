from __future__ import annotations

from typing import List, TYPE_CHECKING

from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Actor, Item


class Inventory(BaseComponent):
    parent: Actor

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.items: List[Item] = []

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