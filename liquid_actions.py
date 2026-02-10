"""
Liquid-related Actions

Actions for interacting with the liquid coating system.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import random
import color
from actions import Action
from liquid_system import LiquidType

if TYPE_CHECKING:
    from entity import Actor


class SpillLiquidAction(Action):
    """Action to spill liquid at the entities location."""
    
    def __init__(self, entity: Actor, liquid_type: LiquidType, amount: int = 2):
        super().__init__(entity) 
        self.liquid_type = liquid_type
        self.amount = amount
    
    def perform(self) -> None:
        """Spill liquid at the entity's current position."""
        x, y = self.entity.x, self.entity.y
        
        if hasattr(self.engine.game_map, 'liquid_system'):
            self.engine.game_map.liquid_system.create_splash(
                x, y, self.liquid_type, radius=1, max_depth=self.amount
            )
            
            liquid_names = {
                LiquidType.WATER: "water",
                LiquidType.BLOOD: "blood", 
                LiquidType.OIL: "oil",
                LiquidType.SLIME: "slime"
            }
            
            self.engine.message_log.add_message(
                f"{self.entity.name} spills {liquid_names[self.liquid_type]}!",
                color.cyan
            )


class CleanLiquidAction(Action):
    """Action to clean liquid from the current tile."""
    
    def __init__(self, entity: Actor):
        super().__init__(entity)
    
    def perform(self) -> None:
        """Clean liquid from the entity's current position.""" 
        x, y = self.entity.x, self.entity.y
        
        if hasattr(self.engine.game_map, 'liquid_system'):
            coating = self.engine.game_map.liquid_system.get_coating(x, y)
            if coating:
                removed = self.engine.game_map.liquid_system.remove_liquid(x, y, amount=3)
                if removed:
                    self.engine.message_log.add_message(
                        f"{self.entity.name} cleans the liquid.", 
                        color.health_recovered
                    )
                else:
                    self.engine.message_log.add_message(
                        f"{self.entity.name} partially cleans the liquid.",
                        color.gray
                    )
            else:
                self.engine.message_log.add_message(
                    "There's no liquid here to clean.",
                    color.impossible
                )