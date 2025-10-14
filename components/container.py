from __future__ import annotations

from typing import List, TYPE_CHECKING, Optional

from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Item
    from entity import Actor


class Container(BaseComponent):
    """A simple container component that can hold items (like a chest)."""
    parent: Actor

    def __init__(self, capacity: int = 10, locked: bool = False):
        self.capacity = capacity
        self.items: List[Item] = []
        self.locked = locked

    def add(self, item: Item) -> bool:
        if len(self.items) >= self.capacity:
            return False
        # If item already in this container, treat as success (idempotent)
        if item in self.items:
            item.parent = self
            return True

        # If the item is currently in another container/inventory, remove it from there first
        try:
            old_parent = getattr(item, "parent", None)
            if old_parent is not None and hasattr(old_parent, "items"):
                try:
                    if item in old_parent.items:
                        old_parent.items.remove(item)
                except ValueError:
                    pass
        except Exception:
            pass

        self.items.append(item)
        item.parent = self
        return True

    def transfer_to(self, dest, item: Item) -> bool:
        """Atomically transfer item from this container to dest (Inventory or another Container).
        Returns True on success, False otherwise.
        """
        # Check capacity on dest
        if hasattr(dest, "is_full") and dest.is_full():
            return False
        if hasattr(dest, "capacity") and hasattr(dest, "items") and len(dest.items) >= dest.capacity:
            return False

        # Ensure item is present here
        if item not in self.items:
            return False

        try:
            self.items.remove(item)
        except ValueError:
            return False

        # If dest has add API, use it
        if hasattr(dest, "add"):
            success = dest.add(item)
            if success:
                return True
            # rollback
            try:
                self.items.append(item)
                item.parent = self
            except Exception:
                pass
            return False

        # Otherwise assume dest is Inventory-like
        try:
            item.parent = dest
            dest.items.append(item)
            return True
        except Exception:
            # rollback
            try:
                self.items.append(item)
                item.parent = self
            except Exception:
                pass
            return False

    def remove(self, item: Item) -> None:
        self.items.remove(item)
        # caller should set item.parent appropriately (e.g., player.inventory)

    def is_full(self) -> bool:
        return len(self.items) >= self.capacity

