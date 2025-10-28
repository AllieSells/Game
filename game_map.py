from __future__ import annotations

from typing import Iterable, Iterator, Optional, TYPE_CHECKING
import numpy as np
from tcod.console import Console

import tile_types
from entity import Actor, Item
from render_order import RenderOrder
import color

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
    
    def render(self, console: Console) -> None:
        # Update tile lighting status based on proximity to light sources
        # Reset all tiles to unlit first
        self.tiles["lit"][:] = False
        
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
                # Use FOV to prevent torch light from going through walls
                try:
                    from tcod.map import compute_fov
                    import tcod
                    from tcod import libtcodpy
                    torch_fov = compute_fov(
                        self.tiles["transparent"], (px, py), 
                        radius=7, algorithm=tcod.FOV_SHADOW
                    )
                    self.tiles["lit"] |= torch_fov
                except Exception as e:
                    # Explain why FOV failed
                    print(f"Failed to compute FOV for torch at ({px}, {py}): {e}")
                    import traceback
                    traceback.print_exc()

                    # Fallback to simple distance if FOV fails
                    rr = 7
                    xs = np.arange(0, self.width)
                    ys = np.arange(0, self.height)
                    dx = xs[:, None] - px
                    dy = ys[None, :] - py
                    dist2 = dx * dx + dy * dy
                    self.tiles["lit"] |= dist2 <= (rr * rr)

            # Campfire and Bonfire lighting - doesn't affect FOV, only visual lighting
            try:
                for item in getattr(self, "items", []):
                    try:
                        if item.name == "Campfire":
                            cx, cy = item.x, item.y
                            # Only apply lighting if item is within map bounds
                            if not (0 <= cx < self.width and 0 <= cy < self.height):
                                continue
                            # Use FOV to prevent light from going through walls
                            try:
                                from tcod.map import compute_fov
                                import tcod
                                from tcod import libtcodpy
                                campfire_fov = compute_fov(
                                    self.tiles["transparent"], (cx, cy), 
                                    radius=3, algorithm=tcod.FOV_SHADOW
                                )
                                self.tiles["lit"] |= campfire_fov
                            except Exception:
                                # Fallback to simple distance if FOV fails
                                xs = np.arange(0, self.width)
                                ys = np.arange(0, self.height)
                                dx = xs[:, None] - cx
                                dy = ys[None, :] - cy
                                dist2 = dx * dx + dy * dy
                                self.tiles["lit"] |= dist2 <= (3 * 3)  # radius 3 for campfires
                        elif item.name == "Bonfire":
                            bx, by = item.x, item.y
                            # Only apply lighting if item is within map bounds
                            if not (0 <= bx < self.width and 0 <= by < self.height):
                                continue
                            # Use FOV to prevent light from going through walls
                            try:
                                from tcod.map import compute_fov
                                import tcod
                                from tcod import libtcodpy
                                bonfire_fov = compute_fov(
                                    self.tiles["transparent"], (bx, by), 
                                    radius=15, algorithm=tcod.FOV_SHADOW
                                )
                                self.tiles["lit"] |= bonfire_fov
                            except Exception:
                                # Fallback to simple distance if FOV fails
                                xs = np.arange(0, self.width)
                                ys = np.arange(0, self.height)
                                dx = xs[:, None] - bx
                                dy = ys[None, :] - by
                                dist2 = dx * dx + dy * dy
                                self.tiles["lit"] |= dist2 <= (15 * 15)  # radius 15 for bonfires (larger)
                    except Exception:
                        continue
            except Exception:
                pass
        except Exception:
            self.tiles["lit"][:] = False

        # Now select per-tile graphic: use the tile's lit attribute combined with player FOV
        # Light sources set tile lit status, but player only sees the effect if in their FOV
        console.tiles_rgb[0 : self.width, 0 : self.height] = np.select(
            condlist=[self.visible & self.tiles["lit"], self.visible & (~self.tiles["lit"]), self.explored],
            choicelist=[self.tiles["light"], self.tiles["dark"], self.tiles["dark"]],
            default=tile_types.SHROUD,
        )

        # Make the 3x3 area around player always a bit lighter (renders under light source light)
        try:
            # Create 3x3 area mask around player that respects walls/transparency
            px, py = self.engine.player.x, self.engine.player.y
            player_area_mask = np.zeros((self.width, self.height), dtype=bool, order="F")
            
            if 0 <= px < self.width and 0 <= py < self.height:
                # Check each tile in 3x3 area around player
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        tx, ty = px + dx, py + dy
                        # Check if target position is in bounds
                        if 0 <= tx < self.width and 0 <= ty < self.height:
                            # Only include if tile is transparent (not a wall)
                            if self.tiles[tx, ty]["transparent"]:
                                player_area_mask[tx, ty] = True
            
            # Always apply enhancement (first line is always true)
            if True:
                alpha = 0.15
                # Apply only to player area (independent of FOV)
                dark_mask = player_area_mask
                if np.any(dark_mask):
                    tiles = console.tiles_rgb[0 : self.width, 0 : self.height]
                    if hasattr(tiles.dtype, 'names') and tiles.dtype.names and 'fg' in tiles.dtype.names:
                        try:
                            fg = tiles['fg'].astype(float)
                            bg = tiles['bg'].astype(float)
                            # blend toward the light variant
                            light_fg = self.tiles['light']['fg'].astype(float)
                            light_bg = self.tiles['light']['bg'].astype(float)
                            fg[dark_mask] = ((1.0 - alpha) * fg[dark_mask] + alpha * light_fg[dark_mask]).clip(0,255)
                            bg[dark_mask] = ((1.0 - alpha) * bg[dark_mask] + alpha * light_bg[dark_mask]).clip(0,255)
                            tiles['fg'] = fg.astype('u1')
                            tiles['bg'] = bg.astype('u1')
                            console.tiles_rgb[0 : self.width, 0 : self.height] = tiles
                        except Exception:
                            # Fallback to plain RGB blending
                            layer = tiles.astype(float)
                            light_layer = self.tiles['light'].astype(float)
                            layer[dark_mask] = ((1.0 - alpha) * layer[dark_mask] + alpha * light_layer[dark_mask])
                            console.tiles_rgb[0 : self.width, 0 : self.height] = layer.astype(np.uint8)
                    else:
                        layer = tiles.astype(float)
                        light_layer = self.tiles['light'].astype(float)
                        layer[dark_mask] = ((1.0 - alpha) * layer[dark_mask] + alpha * light_layer[dark_mask]).clip(0,255)
                        console.tiles_rgb[0 : self.width, 0 : self.height] = layer.astype(np.uint8)
        except Exception:
            pass
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
                console.print(x=entity.x, y=entity.y, string=entity.char, fg=entity.color)
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
                console.print(x=entity.x, y=entity.y, string=entity.char, fg=entity.color)
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

