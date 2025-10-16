from __future__ import annotations

from typing import Iterable, Iterator, Optional, TYPE_CHECKING
import numpy as np
from tcod.console import Console

import tile_types
from entity import Actor, Item
from render_order import RenderOrder

if TYPE_CHECKING:
    from engine import Engine
    from entity import Entity

class GameMap:
    def __init__(
            self, engine: Engine, width: int, height: int, entities: Iterable[Entity] = (), type: str = "dungeon",
    ):
        self.engine = engine
        self.width, self.height = width, height
        self.entities = set(entities)
        self.tiles = np.full((width, height), fill_value=tile_types.wall, order="F")

        self.visible = np.full(
            (width, height), fill_value=False, order="F")  # Tiles the player can see
        
        self.explored = np.full(
            (width, height), fill_value=False, order="F") # Tiles player has seen before
        
        self.downstairs_location = (0, 0)
        self.type = type  # What type of map this is, e.g. "dungeon" or "village"
        
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
                    torch_fov = compute_fov(
                        self.tiles["transparent"], (px, py), 
                        radius=7, algorithm=tcod.FOV_SHADOW
                    )
                    self.tiles["lit"] |= torch_fov
                except Exception:
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
                            # Use FOV to prevent light from going through walls
                            try:
                                from tcod.map import compute_fov
                                import tcod
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
                            # Use FOV to prevent light from going through walls
                            try:
                                from tcod.map import compute_fov
                                import tcod
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
        for entity in entities_sorted_for_rendering:
            if entity.render_order == RenderOrder.ACTOR:
                continue
            if self.visible[entity.x, entity.y]:
                console.print(x=entity.x, y=entity.y, string=entity.char, fg=entity.color)

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
            if self.visible[entity.x, entity.y]:
                console.print(x=entity.x, y=entity.y, string=entity.char, fg=entity.color)
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

    def generate_floor(self) -> None:
        from procgen import generate_dungeon, generate_village

        self.current_floor += 1

        self.engine.game_map = generate_village(
            #max_rooms=self.max_rooms,
            #room_min_size=self.room_min_size,
            #room_max_size=self.room_max_size,
            map_width=self.map_width,
            map_height=self.map_height,
            engine=self.engine,
        )