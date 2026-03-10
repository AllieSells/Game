from enum import Enum, auto
from random import random

from components.body_parts import BodyPart
from liquid_system import LiquidSystem, LiquidType
from typing import Dict, List, Optional, Set, TYPE_CHECKING


class Enchantment(Enum):
    FLAME = auto()


    def get_enchant_name(self):
        names = {
            Enchantment.FLAME: "Flaming"
        }
        return names.get(self, "Unknown")

    
    def get_color(self):
        colors = {
            Enchantment.FLAME: (255, 69, 0)  # Orange-red color for flame
        }
        return colors.get(self, (255, 255, 255))  # Default to white if not found
    
    def on_hit(self, engine, target, hit_part: Optional[BodyPart] = None):
        if self == Enchantment.FLAME:
            engine.message_log.add_message(f"Flames ignite the {target.name}!", (255, 69, 0))
            engine.game_map.liquid_system._coat_entities_in_splash(target.x, target.y, LiquidType.FIRE, distance=1, radius=1)

    def random_enchantment():
        enchants = list(Enchantment)
        return random.choice(enchants)
