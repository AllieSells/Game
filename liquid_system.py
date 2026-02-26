"""
Simple Liquid Coating System

A lightweight system for liquid coatings that modify existing tile graphics.
Focuses on visual appeal, modular design, and unified damage mechanics.

## Damage System:
- **Centralized Calculation**: All liquid damage (stepping, splashing) uses the same 
  `_calculate_liquid_damage()` method for consistency
- **Depth-Based Effects**: Deeper liquids cause more damage/healing
- **Immediate + Periodic**: Stepping/splashing causes immediate effect, then periodic 
  damage per turn while coated
- **Modular Effects**: Easy to add new liquid types with different damage multipliers
- **Healing Support**: Health potions use negative damage values for healing effects
"""

from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, TYPE_CHECKING
import random
import numpy as np
import sounds

if TYPE_CHECKING:
    from game_map import GameMap


class LiquidType(Enum):
    """Types of liquids that can coat tiles."""
    NONE = auto()
    WATER = auto()
    BLOOD = auto()
    OIL = auto()
    SLIME = auto()
    HEALTHPOTION = auto()
    POISON = auto()

    def get_coat_string(self) -> str:
        """Get a string representation of coating description."""
        descriptions = {
            LiquidType.NONE: "",
            LiquidType.WATER: "wet",
            LiquidType.BLOOD: "bloody",
            LiquidType.OIL: "oily",
            LiquidType.SLIME: "slimy",
            LiquidType.HEALTHPOTION: "",
            LiquidType.POISON: "poisoned"
        }
        return descriptions.get(self, "")
    
    def get_display_name(self) -> str:
        """Get the display name for this liquid type."""
        names = {
            LiquidType.NONE: "none",
            LiquidType.WATER: "water",
            LiquidType.BLOOD: "blood", 
            LiquidType.OIL: "oil",
            LiquidType.SLIME: "slime",
            LiquidType.HEALTHPOTION: "a light red liquid",
            LiquidType.POISON: "a pale green liquid"
        }
        return names.get(self, "unknown liquid")
    
    def get_display_color(self) -> Tuple[int, int, int]:
        """Get the display color for this liquid type."""
        import color  # Import here to avoid circular imports
        colors = {
            LiquidType.NONE: color.white,
            LiquidType.WATER: color.blue,
            LiquidType.BLOOD: color.red,
            LiquidType.OIL: color.yellow,
            LiquidType.SLIME: color.green,
            LiquidType.HEALTHPOTION: color.light_red,
            LiquidType.POISON: color.light_green
        }
        return colors.get(self, color.white)
    
    def get_evaporation_chance(self) -> float:
        """Get the evaporation chance per turn for this liquid type."""
        chances = {
            LiquidType.NONE: 0.0,  # No evaporation for no coating
            LiquidType.WATER: 0.05,    # 5% per turn (lasts ~20 turns)
            LiquidType.BLOOD: 0.06,    # 6% per turn (lasts ~17 turns)  
            LiquidType.OIL: 0.02,     # 2% per turn (lasts ~50 turns)
            LiquidType.SLIME: 0.01,   # 1% per turn (lasts ~100 turns)
            LiquidType.HEALTHPOTION: 0.1,  # 10% per turn (lasts ~10 turns)
            LiquidType.POISON: 0.33  # 33% per turn (lasts ~3 turns)
        }
        return chances.get(self, 0.001)


