from __future__ import annotations

from typing import Iterable, Iterator, Optional, TYPE_CHECKING
import numpy as np
from tcod.console import Console

import tile_types
from entity import Actor, Item
from render_order import RenderOrder
import color
from liquid_system import LiquidSystem

if TYPE_CHECKING:
    from engine import Engine
    from entity import Entity

class GameMap:
    def __init__(
            self, engine: Engine, width: int, height: int, entities: Iterable[Entity] = (), type: str = "dungeon", name: str = "Dungeon"
    ):
        self.engine = engine
        self.width, self.height = width, height
        self.entities = set(entities)
        self.type = type
        
        # Initialize tiles. For dungeon maps, populate per-tile using
        # tile_types.random_wall_tile() so we get variation (mossy walls etc.).
        if type == "dungeon":
            # Create an empty structured array and fill each cell with a
            # freshly generated wall tile to avoid sharing the same object.
            self.tiles = np.empty((width, height), dtype=tile_types.tile_dt, order="F")
            for x in range(width):
                for y in range(height):
                    # Place world borders around the edges
                    if x == 0 or x == width - 1 or y == 0 or y == height - 1:
                        self.tiles[x, y] = tile_types.world_border
                    else:
                        self.tiles[x, y] = tile_types.random_wall_tile()
        else:
            # Preserve original behavior for other map types.
            self.tiles = np.full((width, height), fill_value=tile_types.wall, order="F")

        self.visible = np.full(
            (width, height), fill_value=False, order="F")  # Tiles the player can see
        
        self.explored = np.full(
            (width, height), fill_value=False, order="F") # Tiles player has seen before
        
        self.downstairs_location = (0, 0)
        # Location of an upstairs tile on this map (if any).
        self.upstairs_location = (0, 0)
        self.type = type  # What type of map this is, e.g. "dungeon" or "village"
        self.name = name  # Name of this map, e.g. "Dungeon Level 1", "Oakwood"
        
        # Initialize liquid system
        self.liquid_system = LiquidSystem(self)
        
    @property
    def gamemap(self) -> GameMap:
        return self
        
    @property
    def actors(self) -> Iterator[Actor]:
        yield from (
            entity
            for entity in self.entities
            if isinstance(entity, Actor) and entity.is_alive
        )

    @property
    def items(self) -> Iterator[Item]:
        yield from (entity for entity in self.entities if isinstance(entity, Item))

    def get_blocking_entity_at_location(
            self, location_x: int, location_y: int) -> Optional[Entity]:
        for entity in self.entities:
            if (
                entity.blocks_movement
                and entity.x == location_x
                and entity.y == location_y
            ):
                return entity
        return None


    def in_bounds(self, x: int, y: int) -> bool:
        """Return True if x and y are inside of the map."""
        return 0 <= x < self.width and 0 <= y < self.height
    
    def _add_light_source(self, source_x: int, source_y: int, radius: int, max_intensity: float = 1.0) -> None:
        """Add light from a source with distance-based falloff and FOV blocking."""
        try:
            from tcod.map import compute_fov
            import tcod
            
            # Compute FOV to respect walls
            try:
                fov = compute_fov(
                    self.tiles["transparent"], (source_x, source_y),
                    radius=radius, algorithm=tcod.FOV_SHADOW
                )
            except Exception:
                # Fallback: simple distance without FOV if compute_fov fails
                xs = np.arange(0, self.width)
                ys = np.arange(0, self.height)
                dx = xs[:, None] - source_x
                dy = ys[None, :] - source_y
                dist = np.sqrt(dx * dx + dy * dy)
                fov = dist <= radius
            
            # Calculate distance-based light intensity for all tiles in FOV
            xs = np.arange(0, self.width)
            ys = np.arange(0, self.height)
            dx = xs[:, None] - source_x
            dy = ys[None, :] - source_y
            distance = np.sqrt(dx * dx + dy * dy)
            
            # Light falloff: intensity = max_intensity * (1 - distance / radius)^2
            # Only apply where FOV is true and distance <= radius
            mask = fov & (distance <= radius)
            light_intensity = np.where(
                mask,
                max_intensity * np.maximum(0, (1 - distance / radius) ** 2),
                0.0
            )
            
            # Add to existing light levels (lights accumulate)
            self.tiles["light_level"] = np.minimum(
                1.0,  # Cap at maximum brightness
                self.tiles["light_level"] + light_intensity
            )
            
        except Exception as e:
            # Fallback for any errors: simple distance-based lighting
            xs = np.arange(0, self.width)
            ys = np.arange(0, self.height)
            dx = xs[:, None] - source_x
            dy = ys[None, :] - source_y
            distance = np.sqrt(dx * dx + dy * dy)
            
            mask = distance <= radius
            light_intensity = np.where(
                mask,
                max_intensity * np.maximum(0, (1 - distance / radius) ** 2),
                0.0
            )
            
            self.tiles["light_level"] = np.minimum(
                1.0,
                self.tiles["light_level"] + light_intensity
            )
    
    def _apply_lighting_to_entity_color(self, entity_color: tuple, x: int, y: int) -> tuple:
        """Apply lighting effects to entity color based on tile light level."""
        try:
            # Get light level at entity position (0.0 = dark, 1.0 = full light)
            light_level = self.tiles["light_level"][x, y]
            light_level = float(light_level)  # Ensure it's a regular float
            light_level = max(0.0, min(1.0, light_level))  # Clamp between 0 and 1
            
            # Apply lighting: dark multiplier increases with light level
            # 0.2 = very dark (20% brightness), 1.0 = full brightness
            brightness = 0.2 + (0.8 * light_level)
            
            # Apply brightness to entity color
            r, g, b = entity_color
            lit_color = (
                int(r * brightness),
                int(g * brightness), 
                int(b * brightness)
            )
            return lit_color
        except Exception:
            # Fallback to original color if anything fails
            return entity_color
    
    def _render_tiles_with_gradient(self, console: Console) -> None:
        """Render tiles with gradient interpolation between dark and light based on light levels."""
        import tile_types
        
        # Get base tiles for different visibility states
        visible_mask = self.visible
        explored_mask = self.explored
        
        # Initialize all tiles with SHROUD
        result_tiles = np.full(
            (self.width, self.height), 
            tile_types.SHROUD, 
            dtype=console.tiles_rgb.dtype
        )
        
        # For explored areas, start with dark tiles
        dark_tiles = self.tiles["dark"]
        light_tiles = self.tiles["light"]
        
        # Get light levels only where player can see or has explored
        light_levels = self.tiles["light_level"]
        
        # Visible areas get gradient lighting
        if np.any(visible_mask):
            # Add small ambient light around player (3x3 area)
            try:
                px, py = self.engine.player.x, self.engine.player.y
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        tx, ty = px + dx, py + dy
                        if (0 <= tx < self.width and 0 <= ty < self.height 
                            and self.tiles[tx, ty]["transparent"]):
                            light_levels[tx, ty] = max(light_levels[tx, ty], 0.1)
            except Exception:
                pass
            
            # Interpolate between dark and light tiles based on light level
            vis_light_levels = light_levels[visible_mask].clip(0, 1)
            
            # Extract dark and light graphics for visible tiles
            vis_dark = dark_tiles[visible_mask]
            vis_light = light_tiles[visible_mask] 
            
            # Interpolate character (use light char if light level > 0.5, dark otherwise)
            result_chars = np.where(vis_light_levels > 0.5, vis_light['ch'], vis_dark['ch'])
            
            # Interpolate foreground and background colors
            dark_fg = vis_dark['fg'].astype(float)
            light_fg = vis_light['fg'].astype(float)
            dark_bg = vis_dark['bg'].astype(float)  
            light_bg = vis_light['bg'].astype(float)
            
            # Linear interpolation: dark + light_level * (light - dark)
            interp_fg = (dark_fg + vis_light_levels[:, np.newaxis] * (light_fg - dark_fg)).clip(0, 255).astype(np.uint8)
            interp_bg = (dark_bg + vis_light_levels[:, np.newaxis] * (light_bg - dark_bg)).clip(0, 255).astype(np.uint8)
            
            # Create interpolated tiles
            result_tiles[visible_mask] = np.array(
                list(zip(result_chars, interp_fg, interp_bg)), 
                dtype=console.tiles_rgb.dtype
            )
        
        # For explored but not visible areas, use dark tiles
        explored_not_visible = explored_mask & (~visible_mask)
        if np.any(explored_not_visible):
            result_tiles[explored_not_visible] = dark_tiles[explored_not_visible]
        
        # Apply to console
        console.tiles_rgb[0:self.width, 0:self.height] = result_tiles
    
    def render(self, console: Console) -> None:
        # Update tile lighting with gradient falloff based on distance to light sources  
        # Reset all tiles to zero light level first
        self.tiles["light_level"][:] = 0.0
        
        try:
            player = self.engine.player
            # Torch lighting: if player holds a Torch, light radius is 7
            try:
                weapon_name = player.equipment.weapon.name if player.equipment and player.equipment.weapon else None
            except Exception:
                weapon_name = None
            try:
                offhand_name = player.equipment.offhand.name if player.equipment and player.equipment.offhand else None
            except Exception:
                offhand_name = None

            has_torch = (weapon_name == "Torch" or offhand_name == "Torch")

            if has_torch:
                px, py = player.x, player.y
                self._add_light_source(px, py, radius=7, max_intensity=1.0)

            # Campfire and Bonfire lighting - doesn't affect FOV, only visual lighting
            try:
                for item in getattr(self, "items", []):
                    try:
                        if item.name == "Campfire":
                            cx, cy = item.x, item.y
                            # Only apply lighting if item is within map bounds
                            if not (0 <= cx < self.width and 0 <= cy < self.height):
                                continue
                            self._add_light_source(cx, cy, radius=5, max_intensity=0.8)
                        elif item.name == "Bonfire":
                            bx, by = item.x, item.y
                            # Only apply lighting if item is within map bounds
                            if not (0 <= bx < self.width and 0 <= by < self.height):
                                continue
                            self._add_light_source(bx, by, radius=15, max_intensity=1.0)
                    except Exception:
                        continue
            except Exception:
                pass
        except Exception:
            self.tiles["light_level"][:] = 0.0

        # Render tiles with gradient lighting based on light levels
        self._render_tiles_with_gradient(console)
        
        # ANIM RENDER AREA
        if hasattr(self.engine, "animation_queue"):
            # First render priority 0 (under everything).
            for anim in list(self.engine.animation_queue):
                anim_priority = getattr(anim, "render_priority", None)
                if anim_priority is None:
                    anim_priority = 2 if getattr(anim, "draw_above", False) else 0
                if anim_priority != 0:
                    continue
                try:
                    anim.tick(console, self)
                except Exception:
                    pass

        entities_sorted_for_rendering = sorted(self.entities, key=lambda x: x.render_order.value)

        # Render non-actor entities first (corpses, items)
        drawn_positions = set()
        for entity in entities_sorted_for_rendering:
            if entity.render_order == RenderOrder.ACTOR:
                continue
            pos = (entity.x, entity.y)
            if self.visible[entity.x, entity.y]:
                # Apply dynamic lighting to entity color
                lit_color = self._apply_lighting_to_entity_color(entity.color, entity.x, entity.y)
                console.print(x=entity.x, y=entity.y, string=entity.char, fg=lit_color)
                drawn_positions.add(pos)
            else:
                # If tile has been explored but is not currently visible, show a generic marker
                # Only show last-known marker for Items (not corpses or other non-actors)
                if self.explored[entity.x, entity.y] and pos not in drawn_positions and isinstance(entity, Item):
                    try:
                        console.print(x=entity.x, y=entity.y, string="*", fg=color.gray)
                        drawn_positions.add(pos)
                    except Exception:
                        try:
                            console.print(x=entity.x, y=entity.y, string="*", fg=(192,192,192))
                            drawn_positions.add(pos)
                        except Exception:
                            pass

        # Now render priority 1 animations (between items and actors)
        if hasattr(self.engine, "animation_queue"):
            for anim in list(self.engine.animation_queue):
                anim_priority = getattr(anim, "render_priority", None)
                if anim_priority is None:
                    anim_priority = 2 if getattr(anim, "draw_above", False) else 0
                if anim_priority != 1:
                    continue
                try:
                    anim.tick(console, self)
                except Exception:
                    pass

        # Finally render actors on top of the priority-1 animations
        for entity in entities_sorted_for_rendering:
            if entity.render_order != RenderOrder.ACTOR:
                continue
            pos = (entity.x, entity.y)
            if self.visible[entity.x, entity.y]:
                # Apply dynamic lighting to entity color
                lit_color = self._apply_lighting_to_entity_color(entity.color, entity.x, entity.y)
                console.print(x=entity.x, y=entity.y, string=entity.char, fg=lit_color)
                drawn_positions.add(pos)
            else:
                # Do not show '*' for non-visible actors; items already handled above.
                pass
        # Finally render priority 2 animations (above actors)
        if hasattr(self.engine, "animation_queue"):
            for anim in list(self.engine.animation_queue):
                anim_priority = getattr(anim, "render_priority", None)
                if anim_priority is None:
                    anim_priority = 2 if getattr(anim, "draw_above", False) else 0
                if anim_priority != 2:
                    continue
                try:
                    anim.tick(console, self)
                except Exception:
                    pass
        # (removed duplicate final darkening pass — we darken once above)
            
    def get_actor_at_location(self, x: int, y: int) -> Optional[Actor]:
        for actor in self.actors:
            if actor.x == x and actor.y == y:
                return actor
            
        return None
    
