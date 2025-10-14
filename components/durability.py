from __future__ import annotations

from typing import TYPE_CHECKING

import color
from components.base_component import BaseComponent

if TYPE_CHECKING:
    from entity import Item


class Durability(BaseComponent):
    """A reusable durability component for items.

    Tracks current and maximum durability and provides a method to
    decrement durability and handle item breakage.
    """
    parent: "Item"

    def __init__(self, max_durability: int):
        self.max_durability = max_durability
        self.current_durability = max_durability

    def degrade(self, amount: int = 1) -> None:
        """Decrease durability by amount. If durability reaches zero,
        remove the item from its parent (inventory or equipment) and
        notify the player via the message log.
        """
        self.current_durability -= amount
        if self.current_durability <= 0:
            # Guard: ensure we only process breaking once
            if getattr(self, "_broken", False):
                return
            self._broken = True

            # Item is broken. Remove from wherever it is.
            item = self.parent
            engine = self.engine
            # If the item is equipped, unequip it first if possible.
            try:
                # The item.parent might be an Actor, or an Inventory whose parent is the Actor.
                actor = None
                if hasattr(item, "parent") and hasattr(item.parent, "equipment"):
                    actor = item.parent  # parent is Actor
                elif hasattr(item, "parent") and hasattr(item.parent, "parent") and hasattr(item.parent.parent, "equipment"):
                    actor = item.parent.parent  # parent is Inventory, parent.parent is Actor

                if actor and actor.equipment.item_is_equipped(item):
                    # Find the slot and unequip without showing the equip/unequip message
                    try:
                        slot = next(
                            slot for slot in ("weapon", "armor", "offhand", "back")
                            if getattr(actor.equipment, slot) == item
                        )
                        actor.equipment.unequip_from_slot(slot, add_message=False)
                    except StopIteration:
                        pass
            except Exception:
                # Best-effort: ignore if not applicable
                pass

            # If item is in an inventory, remove it
            try:
                if hasattr(item, "parent") and hasattr(item.parent, "items"):
                    inventory = item.parent
                    inventory.items.remove(item)
            except Exception:
                pass

            # Finally, if item is on the map, remove from entities
            try:
                if hasattr(item, "gamemap") and item in item.gamemap.entities:
                    item.gamemap.entities.remove(item)
            except Exception:
                pass

            # Message the player
            engine.message_log.add_message(f"Your {item.name} breaks.", color.red)

            # Remove durability attribute so future calls won't re-run breaking logic
            try:
                if hasattr(item, "durability"):
                    delattr(item, "durability")
            except Exception:
                pass

            # Update FOV if the item's removal affects vision/light (best-effort)
            try:
                engine.update_fov()
            except Exception:
                pass