@dataclass
class LiquidCoating:
    """Represents a liquid coating on a tile.""" 
    liquid_type: LiquidType
    depth: int  # 1-3, affects appearance
    age: int = 0  # For aging/evaporation effects
    original_tile: Optional[np.ndarray] = None  # Store original tile data
    
    def get_char(self) -> int:
        """Get ASCII character code based on liquid type and depth."""
        chars = {
            LiquidType.WATER: [ord("˙"), ord("·"), ord("~")],
            LiquidType.BLOOD: [ord("˙"), ord("·"), ord("~")],
            LiquidType.OIL: [ord("˙"), ord("·"), ord("~")], 
            LiquidType.SLIME: [ord("˙"), ord("·"), ord("∿")],
            LiquidType.HEALTHPOTION: [ord("`"), ord("·"), ord("~")],
            LiquidType.POISON: [ord("`"), ord("·"), ord("~")]
        }
        
        char_list = chars[self.liquid_type]
        index = min(self.depth - 1, len(char_list) - 1)
        return char_list[index]
    
    def get_color(self, is_light: bool = True) -> Tuple[int, int, int]:
        """Get color based on liquid type and lighting."""
        colors = {
            LiquidType.WATER: {
                'dark': (0, 40, 80),
                'light': (30, 80, 150)
            },
            LiquidType.BLOOD: {
                'dark': (80, 0, 0), 
                'light': (150, 20, 20)
            },
            LiquidType.OIL: {
                'dark': (40, 30, 0),
                'light': (80, 60, 10)
            },
            LiquidType.SLIME: {
                'dark': (30, 60, 30),
                'light': (50, 120, 50)
            },
            LiquidType.HEALTHPOTION: {
                'dark': (110, 57, 57),
                'light': (242, 135, 135)
            },
            LiquidType.POISON: {
                'dark': (57, 110, 57),
                'light': (135, 242, 135)
            }
        }
        
        base_color = colors[self.liquid_type]['light' if is_light else 'dark']
        
        # Modify intensity based on depth
        intensity = min(1.0, 0.5 + (self.depth * 0.3))
        return tuple(int(c * intensity) for c in base_color)
    
    def get_bg_color(self, original_bg: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """Get background color blended with original."""
        liquid_color = self.get_color(True)
        blend_factor = min(0.4, self.depth * 0.15)  # Subtle background tinting
        
        return tuple(
            int(original_bg[i] * (1 - blend_factor) + liquid_color[i] * blend_factor)
            for i in range(3)
        )


class LiquidSystem:
    """Manages liquid coatings on the game map."""
    
    def __init__(self, game_map: GameMap):
        self.game_map = game_map
        # Position -> LiquidCoating mapping
        self.coatings: Dict[Tuple[int, int], LiquidCoating] = {}

    def spill_volume(self, x: int, y: int, liquid_type: LiquidType, volume: int) -> None:
        """Spill a volume of liquid at a location, creating a splash pattern."""
        self.create_splash(x, y, liquid_type, radius=2, max_depth=min(3, volume))

        
    
    def add_liquid(self, x: int, y: int, liquid_type: LiquidType, depth: int = 1) -> None:
        """Add liquid coating to a tile."""
        if not self.game_map.in_bounds(x, y):
            return
        
        # Only coat walkable tiles
        if not self.game_map.tiles['walkable'][x, y]:
            return
            
        pos = (x, y)
        
        if pos in self.coatings:
            # Add to existing coating
            existing = self.coatings[pos]
            if existing.liquid_type == liquid_type:
                existing.depth = min(existing.depth + depth, 3)
                self._update_tile_graphics(x, y, existing)
            else:
                # Replace with new liquid if different type
                self._restore_original_tile(x, y)
                coating = LiquidCoating(liquid_type, depth)
                self._store_original_tile(x, y, coating)
                self.coatings[pos] = coating
                self._update_tile_graphics(x, y, coating)
        else:
            # New coating
            coating = LiquidCoating(liquid_type, min(depth, 3))
            self._store_original_tile(x, y, coating)
            self.coatings[pos] = coating
            self._update_tile_graphics(x, y, coating)
    
    def remove_liquid(self, x: int, y: int, amount: int = 1) -> bool:
        """Remove liquid coating. Returns True if coating was removed."""
        pos = (x, y)
        if pos not in self.coatings:
            return False
        
        coating = self.coatings[pos]
        coating.depth -= amount
        
        if coating.depth <= 0:
            self._restore_original_tile(x, y)
            del self.coatings[pos]
            return True
        else:
            self._update_tile_graphics(x, y, coating)
            return False
    
    def _store_original_tile(self, x: int, y: int, coating: LiquidCoating) -> None:
        """Store the original tile data before applying liquid."""
        coating.original_tile = self.game_map.tiles[x, y].copy()
    
    def _restore_original_tile(self, x: int, y: int) -> None:
        """Restore the original tile data."""
        if (x, y) in self.coatings:
            coating = self.coatings[(x, y)]
            if coating.original_tile is not None:
                self.game_map.tiles[x, y] = coating.original_tile
    
    def _update_tile_graphics(self, x: int, y: int, coating: LiquidCoating) -> None:
        """Update the tile's graphics to show the liquid coating."""
        if coating.original_tile is None:
            return
        
        # Get original character and foreground colors (preserve these)
        orig_char = coating.original_tile["dark"]["ch"]
        orig_fg_dark = tuple(coating.original_tile["dark"]["fg"])
        orig_fg_light = tuple(coating.original_tile["light"]["fg"])
        
        # Get original background colors for blending
        orig_bg_dark = tuple(coating.original_tile["dark"]["bg"])
        orig_bg_light = tuple(coating.original_tile["light"]["bg"])
        
        # Blend background colors with liquid (only modify background)
        liquid_bg_dark = coating.get_bg_color(orig_bg_dark)
        liquid_bg_light = coating.get_bg_color(orig_bg_light)
        
        # Update tile graphics
        current_tile = self.game_map.tiles[x, y]
        
        # Create new tile preserving original character and foreground, only changing background
        new_tile = (
            current_tile["light_level"],
            current_tile["name"],
            current_tile["walkable"],
            current_tile["transparent"],
            np.array((orig_char, orig_fg_dark, liquid_bg_dark), dtype=current_tile["dark"].dtype),
            np.array((orig_char, orig_fg_light, liquid_bg_light), dtype=current_tile["light"].dtype),
            current_tile["interactable"]
        )
        
        self.game_map.tiles[x, y] = new_tile
    
    def get_coating(self, x: int, y: int) -> Optional[LiquidCoating]:
        """Get liquid coating at position."""
        return self.coatings.get((x, y))
    
    def create_splash(self, center_x: int, center_y: int, liquid_type: LiquidType, 
                     radius: int = 2, max_depth: int = 2) -> None:
        """Create a splash pattern around a center point."""
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                x, y = center_x + dx, center_y + dy
                
                if not self.game_map.in_bounds(x, y):
                    continue
                
                distance = (dx * dx + dy * dy) ** 0.5
                if distance <= radius:
                    # Deeper liquid closer to center
                    depth = max(1, max_depth - int(distance))
                    if random.random() < 0.8:  # Some randomness
                        self.add_liquid(x, y, liquid_type, depth)
                    
                    # Coat random body parts on entities in splash area
                    self._coat_entities_in_splash(x, y, liquid_type, distance, radius)

    def _coat_entities_in_splash(self, x: int, y: int, liquid_type: LiquidType, 
                                distance: float, radius: int) -> None:
        """Coat random body parts on entities caught in liquid splash."""
        # Find entities at this position
        entities_here = [e for e in self.game_map.entities if e.x == x and e.y == y]
        
        for entity in entities_here:
            if not (hasattr(entity, 'body_parts') and entity.body_parts):
                continue
                
            # Calculate coating chance based on distance from center (closer = higher chance)
            base_chance = 0.8 - (distance / radius) * 0.4  # 80% at center, 40% at edge
            
            # Get all body parts that can be coated
            all_parts = list(entity.body_parts.body_parts.values())
            
            # Determine how many parts to potentially coat (more for closer entities)
            max_parts_to_coat = max(1, int(len(all_parts) * (0.5 - distance / radius * 0.3)))
            
            # Randomly select parts to coat
            parts_to_check = random.sample(all_parts, min(max_parts_to_coat, len(all_parts)))
            
            coated_parts = []
            for part in parts_to_check:
                if random.random() < base_chance:
                    # Don't overwrite existing coatings unless it's the same type
                    if part.coating == LiquidType.NONE or part.coating == liquid_type:
                        part.coating = liquid_type
                        part.coating_age = 0
                        coated_parts.append(part.name)
                        
                        # Apply immediate liquid effect for splash damage
                        splash_depth = max(1, int(3 * (1 - distance / radius)))  # More depth closer to center
                        self._apply_liquid_effect(entity, liquid_type, splash_depth, part)
            
            # Show message if any parts were coated and this is the player
            if coated_parts and entity == self.game_map.engine.player:
                if len(coated_parts) == 1:
                    message = f"The {liquid_type.get_display_name()} splashes onto your {coated_parts[0]}!"
                else:
                    parts_text = ", ".join(coated_parts[:-1]) + f" and {coated_parts[-1]}"
                    message = f"The {liquid_type.get_display_name()} splashes onto your {parts_text}!"
                
                import color
                self.game_map.engine.message_log.add_message(message, color.cyan)
    
    def create_trail(self, start_x: int, start_y: int, end_x: int, end_y: int, 
                    liquid_type: LiquidType, width: int = 1) -> None:
        """Create a trail of liquid between two points."""
        # Simple line drawing algorithm
        dx = abs(end_x - start_x)
        dy = abs(end_y - start_y)
        sx = 1 if start_x < end_x else -1
        sy = 1 if start_y < end_y else -1
        err = dx - dy
        
        x, y = start_x, start_y
        
        while True:
            # Add liquid with some width
            for w_dx in range(-width, width + 1):
                for w_dy in range(-width, width + 1):
                    tx, ty = x + w_dx, y + w_dy
                    if self.game_map.in_bounds(tx, ty) and random.random() < 0.7:
                        self.add_liquid(tx, ty, liquid_type, 1)
            
            if x == end_x and y == end_y:
                break
                
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
    def _calculate_liquid_damage(self, liquid_type: LiquidType, depth: int, base_multiplier: int = 1) -> int:
        """Calculate damage amount based on liquid type and depth."""
        damage_multipliers = {
            LiquidType.POISON: 1,
            LiquidType.NONE: 0,
            LiquidType.WATER: 0,
            LiquidType.BLOOD: 0,
            LiquidType.OIL: 0,
            LiquidType.SLIME: 0,
            LiquidType.HEALTHPOTION: -1,  # Negative for healing
        }
        
        multiplier = damage_multipliers.get(liquid_type, 0)
        return base_multiplier * multiplier * depth
    
    def _apply_liquid_effect(self, target, liquid_type: LiquidType, depth: int, 
                           affected_body_part=None) -> None:
        """Apply liquid effect (damage/healing) to target."""
        if not hasattr(target, 'fighter') or not target.fighter:
            return
            
        damage = self._calculate_liquid_damage(liquid_type, depth)
        
        if damage == 0:
            return
            
        is_healing = damage < 0
        actual_damage = abs(damage)
        
        # Apply damage/healing
        if is_healing:
            target.fighter.heal(actual_damage)
            effect_verb = "heals"
            effect_type = "healing"
        else:
            # Damage the specific body part if provided
            if affected_body_part:
                target.fighter.take_damage(actual_damage, targeted_part=affected_body_part.part_type, causes_bleeding=False)
            else:
                target.fighter.take_damage(actual_damage, causes_bleeding=False)
            effect_verb = "burns" if liquid_type == LiquidType.POISON else "affects"
            effect_type = "damage"
        
        # Generate appropriate message
        liquid_name = liquid_type.get_display_name().capitalize()
        if affected_body_part:
            message = f"{liquid_name} on your {affected_body_part.name} {effect_verb} you for {actual_damage} {effect_type}!"
        else:
            message = f"You take {actual_damage} {liquid_name} {effect_type}!"
        
        # Play appropriate sound
        if liquid_type == LiquidType.POISON and not is_healing:
            sounds.play_poison_burn_sound()
        
        # Show message for player
        if target == self.game_map.engine.player:
            import color
            message_color = color.health_recovered if is_healing else color.status_effect_applied
            self.game_map.engine.message_log.add_message(message, message_color)
    
    def tick_liquid_effects(self, target, coating, affected_body_part=None) -> None:
        """Apply any effects from the liquid coating to the target (e.g., poison damage)."""
        # Handle both LiquidCoating objects and LiquidType enums
        if isinstance(coating, LiquidCoating):
            liquid_type = coating.liquid_type
            depth = coating.depth
        else:
            # Assume it's a LiquidType enum (from body part coatings)
            liquid_type = coating
            # Get depth from ground liquid at target's position or default to 1
            ground_coating = self.get_coating(target.x, target.y)
            depth = ground_coating.depth if ground_coating and ground_coating.liquid_type == liquid_type else 1
        
        self._apply_liquid_effect(target, liquid_type, depth, affected_body_part)
    
    def tick_liquid(self) -> None:
        """Process liquid aging and evaporation."""
        to_remove = []
        
        for pos, coating in list(self.coatings.items()):
            coating.age += 1
            
            # Use liquid type's built-in evaporation chance
            if random.random() < coating.liquid_type.get_evaporation_chance():
                coating.depth -= 1
                if coating.depth <= 0:
                    to_remove.append(pos)
                else:
                    # Update graphics for reduced depth
                    x, y = pos
                    self._update_tile_graphics(x, y, coating)
        
        for pos in to_remove:
            x, y = pos
            self._restore_original_tile(x, y)
            del self.coatings[pos]
    
    def cleanup(self) -> None:
        """Clean up all liquid coatings and restore original tiles."""
        for pos in list(self.coatings.keys()):
            x, y = pos
            self._restore_original_tile(x, y)
        self.coatings.clear()