class GameWorld:
    # settings for GameMap and generates new maps when moving down

    def __init__(
            self,
            *,
            engine: Engine,
            map_width: int,
            map_height: int,
            max_rooms: int,
            room_min_size: int,
            room_max_size: int,
            current_floor: int = 0
        ):
            self.engine = engine

            self.map_width = map_width
            self.map_height = map_height

            self.max_rooms = max_rooms

            self.room_min_size = room_min_size
            self.room_max_size = room_max_size

            self.current_floor = current_floor
            self.floors_since_village = 0  # Track floors since last village
            # Stacks to support navigating between previously visited maps.
            # up_stack: maps above the current map (you can ascend to these)
            # down_stack: maps below the current map (you can descend to these if you previously ascended)
            # Each entry is a tuple: (gamemap, player_xy, floor_number)
            self.up_stack: list[tuple] = []
            self.down_stack: list[tuple] = []
            self.fungi = []  # Global list of fungi in the world

    def generate_floor(self) -> None:
        from procgen import generate_dungeon, generate_village
        import random

        self.current_floor += 1
        self.floors_since_village += 1

        # Clear any pending animations when moving to a new floor so
        # animations from the previous level don't carry over.
        try:
            if hasattr(self.engine, "animation_queue"):
                try:
                    self.engine.animation_queue.clear()
                except Exception:
                    # Fallback: remove items one-by-one
                    try:
                        while self.engine.animation_queue:
                            self.engine.animation_queue.popleft()
                    except Exception:
                        pass
        except Exception:
            pass

        # Calculate village probability for average village by floor 3
        # Using geometric distribution: E[X] = 1/p = 3, so p = 1/3 ≈ 0.333
        #
        # Village equation chance
        village_chance = ((self.floors_since_village)^2) / 25
        gen_chance = random.random()
        if gen_chance < village_chance:

            # Generate village and reset counter
            self.floors_since_village = 0  # Reset counter when village appears
            self.engine.game_map = generate_village(
                map_width=self.map_width,
                map_height=self.map_height,
                engine=self.engine,
            )
        else:
            # Generate dungeon (counter continues to accumulate)
            self.engine.game_map = generate_dungeon(
                max_rooms=self.max_rooms,
                room_min_size=self.room_min_size,
                room_max_size=self.room_max_size,
                map_width=self.map_width,
                map_height=self.map_height,
                engine=self.engine,
            )

    def descend(self) -> None:
        """Descend one level.

        Behavior:
        - Push the current map onto the up_stack so it can be returned to by ascending.
        - If a previously-visited lower map exists on the down_stack, pop and restore it
          (so descend after an ascend returns you to the same lower map).
        - Otherwise, generate a fresh floor (via generate_floor()).
        - In both cases, ensure an up_stairs tile exists on the newly active map at the
          player's location so the player can ascend back.
        """
        current_map = self.engine.game_map
        player_pos = (self.engine.player.x, self.engine.player.y)

        # Push current map onto up_stack (so we can ascend later)
        self.up_stack.append((current_map, player_pos, self.current_floor))

        # If we have a previously-cached lower map, reuse it instead of regenerating
        if len(self.down_stack) > 0:
            next_map, next_player_pos, next_floor = self.down_stack.pop()

            # Clear animations before map swap
            try:
                if hasattr(self.engine, "animation_queue"):
                    try:
                        self.engine.animation_queue.clear()
                    except Exception:
                        try:
                            while self.engine.animation_queue:
                                self.engine.animation_queue.popleft()
                        except Exception:
                            pass
            except Exception:
                pass

            # Restore the cached lower map
            self.engine.game_map = next_map
            # Update floor number to the stored value
            try:
                self.current_floor = next_floor
            except Exception:
                pass

            # Place player where they were on that lower map (if provided)
            try:
                nx, ny = next_player_pos
                self.engine.player.place(nx, ny, next_map)
            except Exception:
                pass

            return

        # No cached lower map: generate a new floor
        self.generate_floor()

        # After generation, place an up stairs tile at the player's current location
        try:
            px, py = self.engine.player.x, self.engine.player.y
            self.engine.game_map.tiles[px, py] = tile_types.up_stairs
            self.engine.game_map.upstairs_location = (px, py)
        except Exception:
            pass

    def ascend(self) -> None:
        """Ascend one level.

        Behavior:
        - Push the current map onto down_stack so it can be returned to by descending.
        - Pop the most recent map from up_stack and restore it as the active map.
        - Restore player position and floor number from the popped entry.
        """
        # If nothing to ascend to, do nothing
        if len(self.up_stack) == 0:
            return

        current_map = self.engine.game_map
        current_player_pos = (self.engine.player.x, self.engine.player.y)

        # Push current map onto down_stack so we can go back down to it later
        self.down_stack.append((current_map, current_player_pos, self.current_floor))

        # Pop the map above us and restore it
        prev_map, prev_player_pos, prev_floor = self.up_stack.pop()

        # Clear animations before map swap
        try:
            if hasattr(self.engine, "animation_queue"):
                try:
                    self.engine.animation_queue.clear()
                except Exception:
                    try:
                        while self.engine.animation_queue:
                            self.engine.animation_queue.popleft()
                    except Exception:
                        pass
        except Exception:
            pass

        # Restore previous map and player position
        self.engine.game_map = prev_map
        try:
            px, py = prev_player_pos
            self.engine.player.place(px, py, prev_map)
        except Exception:
            try:
                px = max(0, min(prev_map.width - 1, px))
                py = max(0, min(prev_map.height - 1, py))
                self.engine.player.place(px, py, prev_map)
            except Exception:
                pass

        # Restore recorded floor number
        try:
            self.current_floor = prev_floor
        except Exception:
            pass

