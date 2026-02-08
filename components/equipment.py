from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from components.base_component import BaseComponent
from equipment_types import EquipmentType

if TYPE_CHECKING:
    from entity import Actor, Item

import sounds


class Equipment(BaseComponent):
    parent: Actor

    def __init__(self, weapon: Optional[Item] = None, backpack: Optional[Item] = None, armor: Optional[Item] = None, offhand: Optional[Item] = None):
        self.weapon = weapon
        self.backpack = backpack
        self.armor = armor
        self.offhand = offhand

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
        return self.weapon == item or self.armor == item or self.offhand == item

    def unequip_message(self, item_name: str) -> None:
        self.parent.gamemap.engine.message_log.add_message(
            f"You remove the {item_name}."
        )

    def equip_message(self, item_name: str) -> None:
        self.parent.gamemap.engine.message_log.add_message(
            f"You equip the {item_name}."
        )

    def equip_to_slot(self, slot: str, item: Item, add_message: bool) -> None:
        current_item = getattr(self, slot)

        if current_item is not None:
            self.unequip_from_slot(slot, add_message)

        setattr(self, slot, item)

        if add_message:
            self.equip_message(item.name)
                # Play equip sound 
        #print(f"DEBUG: Checking equip sound for {item.name}")
        #print(f"DEBUG: Has equip_sound attr: {hasattr(item, 'equip_sound')}")
        #if hasattr(item, 'equip_sound'):
        #    print(f"DEBUG: equip_sound value: {item.equip_sound}")
        if hasattr(item, "equip_sound") and item.equip_sound is not None:
            #print(f"DEBUG: About to call equip sound for {item.name}")
            try:
                item.equip_sound()
                #print(f"DEBUG: Successfully called equip sound for {item.name}")
            except Exception as e:
                print(f"DEBUG: Error calling equip sound: {e}")
        else:
            print(f"DEBUG: No equip sound for {item}")
        #if item_name.lower() == "torch":
        #    sounds.play_torch_pull_sound()

    def unequip_from_slot(self, slot: str, add_message: bool) -> None:
        current_item = getattr(self, slot)

        if add_message:
            self.unequip_message(current_item.name)
        
        # Play unequip sound
        if hasattr(current_item, "unequip_sound") and current_item.unequip_sound is not None:
            try:
                current_item.unequip_sound()
            except Exception as e:
                print(f"DEBUG: Error calling unequip sound: {e}")
        else:
            print(f"DEBUG: No unequip sound for {current_item}")

        setattr(self, slot, None)

    def toggle_equip(self, equippable_item: Item, add_message: bool = True) -> None:
        # Determine target slot: weapon, offhand or armor. If the item
        # explicitly marks OFFHAND, respect that. Otherwise weapons default
        # to the main 'weapon' slot.
        if (
            equippable_item.equippable
            and equippable_item.equippable.equipment_type == EquipmentType.OFFHAND
        ):
            slot = "offhand"
        elif (
            equippable_item.equippable
            and equippable_item.equippable.equipment_type == EquipmentType.WEAPON
        ):
            slot = "weapon"
        elif (
            equippable_item.equippable
            and equippable_item.equippable.equipment_type == EquipmentType.BACKPACK
        ):
            slot = "back"
        else:
            slot = "armor"

        if getattr(self, slot) == equippable_item:
            self.unequip_from_slot(slot, add_message)
        else:
            self.equip_to_slot(slot, equippable_item, add_message)