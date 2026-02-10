from __future__ import annotations

from typing import TYPE_CHECKING

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
    ):
        self.equipment_type = equipment_type

        self.power_bonus = power_bonus
        self.defense_bonus = defense_bonus


class Dagger(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=2)


class Sword(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=4)


class LeatherArmor(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=1)


class ChainMail(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.ARMOR, defense_bonus=3)

class devtool(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=1000)

class Torch(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.WEAPON, power_bonus=0)

class Shield(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.SHIELD, defense_bonus=2)

class Helmet(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.HELMET, defense_bonus=1)

class Boots(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BOOTS, defense_bonus=1)

class Gauntlets(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.GAUNTLETS, defense_bonus=1)

class Leggings(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.LEGGINGS, defense_bonus=1)

class Backpack(Equippable):
    def __init__(self) -> None:
        super().__init__(equipment_type=EquipmentType.BACKPACK, power_bonus=0)
        