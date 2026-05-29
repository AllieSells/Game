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
import math
from typing import Dict, Tuple, Optional, TYPE_CHECKING
import random
import numpy as np
from components.effect import BurningEffect, PoisonEffect
import sounds
import sprite_manager

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
    FIRE = auto()

    def get_coat_string(self) -> str:
        """Get a string representation of coating description."""
        descriptions = {
            LiquidType.NONE: "",
            LiquidType.WATER: "wet",
            LiquidType.BLOOD: "bloody",
            LiquidType.OIL: "oily",
            LiquidType.SLIME: "slimy",
            LiquidType.HEALTHPOTION: "",
            LiquidType.POISON: "poisoned",
            LiquidType.FIRE: "burning"
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
            LiquidType.POISON: "a pale green liquid",
            LiquidType.FIRE: "fire"
        }
        return names.get(self, "unknown liquid")
    
    def get_display_color(self) -> Tuple[int, int, int]:
        """Get the display color for this liquid type."""
        import color  # Import here to avoid circular imports
        colors = {
            LiquidType.NONE: color.white,
            LiquidType.WATER: color.blue,
            LiquidType.BLOOD: color.dark_red,
            LiquidType.OIL: color.yellow,
            LiquidType.SLIME: color.green,
            LiquidType.HEALTHPOTION: color.light_red,
            LiquidType.POISON: color.light_green,
            LiquidType.FIRE: (255, 85, 23)
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
            LiquidType.POISON: 0.1,  # 10% per turn (lasts ~10 turns)
            LiquidType.FIRE: 0.05  # 5% per turn (lasts ~20 turns)
        }
        return chances.get(self, 0.001)


