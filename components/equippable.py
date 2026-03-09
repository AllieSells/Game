from __future__ import annotations

from typing import TYPE_CHECKING, Set

from components.base_component import BaseComponent
from equipment_types import EquipmentType

if TYPE_CHECKING:
    from entity import Item


class Equippable(BaseComponent):
    parent: Item

    def __init__(
        self,
        equipment_type: EquipmentType,
        power_bonus: int = 0,
        defense_bonus: int = 0,
        required_tags: Set[str] | None = None,
        equip_all_matching: bool = True,  # True = cover all matching parts, False = use only one
    ):
        self.equipment_type = equipment_type
        self.power_bonus = power_bonus
        self.defense_bonus = defense_bonus
        self.required_tags = required_tags or set()  # Tags that body parts must have to equip this item
        self.equip_all_matching = equip_all_matching  # Whether to equip to all matching parts or just one

    def get_defense(self) -> int:
        """Calculate total defense provided by this item, including any trait bonuses."""
        bonus = 0
        if 'light armor' in self.parent.tags:
            bonus = self.defense_bonus + self.engine.player.level.traits['light armor']['level'] - 1
        else:
            bonus = self.defense_bonus
        return bonus
class Arrow(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.PROJECTILE, power_bonus=3, required_tags={"hand", "grasp"})

class Bow(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.RANGED, power_bonus=0, required_tags={"hand", "grasp"})

class Dagger(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=2, required_tags={"hand", "grasp"}, equip_all_matching=False)

class Shortsword(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=4, required_tags={"hand", "grasp"}, equip_all_matching=False)

class Longsword(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=6, required_tags={"hand", "grasp"}, equip_all_matching=True)

class LeatherCap(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.HELMET, defense_bonus=1, required_tags={"head", "neck"}, equip_all_matching=True)

class LeatherLeggings(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.LEGGINGS, defense_bonus=1, required_tags={"leg"}, equip_all_matching=True)

class LeatherBoot(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BOOTS, defense_bonus=1, required_tags={"foot"}, equip_all_matching=True)

class LeatherArmor(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=1, required_tags={"torso"}, equip_all_matching=True)


class ChainMail(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=3, required_tags={"torso"})

class devtool(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=1000, required_tags={"hand", "grasp"})

class Torch(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=0, required_tags={"hand", "hold", "use"}, equip_all_matching=False)

class Shield(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.SHIELD, defense_bonus=2, required_tags={"hand", "grasp"})

class Helmet(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.HELMET, defense_bonus=1, required_tags={"head", "neck"})

class Boots(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BOOTS, defense_bonus=1, required_tags={"foot"})

class Gauntlets(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.GAUNTLETS, defense_bonus=1, required_tags={"arm"})

class Leggings(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.LEGGINGS, defense_bonus=1, required_tags={"leg"})

class Backpack(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BACKPACK, power_bonus=0, required_tags={"torso", "back"})
        