from __future__ import annotations

from email.mime import base
from typing import TYPE_CHECKING

import color
from components.base_component import BaseComponent
from render_order import RenderOrder

if TYPE_CHECKING:
    from entity import Actor



class Fighter(BaseComponent):

    parent: Actor

    def __init__(self, hp: int, base_defense: int, base_power: int, leave_corpse: bool = True):
        self.max_hp = hp
        self._hp = hp
        self.base_defense = base_defense
        self.base_power = base_power
        # Whether this entity should leave a corpse when it dies.
        # Set to False for ephemeral creatures like Shades.
        self.leave_corpse = leave_corpse

    @property
    def hp(self) -> int:
        return self._hp
    
    @hp.setter
    def hp(self, value: int) -> None:
        self._hp = max(0, min(value, self.max_hp))  # Clamp the value between 0 and max_hp
        if self._hp == 0 and self.parent.ai:
            print("why not die")
            self.die()

    @property
    def defense(self) -> int:
        return self.base_defense + self.defense_bonus
    
    @property
    def power(self) -> int:
        return self.base_power + self.power_bonus

    @property
    def defense_bonus(self) -> int:
        if self.parent.equipment:
            return self.parent.equipment.defense_bonus
        else:
            return 0

    @property
    def power_bonus(self) -> int:
        if self.parent.equipment:
            return self.parent.equipment.power_bonus
        else:
            return 0
    
    def die(self) -> None:
        if self.engine.player is self.parent:
            death_message = "YOU DIED IDIOT"
            death_message_color = color.player_die
        else:
            death_message = f"{self.parent.name} is dead! Not big surpise."
            death_message_color = color.enemy_die
        # If configured not to leave a corpse (ephemeral creatures), remove
        # the entity from the map and award XP without creating a corpse.
        if not getattr(self, "leave_corpse", True):
            try:
                self.engine.message_log.add_message(death_message, death_message_color)
            except Exception:
                pass

            try:
                gm = self.parent.gamemap
                if hasattr(gm, "entities") and self.parent in gm.entities:
                    try:
                        gm.entities.remove(self.parent)
                    except Exception:
                        try:
                            gm.entities.discard(self.parent)
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                self.parent.ai = None
            except Exception:
                pass

            try:
                self.parent.blocks_movement = False
            except Exception:
                pass

            try:
                self.engine.player.level.add_xp(self.parent.level.xp_given)
            except Exception:
                pass

            return

        # Default death behavior: leave a corpse
        self.parent.char = "%"
        self.parent.color = (191, 0, 0)
        self.parent.blocks_movement = False
        self.parent.ai = None
        self.parent.name = f"remains of {self.parent.name}"
        self.parent.render_order = RenderOrder.CORPSE

        try:
            self.engine.message_log.add_message(death_message, death_message_color)
        except Exception:
            pass

        try:
            self.engine.player.level.add_xp(self.parent.level.xp_given)
        except Exception:
            pass

    def heal(self, amount: int) -> int:
        if self.hp == self.max_hp:
            return 0
        
        new_hp_value = self.hp + amount

        if new_hp_value > self.max_hp:
            new_hp_value = self.max_hp

        amount_recovered = new_hp_value - self.hp

        self.hp = new_hp_value

        return amount_recovered
    
    def take_damage(self, amount: int) -> None:
        self.hp -= amount