@dataclass
class LiquidCoating:
    """Represents a liquid coating on a tile.""" 
    liquid_type: LiquidType
    depth: int  # 1-3, affects appearance
    age: int = 0  # For aging/evaporation effects
    original_tile: Optional[np.ndarray] = None  # Store original tile data
    pos: Tuple[int, int] = (0, 0) 
    
    def get_char(self) -> int:
        """Get ASCII character code based on liquid type and depth."""
        chars = {
            LiquidType.WATER: [ord("˙"), ord("·"), ord("~")],
            LiquidType.BLOOD: [ord("˙"), ord("·"), ord("~")],
            LiquidType.OIL: [ord("˙"), ord("·"), ord("~")], 
            LiquidType.SLIME: [ord("˙"), ord("·"), ord("∿")],
            LiquidType.HEALTHPOTION: [ord("`"), ord("·"), ord("~")],
            LiquidType.POISON: [ord("`"), ord("·"), ord("~")],
            LiquidType.FIRE: [ord("'"), ord("·"), ord("x")]
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
            },
            LiquidType.FIRE: {
                'dark': (255, 85, 23),
                'light': (255, 85, 23)
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
    
    def get_pos(self) -> Tuple[int, int]:
        """Get the position of this coating based on original tile data."""
        if self.original_tile is not None:
            return self.pos
        return (0, 0)  # Default position if original tile is not set

class LiquidSystem:
    """Manages liquid coatings on the game map."""

    def __init__(self, game_map: GameMap):
        self.game_map = game_map
        # Position -> LiquidCoating mapping
        self.coatings: Dict[Tuple[int, int], LiquidCoating] = {}
        # Batch-update state: when _batch_mode is True, _update_tile_graphics
        # defers work into _pending_tile_updates instead of running immediately.
        self._batch_mode: bool = False
        self._pending_tile_updates: set = set()

    def spill_volume(self, x: int, y: int, liquid_type: LiquidType, volume: int) -> None:
        """Spill a volume of liquid at a location, creating a splash pattern."""
        self.create_splash(x, y, liquid_type, radius=2, max_depth=min(3, volume))

        
    
    # Tile names considered "water" — blood/other coatings are suppressed on these.
    _WATER_TILE_NAMES = frozenset({"Water", "Ocean", "River", "Shore"})

    def add_liquid(self, x: int, y: int, liquid_type: LiquidType, depth: int = 1) -> None:
        """Add liquid coating to a tile."""
        if not self.game_map.in_bounds(x, y):
            return

        # Don't place blood (or any coating) on top of water tiles.
        tile_name = str(self.game_map.tiles['name'][x, y])
        if tile_name in self._WATER_TILE_NAMES:
            return

        # Only coat walkable tiles
        if not self.game_map.tiles['walkable'][x, y]:
            return
            
        pos = (x, y)
        
        if pos in self.coatings:
            # Add to existing coating
            existing = self.coatings[pos]
            if existing.liquid_type == liquid_type:
                old_depth = existing.depth
                existing.depth = min(existing.depth + depth, 3)
                if existing.depth != old_depth:
                    self._update_tile_graphics(x, y, existing)
                # depth unchanged (already at max) — no visual update needed
            else:
                # Replace with new liquid if different type
                self._restore_original_tile(x, y)
                coating = LiquidCoating(liquid_type, depth, pos=pos)
                self._store_original_tile(x, y, coating)
                self.coatings[pos] = coating
                self._update_tile_graphics(x, y, coating)
        else:
            # New coating
            coating = LiquidCoating(liquid_type, min(depth, 3), pos=pos)
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
            # Refresh all 8 neighbours so diagonal pulls update too.
            for nx, ny in (
                (x,     y - 1), (x,     y + 1), (x - 1, y    ), (x + 1, y    ),
                (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1),
            ):
                if (nx, ny) in self.coatings:
                    self._update_tile_graphics(nx, ny, self.coatings[(nx, ny)], _refresh_neighbors=False)
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
    
    def _begin_batch(self) -> None:
        """Start batching tile graphic updates. Calls to _update_tile_graphics are deferred."""
        self._batch_mode = True
        self._pending_tile_updates = set()

    def _end_batch(self) -> None:
        """Flush all deferred tile graphic updates, including their neighbours, deduplicated."""
        self._batch_mode = False
        # Expand pending set to include neighbours so blob connectivity is correct.
        to_update = set(self._pending_tile_updates)
        for x, y in self._pending_tile_updates:
            for nx, ny in (
                (x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y),
                (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1),
            ):
                if (nx, ny) in self.coatings:
                    to_update.add((nx, ny))
        self._pending_tile_updates = set()
        for x, y in to_update:
            if (x, y) in self.coatings:
                self._update_tile_graphics(x, y, self.coatings[(x, y)], _refresh_neighbors=False)

    def _update_tile_graphics(self, x: int, y: int, coating: LiquidCoating, _refresh_neighbors: bool = True) -> None:
        """Update the tile's graphics to show the liquid coating via procedural sprite compositing."""
        if self._batch_mode:
            self._pending_tile_updates.add((x, y))
            return
        if coating.original_tile is None:
            return

        orig_char = int(coating.original_tile["dark"]["ch"])

        # All 8-neighbour connectivity drives blob shape and diagonal pulls.
        has_top    = (x,     y - 1) in self.coatings
        has_bottom = (x,     y + 1) in self.coatings
        has_left   = (x - 1, y    ) in self.coatings
        has_right  = (x + 1, y    ) in self.coatings
        has_tl     = (x - 1, y - 1) in self.coatings
        has_tr     = (x + 1, y - 1) in self.coatings
        has_bl     = (x - 1, y + 1) in self.coatings
        has_br     = (x + 1, y + 1) in self.coatings

        tint = coating.liquid_type.get_display_color()

        puddle_char = sprite_manager.get_puddle_sprite(
            x, y,
            has_top, has_bottom, has_left, has_right,
            has_tl, has_tr, has_bl, has_br,
            tint, coating.depth,
        )

        # Use compose_puddle_tile so the tile+puddle composite reuses its
        # per-position slot instead of allocating a new one every evaporation tick.
        composite_char = sprite_manager.compose_puddle_tile(x, y, orig_char, ord(puddle_char))
        composite_cp = ord(composite_char)

        current_tile = self.game_map.tiles[x, y]
        orig_bg_dark  = tuple(coating.original_tile["dark"]["bg"])
        orig_bg_light = tuple(coating.original_tile["light"]["bg"])
        white = (255, 255, 255)

        new_tile = (
            current_tile["light_level"],
            current_tile["name"],
            current_tile["walkable"],
            current_tile["transparent"],
            np.array((composite_cp, white, orig_bg_dark),  dtype=current_tile["dark"].dtype),
            np.array((composite_cp, white, orig_bg_light), dtype=current_tile["light"].dtype),
            current_tile["interactable"],
            current_tile["type"],
            current_tile["direction"],
        )
        self.game_map.tiles[x, y] = new_tile

        # Refresh all 8 neighbours so diagonal pulls stay consistent.
        if _refresh_neighbors:
            for nx, ny in (
                (x,     y - 1), (x,     y + 1), (x - 1, y    ), (x + 1, y    ),
                (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1),
            ):
                if (nx, ny) in self.coatings:
                    self._update_tile_graphics(nx, ny, self.coatings[(nx, ny)], _refresh_neighbors=False)
    
    def get_coating(self, x: int, y: int) -> Optional[LiquidCoating]:
        """Get liquid coating at position."""
        return self.coatings.get((x, y))
    
    # Liquid types that can actively affect entities (cause damage/healing/effects).
    # Inert types (BLOOD, WATER, OIL, SLIME) skip the costly entity-coating scan.
    _HAZARDOUS_LIQUIDS = frozenset({LiquidType.FIRE, LiquidType.POISON, LiquidType.HEALTHPOTION})
    _SPLASH_OFFSETS_CACHE: Dict[int, list[tuple[int, int, int]]] = {}

    @classmethod
    def _get_splash_offsets(cls, radius: int) -> list[tuple[int, int, int]]:
        """Return cached (dx, dy, dist_sq) offsets inside a circular splash radius."""
        r = max(0, int(radius))
        cached = cls._SPLASH_OFFSETS_CACHE.get(r)
        if cached is not None:
            return cached

        radius_sq = r * r
        offsets: list[tuple[int, int, int]] = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                dist_sq = dx * dx + dy * dy
                if dist_sq <= radius_sq:
                    offsets.append((dx, dy, dist_sq))

        cls._SPLASH_OFFSETS_CACHE[r] = offsets
        return offsets

    def create_spray(self, start_x: int, start_y: int, direction: Tuple[int, int], liquid_type: LiquidType
                        , length: int = 5) -> None:
        """Create a directional spray pattern from a starting point."""
        coat_entities = liquid_type in self._HAZARDOUS_LIQUIDS
        entity_pos_map = None
        if coat_entities:
            entity_pos_map = {}
            for e in self.game_map.entities:
                entity_pos_map.setdefault((e.x, e.y), []).append(e)

        dx, dy = direction
        self._begin_batch()
        try:
            # omit the starting tile to avoid coating the source of the spray (e.g., player or monster)
            for i in range(1, length):
                x, y = start_x + dx * i, start_y + dy * i
                if not self.game_map.in_bounds(x, y):
                    break
                self.add_liquid(x, y, liquid_type, depth=1)
                if random.random() < 0.3:  # Random splatter around main spray line
                    splatter_x = x + random.randint(-1, 1)
                    splatter_y = y + random.randint(-1, 1)
                    if self.game_map.in_bounds(splatter_x, splatter_y):
                        self.add_liquid(splatter_x, splatter_y, liquid_type, depth=1)
                # Only scan/coat entities for liquids that can harm or heal them
                if coat_entities:
                    self._coat_entities_in_splash(x, y, liquid_type, distance=0, radius=1, entity_pos_map=entity_pos_map)
        finally:
            self._end_batch()


    def create_splash(self, center_x: int, center_y: int, liquid_type: LiquidType,
                     radius: int = 2, max_depth: int = 2, fill_chance: float = 0.8) -> None:
        """Create a splash pattern around a center point."""
        coat_entities = liquid_type in self._HAZARDOUS_LIQUIDS
        # Build position map once instead of O(E) scan per tile.
        entity_pos_map = None
        if coat_entities:
            entity_pos_map = {}
            for e in self.game_map.entities:
                entity_pos_map.setdefault((e.x, e.y), []).append(e)

        self._begin_batch()
        try:
            splash_offsets = self._get_splash_offsets(radius)
            clamped_fill = max(0.0, min(1.0, float(fill_chance)))
            for dx, dy, dist_sq in splash_offsets:
                x, y = center_x + dx, center_y + dy
                if not self.game_map.in_bounds(x, y):
                    continue

                if clamped_fill < 1.0 and random.random() >= clamped_fill:
                    continue

                # Deeper liquid closer to center; integer sqrt is cheaper than float sqrt.
                depth = max(1, max_depth - math.isqrt(dist_sq))
                self.add_liquid(x, y, liquid_type, depth)

                # Only scan/coat entities for liquids that can harm or heal them.
                if coat_entities:
                    distance = math.sqrt(dist_sq)
                    self._coat_entities_in_splash(x, y, liquid_type, distance, radius, entity_pos_map)
        finally:
            self._end_batch()

    def _coat_entities_in_splash(self, x: int, y: int, liquid_type: LiquidType,
                                distance: float, radius: int,
                                entity_pos_map: Optional[dict] = None) -> None:
        """Coat random body parts on entities caught in liquid splash."""
        if entity_pos_map is not None:
            entities_here = entity_pos_map.get((x, y), [])
        else:
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

            # Apply immediate splash effect once per affected entity, not once per coated body part.
            if coated_parts:
                splash_depth = max(1, int(3 * (1 - distance / radius)))  # More depth closer to center
                self._apply_liquid_effect(entity, liquid_type, splash_depth)
            
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
            LiquidType.FIRE: 2
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
        
        # Determine damage type for resistances
        from components.damage_types import DamageType
        import actions
        
        damage_type_map = {
            LiquidType.FIRE: DamageType.FIRE,
            LiquidType.POISON: DamageType.POISON,
        }
        
        # Check if target is immune to this damage type
        liquid_damage_type = damage_type_map.get(liquid_type, DamageType.NONE)
        if not is_healing and liquid_damage_type != DamageType.NONE:
            if hasattr(target, 'damage_resistances') and target.damage_resistances:
                for res_type, res_value in target.damage_resistances:
                    if res_type == liquid_damage_type and res_value == 0.0:
                        return  # Immune, skip all effects and messages
        
        # Apply damage/healing
        if is_healing:
            target.fighter.heal(actual_damage)
            effect_verb = "heals"
            effect_type = "healing"
            final_damage = actual_damage  # Track final amount for message
        else:
            effect_verb = "burns" if liquid_type == LiquidType.POISON or liquid_type == LiquidType.FIRE else "affects"
            effect_type = "damage"
            
            # Apply typed damage for resistances
            liquid_damage_type = damage_type_map.get(liquid_type, DamageType.NONE)
            final_damage = actions.apply_typed_damage(target, actual_damage, liquid_damage_type)
            
            # If fully resisted, don't show message or apply effects
            if final_damage == 0:
                return
            
            # For fire and poison, apply via effect (shows indicator + deals damage over time)
            if liquid_type == LiquidType.FIRE:
                effect = BurningEffect(amount=final_damage, duration=1)
                if hasattr(self.game_map.engine, "add_or_refresh_effect"):
                    self.game_map.engine.add_or_refresh_effect(target, effect)
                else:
                    has_same_effect = any(isinstance(existing, effect.__class__) for existing in getattr(target, "effects", []))
                    if not has_same_effect:
                        target.effects.append(effect)
            elif liquid_type == LiquidType.POISON:
                effect = PoisonEffect(amount=final_damage, duration=5)
                if hasattr(self.game_map.engine, "add_or_refresh_effect"):
                    self.game_map.engine.add_or_refresh_effect(target, effect)
                else:
                    has_same_effect = any(isinstance(existing, effect.__class__) for existing in getattr(target, "effects", []))
                    if not has_same_effect:
                        target.effects.append(effect)
            else:
                # Other liquids: apply immediate damage
                causes_bleeding = True
                target.fighter.take_damage(final_damage, causes_bleeding=causes_bleeding)
            
            self.game_map.engine.debug_log(f"Applied {liquid_type.name} effect to {target.name} for {final_damage} damage.", handler=type(self).__name__, event="combat")
        
        # Generate appropriate message (only if damage/healing occurred)
        liquid_name = liquid_type.get_display_name().capitalize()
        if affected_body_part:
            message = f"The {liquid_name.lower()} on your {affected_body_part.name} {effect_verb} you for {final_damage} {effect_type}!"
        else:
            message = f"You take {final_damage} {liquid_name} {effect_type}!"
        
        # Play appropriate sound
        if liquid_type == LiquidType.POISON and not is_healing:
            sounds._play_burn_sound_at(target.x, target.y, self.game_map.engine.player, self.game_map) 
        if liquid_type == LiquidType.FIRE and not is_healing:
            sounds._play_burn_sound_at(target.x, target.y, self.game_map.engine.player, self.game_map)
        
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
        to_refresh: set = set()

        for pos, coating in list(self.coatings.items()):
            coating.age += 1

            # Use liquid type's built-in evaporation chance
            if random.random() < coating.liquid_type.get_evaporation_chance():
                coating.depth -= 1
                if coating.depth <= 0:
                    to_remove.append(pos)
                else:
                    to_refresh.add(pos)

        for pos in to_remove:
            x, y = pos
            self._restore_original_tile(x, y)
            sprite_manager.release_puddle_slots(x, y)
            del self.coatings[pos]
            # Collect neighbours instead of updating immediately to avoid
            # re-updating the same tile when multiple adjacent tiles evaporate.
            for nx, ny in (
                (x,     y - 1), (x,     y + 1), (x - 1, y    ), (x + 1, y    ),
                (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1),
            ):
                if (nx, ny) in self.coatings:
                    to_refresh.add((nx, ny))

        # Single deduplicated pass over all tiles that need a graphics refresh.
        for pos in to_refresh:
            if pos in self.coatings:
                x, y = pos
                self._update_tile_graphics(x, y, self.coatings[pos], _refresh_neighbors=False)

    def cleanup(self) -> None:
        """Clean up all liquid coatings and restore original tiles."""
        for pos in list(self.coatings.keys()):
            x, y = pos
            self._restore_original_tile(x, y)
            sprite_manager.release_puddle_slots(x, y)
        self.coatings.clear()

    def refresh_all_graphics(self) -> None:
        """Regenerate all liquid tile graphics (e.g. after a puddle algorithm change).

        Clears the puddle sprite content-cache so every coating gets fresh
        pixels on the next _update_tile_graphics call, while reusing the same
        tileset slots (no new slots consumed).
        """
        sprite_manager.invalidate_all_puddle_sprites()
        for pos, coating in list(self.coatings.items()):
            x, y = pos
            self._update_tile_graphics(x, y, coating, _refresh_neighbors=False)