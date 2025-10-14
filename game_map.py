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
            self, engine: Engine, width: int, height: int, entities: Iterable[Entity] = ()
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
        # Build per-tile lighting mask: tiles considered "lit" if within player's torch radius
        # or within campfire radius (3). We'll compute lit_mask first and then choose
        # per-tile 'light' vs 'dark' so mixed FOV renders correctly.
        lit_mask = np.zeros((self.width, self.height), dtype=bool, order="F")
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
                rr = 7
                px, py = player.x, player.y
                xs = np.arange(0, self.width)
                ys = np.arange(0, self.height)
                dx = xs[:, None] - px
                dy = ys[None, :] - py
                dist2 = dx * dx + dy * dy
                lit_mask |= dist2 <= (rr * rr)

            # Campfire lighting (radius 3) - doesn't affect FOV, only visual lighting
            try:
                for item in getattr(self, "items", []):
                    try:
                        if item.name == "Campfire":
                            cx, cy = item.x, item.y
                            xs = np.arange(0, self.width)
                            ys = np.arange(0, self.height)
                            dx = xs[:, None] - cx
                            dy = ys[None, :] - cy
                            dist2 = dx * dx + dy * dy
                            lit_mask |= dist2 <= (3 * 3)
                    except Exception:
                        continue
            except Exception:
                pass
        except Exception:
            lit_mask[:] = False

        # Now select per-tile graphic: visible+lit -> light, visible+unlit -> dark, explored -> dark, else SHROUD
        console.tiles_rgb[0 : self.width, 0 : self.height] = np.select(
            condlist=[self.visible & lit_mask, self.visible & (~lit_mask), self.explored],
            choicelist=[self.tiles["light"], self.tiles["dark"], self.tiles["dark"]],
            default=tile_types.SHROUD,
        )

        # If entire visible area has no lit tiles (complete darkness), make the
        # visible-but-unlit tiles a hair lighter so the player's FOV reads more
        # usefully. This is a single, conditional pass to avoid stacking.
        try:
            visible_mask = self.visible
            visible_count = int(np.count_nonzero(visible_mask))
            visible_lit_count = int(np.count_nonzero(visible_mask & lit_mask))
            # Only apply when there are visible tiles and none are lit
            if visible_count > 0 and visible_lit_count == 0:
                alpha = 0.15
                dark_mask = visible_mask & (~lit_mask)
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
        # Render animations in priority order. Each animation may set a
        # numeric `render_priority` (0=under items, 1=between items and actors,
        # 2=above actors). Older animations may set `draw_above` (boolean);
        # treat draw_above=True as priority 2 for compatibility.
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
        from procgen import generate_dungeon

        self.current_floor += 1

        self.engine.game_map = generate_dungeon(
            max_rooms=self.max_rooms,
            room_min_size=self.room_min_size,
            room_max_size=self.room_max_size,
            map_width=self.map_width,
            map_height=self.map_height,
            engine=self.engine,
        )