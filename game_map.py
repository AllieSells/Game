from __future__ import annotations

import threading
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


class _FloorProbe:
    """Throwaway placement anchor used by background floor generation.

    Substitutes for the real player inside generate_dungeon so the background
    thread never reads or writes player.x / player.y.  After generation, probe.x
    and probe.y hold the first-room centre that becomes the player's spawn point.
    """
    def __init__(self) -> None:
        self.x: int = 0
        self.y: int = 0
        self.parent = None

    def place(self, x: int, y: int, gamemap=None) -> None:
        self.x = x
        self.y = y
        if gamemap:
            if self.parent and hasattr(self.parent, "entities"):
                self.parent.entities.discard(self)
            self.parent = gamemap
            gamemap.entities.add(self)

class GameMap:
    def __init__(
            self, engine: Engine, width: int, height: int, entities: Iterable[Entity] = (), type: str = "dungeon", name: str = "Dungeon", sunlit: bool = False
    ):
        self.engine = engine
        self.width, self.height = width, height
        self.entities = set(entities)
        self.type = type
        self.sunlit = sunlit
        self.temperature = 20
        
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
    
    def _add_light_source(self, source_x: int, source_y: int, radius: int, max_intensity: float = 1.0,
                          wobble_dx: float = 0.0, wobble_dy: float = 0.0, di: float = 0.0) -> None:
        """Add light from a source with distance-based falloff and FOV blocking.

        wobble_dx / wobble_dy shift the effective light centre each frame so
        the flame appears to move.  di is an intensity delta (±0.2) that
        brightens or dims the whole cone, both matching the libtcod demo
        torch-flicker formula exactly.
        """
        try:
            from tcod.map import compute_fov
            import tcod

            # FOV blocking uses the integer tile position (walls don't move).
            fov = compute_fov(
                self.tiles["transparent"], (source_x, source_y),
                radius=radius, algorithm=tcod.FOV_SHADOW
            )

            # Effective (wobbled) light centre for distance calculation.
            eff_x = source_x + wobble_dx
            eff_y = source_y + wobble_dy

            xs = np.arange(0, self.width)
            ys = np.arange(0, self.height)
            ddx = xs[:, None] - eff_x
            ddy = ys[None, :] - eff_y
            r = ddx * ddx + ddy * ddy  # squared distance from wobbled position

            squared_radius = float(radius * radius)

            # libtcod demo falloff: l = (R² − r) / R² + di, clamped to [0, max_intensity].
            # Gives 1.0+di at the centre and di at the edge; di pulses the cone
            # brighter/darker each frame while the clamp keeps values legal.
            l = (squared_radius - r) / squared_radius + di

            mask = fov & (r <= squared_radius)
            light_intensity = np.where(mask, np.clip(l, 0.0, max_intensity), 0.0)

            # Accumulate light (multiple sources add together, capped at 1.0).
            self.tiles["light_level"] = np.minimum(
                1.0,
                self.tiles["light_level"] + light_intensity
            )

        except Exception:
            # Fallback: simple distance-based lighting without wobble.
            xs = np.arange(0, self.width)
            ys = np.arange(0, self.height)
            ddx = xs[:, None] - source_x
            ddy = ys[None, :] - source_y
            distance = np.sqrt(ddx * ddx + ddy * ddy)

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
            # Add configurable ambient light around player
            px, py = self.engine.player.x, self.engine.player.y
            if any(getattr(effect, "name", "") == "Darkvision" for effect in self.engine.player.effects):
                ambient_radius = 9
                ambient_intensity = 0.2
            else:
                ambient_radius = 1  # Default 1 for 3x3
                ambient_intensity = 0.1  # Default 0.1
            
            for dx in range(-ambient_radius, ambient_radius + 1):
                for dy in range(-ambient_radius, ambient_radius + 1):
                    tx, ty = px + dx, py + dy
                    if (0 <= tx < self.width and 0 <= ty < self.height 
                        and self.tiles[tx, ty]["transparent"]):
                        light_levels[tx, ty] = max(light_levels[tx, ty], ambient_intensity)

            
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
            interp_fg = (dark_fg + vis_light_levels[:, np.newaxis] * (light_fg - dark_fg))
            interp_bg = (dark_bg + vis_light_levels[:, np.newaxis] * (light_bg - dark_bg))

            # Warm torch/fire tint: lit tiles shift toward amber on non-sunlit maps.
            # warm_tint = [R_mul, G_mul, B_mul] at full brightness — keep red,
            # slightly dim green, noticeably cut blue.
            if not getattr(self, "sunlit", False):
                warm_tint = np.array([1.0, 0.88, 0.60], dtype=float)
                # Tint strength is proportional to light level (no tint in darkness)
                tint_mul = 1.0 + vis_light_levels[:, np.newaxis] * (warm_tint - 1.0)
                interp_fg = interp_fg * tint_mul
                interp_bg = interp_bg * tint_mul

            interp_fg = interp_fg.clip(0, 255).astype(np.uint8)
            interp_bg = interp_bg.clip(0, 255).astype(np.uint8)

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

        # Advance the torch-flicker time variable exactly like fov_torchx in the
        # libtcod demo (0.2 per frame).  Three 1-D noise samples at fixed offsets
        # give independent wobble axes and intensity pulse per source.
        self.engine._torch_t = getattr(self.engine, "_torch_t", 0.0) + 0.2

        # Read flicker setting once per frame (avoid repeated disk reads).
        try:
            import json as _json
            with open("settings.json") as _sf:
                _content = "\n".join(
                    line for line in _sf.read().splitlines()
                    if not line.lstrip().startswith("//")
                )
                _flicker_on = _json.loads(_content).get("light_flicker", True)
        except Exception:
            _flicker_on = True

        def _wobble(t_offset: float = 0.0):
            """Return (dx, dy, di) flicker values for a light source.

            When the 'light_flicker' setting is off, returns (0, 0, 0) so the
            light still emits at full steady radius without any animation.
            """
            if not _flicker_on:
                return 0.0, 0.0, 0.0

            t = self.engine._torch_t + t_offset
            noise = self.engine._noise_gen
            def _s(x: float) -> float:
                pt = np.array([[[x]], [[0.0]]], dtype=np.float32)
                return float(noise.sample_mgrid(pt)[0, 0])
            return _s(t + 20.0) * 0.9, _s(t + 30.0) * 0.9, _s(t) * 0.08

        if getattr(self, "sunlit", True):
            self.tiles["light_level"][:] = 1.0  # Sunlit maps are fully lit
        
        try:
            player = self.engine.player
            # Torch lighting: if player holds a Torch, light radius is 7
            has_torch = False
            try:
                if player.equipment:
                    has_torch = player.equipment.has_item_equipped("Torch")
            except Exception:
                has_torch = False

            if has_torch:
                px, py = player.x, player.y
                wdx, wdy, di = _wobble(0.0)
                self._add_light_source(px, py, radius=7, max_intensity=1.0,
                                       wobble_dx=wdx, wobble_dy=wdy, di=di)

            # Campfire and Bonfire lighting - doesn't affect FOV, only visual lighting
            try:
                for item in getattr(self, "items", []):
                    try:
                        if item.name == "Campfire":
                            cx, cy = item.x, item.y
                            # Only apply lighting if item is within map bounds
                            if not (0 <= cx < self.width and 0 <= cy < self.height):
                                continue
                            # Unique noise offset so each campfire flickers independently.
                            wdx, wdy, di = _wobble(cx * 3.7 + cy * 5.3)
                            self._add_light_source(cx, cy, radius=5, max_intensity=0.8,
                                                   wobble_dx=wdx, wobble_dy=wdy, di=di)
                        elif item.name == "Bonfire":
                            bx, by = item.x, item.y
                            # Only apply lighting if item is within map bounds
                            if not (0 <= bx < self.width and 0 <= by < self.height):
                                continue
                            wdx, wdy, di = _wobble(bx * 3.7 + by * 5.3)
                            self._add_light_source(bx, by, radius=15, max_intensity=1.0,
                                                   wobble_dx=wdx, wobble_dy=wdy, di=di)
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
            current_floor: int = 0,
        ):
            self.engine = engine

            self.map_width = map_width
            self.map_height = map_height

            self.max_rooms = max_rooms

            self.room_min_size = room_min_size
            self.room_max_size = room_max_size

            self.current_floor = current_floor
            self.floors_since_village = -1  # Track floors since last village
            # Stacks to support navigating between previously visited maps.
            # up_stack: maps above the current map (you can ascend to these)
            # down_stack: maps below the current map (you can descend to these if you previously ascended)
            # Each entry is a tuple: (gamemap, player_xy, floor_number)
            self.up_stack: list[tuple] = []
            self.down_stack: list[tuple] = []
            self._stack_lock = threading.Lock()  # guards down_stack across threads
            self._bg_thread: Optional[threading.Thread] = None
            self.fungi = []  # Global list of fungi in the world

            # world_noise is populated by generate_world_noise()
            self.world_noise: np.ndarray = np.zeros((4, 1), dtype=np.float32)
            # Seeded RNG held across batches so noise extends smoothly between them
            self._noise_rng = None
            # Next floor number to generate when down_stack runs low
            self._next_batch_floor: int = 1

    # pickle support: strip out the non-serialisable lock and thread objects
    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        # Wait for any running background thread before saving
        bg = state.get("_bg_thread")
        if bg is not None and bg.is_alive():
            bg.join()
        state.pop("_stack_lock", None)
        state.pop("_bg_thread", None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        # Recreate the lock and clear the thread handle on restore
        self._stack_lock = threading.Lock()
        self._bg_thread = None

    # ---------------------------------------------------------------------------
    # Noise tracks (indices into world_noise axis-0)
    # ---------------------------------------------------------------------------
    TRACK_TEMPERATURE = 0  # -10..10: cold → hot
    TRACK_VEGETATION = 1  # -10..10: sparse → dense
    TRACK_TYPE    = 2  # -10..10: dungeon halls → natural caves
    TRACK_SPECIAL    = 3  # -10..10: normal floor → special / event floor

    # Each deeper floor steps this far in noise space → smooth transitions
    _FLOOR_SCALE = 0.3
    # Number of waypoints spread across _MAX_FLOORS — fewer = smoother, more = choppier
    _WAYPOINTS = 2
    # Pre-allocate for this many floors; extended automatically if needed
    _MAX_FLOORS  = 6
    # Optional guaranteed starting values per track (raw float -1..1, or None to randomise).
    # e.g. TRACK_TYPE starts at -10 on the -10..10 scale → -1.0 raw.
    _START_ANCHORS = {
        TRACK_TYPE: 10.0,  # floor 1 is always full dungeon halls
    }

    def _generate_noise_batch(self, rng, num_floors: int, anchor_values=None) -> np.ndarray:
        """Return a (4, num_floors) noise array built from cubic-spline random waypoints.

        anchor_values -- optional shape-(4,) array that pins the first waypoint of
        each track to the last value of the previous batch, giving smooth continuation.
        """
        from scipy.interpolate import CubicSpline

        n_wp = max(self._WAYPOINTS, 2)
        wp_floors = np.linspace(0, num_floors - 1, n_wp)
        tracks = []
        for t in range(4):
            wp_values = rng.uniform(-1.0, 1.0, size=n_wp)
            if anchor_values is not None:
                wp_values[0] = float(anchor_values[t])
            cs = CubicSpline(wp_floors, wp_values)
            tracks.append(np.clip(cs(np.arange(num_floors)), -1.0, 1.0))
        return np.array(tracks, dtype=np.float32)

    def generate_world_noise(self) -> None:
        """Build the initial world noise profile (first batch)."""
        from setup_game import _current_seed
        self._noise_rng = np.random.default_rng(_current_seed)
        # Build anchor array from _START_ANCHORS (None entries stay random)
        initial_anchors = np.array(
            [self._START_ANCHORS.get(t, None) for t in range(4)], dtype=object
        )
        # Only pass anchors if at least one track has a fixed start
        if any(v is not None for v in initial_anchors):
            anchor_arr = np.array(
                [float(v) if v is not None else self._noise_rng.uniform(-1.0, 1.0)
                 for v in initial_anchors],
                dtype=np.float32,
            )
            self.world_noise = self._generate_noise_batch(self._noise_rng, self._MAX_FLOORS, anchor_values=anchor_arr)
        else:
            self.world_noise = self._generate_noise_batch(self._noise_rng, self._MAX_FLOORS)

        self.engine.debug_log(f"Generated {self._MAX_FLOORS} floors (seed={_current_seed})", handler=type(self).__name__, event="world_noise")

    def _extend_world_noise(self) -> None:
        """Append another noise batch anchored to the tail of the current array."""
        anchor = self.world_noise[:, -1]
        new_batch = self._generate_noise_batch(self._noise_rng, self._MAX_FLOORS, anchor_values=anchor)
        self.world_noise = np.concatenate([self.world_noise, new_batch], axis=1)
        self.engine.debug_log(f"Extended to {self.world_noise.shape[1]} total floors", handler=type(self).__name__, event="world_noise")

    def get_floor_noise(self, floor: int) -> dict:
        def _to_int(raw: float) -> int:
            return int(max(-10, min(10, round(raw * 10))))

        # Auto-extend the noise array on demand so any floor index can be looked up
        while floor >= self.world_noise.shape[1] and self._noise_rng is not None:
            self._extend_world_noise()

        idx = min(max(floor, 0), self.world_noise.shape[1] - 1)
        return {
            "temperature": _to_int(self.world_noise[self.TRACK_TEMPERATURE, idx]),
            "vegetation":  _to_int(self.world_noise[self.TRACK_VEGETATION,  idx]),
            "type":        _to_int(self.world_noise[self.TRACK_TYPE,        idx]),
            "special":     _to_int(self.world_noise[self.TRACK_SPECIAL,     idx]),
        }

    
    def _generate_floor_batch(self, start_floor_num: int) -> None:
        """Generate _MAX_FLOORS maps and append them to down_stack.

        Thread-safe: uses _FloorProbe instead of the real player, never mutates
        self.current_floor, and holds _stack_lock only while appending.
        world_noise must already cover [start_floor_num-1 .. start_floor_num+_MAX_FLOORS-2]
        before this is called (guaranteed by _spawn_bg_batch pre-extension).
        """
        from procgen import generate_dungeon

        batch: list[tuple] = []
        for i in range(self._MAX_FLOORS):
            floor_num = start_floor_num + i
            noise = self.get_floor_noise(floor_num - 1)
            probe = _FloorProbe()
            new_map = generate_dungeon(
                max_rooms=self.max_rooms,
                room_min_size=self.room_min_size,
                room_max_size=self.room_max_size,
                map_width=self.map_width,
                map_height=self.map_height,
                engine=self.engine,
                noise_map=noise,
                player_proxy=probe,
                floor_num=floor_num,
            )
            new_map.entities.discard(probe)
            probe.parent = None
            batch.append((new_map, (probe.x, probe.y), floor_num))

        with self._stack_lock:
            self.down_stack.extend(batch)

        self.engine.debug_log(f"Batch ready: floors {start_floor_num}\u2013{start_floor_num + self._MAX_FLOORS - 1} ({len(self.down_stack)} queued)", handler=type(self).__name__, event="world_noise")

    def _spawn_bg_batch(self, start_floor_num: int) -> None:
        """Kick off a background thread to generate the next batch, if none is running.

        Noise is pre-extended on the main thread before the thread starts so the
        background thread only reads world_noise (never writes it).
        """
        if self._bg_thread is not None and self._bg_thread.is_alive():
            return
        # Pre-extend noise synchronously so bg thread is read-only on noise data
        needed = start_floor_num + self._MAX_FLOORS - 2
        while needed >= self.world_noise.shape[1] and self._noise_rng is not None:
            self._extend_world_noise()
        self._bg_thread = threading.Thread(
            target=self._generate_floor_batch,
            args=(start_floor_num,),
            daemon=True,
        )
        self._bg_thread.start()
        self.engine.debug_log(f"Background: generating floors {start_floor_num}\u2013{start_floor_num + self._MAX_FLOORS - 1}", handler=type(self).__name__, event="world_noise")

    def generate_world(self) -> None:
        """Activate floor 1 immediately, then generate the rest in a background thread.

        down_stack holds upcoming pre-built floors (index 0 = next floor down).
        up_stack is a full history of every floor the player has stood on, so
        the player can always ascend all the way back to floor 1.
        """
        from procgen import generate_dungeon

        self.generate_world_noise()
        with self._stack_lock:
            self.down_stack = []

        # Floor 1: generate and activate synchronously so the player can start immediately
        probe = _FloorProbe()
        noise = self.get_floor_noise(0)
        floor1_map = generate_dungeon(
            max_rooms=self.max_rooms,
            room_min_size=self.room_min_size,
            room_max_size=self.room_max_size,
            map_width=self.map_width,
            map_height=self.map_height,
            engine=self.engine,
            noise_map=noise,
            player_proxy=probe,
            floor_num=1,
        )
        floor1_map.entities.discard(probe)
        probe.parent = None
        self._activate_floor((floor1_map, (probe.x, probe.y), 1))

        # Floors 2 onward: generate in background
        self._next_batch_floor = self._MAX_FLOORS + 2
        self._spawn_bg_batch(2)

    def _activate_floor(self, floor_entry: tuple) -> None:
        """Set the given floor entry as the active map and place the player."""
        new_map, start_pos, floor_num = floor_entry
        self.current_floor = floor_num
        self.engine.game_map = new_map
        new_map.entities.add(self.engine.player)
        px, py = start_pos
        self.engine.player.place(px, py, new_map)
        self.engine.debug_log(f"Activated floor {floor_num}, player at ({px}, {py})", handler=type(self).__name__, event="activate_floor")





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
        village_chance = ((self.floors_since_village)**2) / 25
        
        gen_chance = random.random()
        
        self.engine.debug_log(f"Floors since village: {self.floors_since_village}, Gen Chance: {gen_chance:.2f}, < Village chance: {village_chance:.2f}", handler=type(self).__name__, event="generate_floor")
        self.engine.debug_log(f"Village chance equation: (({self.floors_since_village})^2) / 25 = {village_chance:.2f}", handler=type(self).__name__, event="generate_floor")
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

        The current map is pushed onto up_stack so the player can ascend all the
        way back.  The next floor is popped from down_stack; when the queue drops
        to a low watermark a background batch is spawned automatically.
        """
        current_map = self.engine.game_map
        player_pos = (self.engine.player.x, self.engine.player.y)
        self.engine.is_transitioning_level = True

        # Save current floor so the player can ascend back to it
        self.up_stack.append((current_map, player_pos, self.current_floor))

        # If queue is empty and bg thread is still running, wait for it
        with self._stack_lock:
            queue_len = len(self.down_stack)

        if queue_len == 0:
            if self._bg_thread is not None and self._bg_thread.is_alive():
                self.engine.debug_log("Waiting for background generation to finish...", handler=type(self).__name__, event="descend")
                self._bg_thread.join()
            else:
                # Fallback: generate synchronously
                self.engine.debug_log("Queue empty — generating synchronously...", handler=type(self).__name__, event="descend")
                self._generate_floor_batch(self._next_batch_floor)
                self._next_batch_floor += self._MAX_FLOORS

        # Spawn next background batch when queue is getting low
        with self._stack_lock:
            queue_len = len(self.down_stack)
        if queue_len <= 2:
            self._spawn_bg_batch(self._next_batch_floor)
            self._next_batch_floor += self._MAX_FLOORS

        # Clear pending animations before map swap
        try:
            if hasattr(self.engine, "animation_queue"):
                self.engine.animation_queue.clear()
        except Exception:
            pass

        # Activate the next floor
        with self._stack_lock:
            next_entry = self.down_stack.pop(0)
        self._activate_floor(next_entry)

        # Place up_stairs at the landing spot so the player can ascend back
        try:
            px, py = self.engine.player.x, self.engine.player.y
            self.engine.game_map.tiles[px, py] = tile_types.up_stairs
            self.engine.game_map.upstairs_location = (px, py)
        except Exception:
            pass

        with self._stack_lock:
            q = len(self.down_stack)
        self.engine.debug_log(f"Floor {self.current_floor} ({q} ahead, {len(self.up_stack)} above)", handler=type(self).__name__, event="descend")

        try:
            import sounds
            sounds.refresh_all_ambient_sounds(self.engine.player, self.engine.game_map.entities, self.engine.game_map)
        except Exception:
            pass

        self.engine.is_transitioning_level = False

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
            
        # Set level transition flag to suppress equipment sounds
        self.engine.is_transitioning_level = True

        current_map = self.engine.game_map
        current_player_pos = (self.engine.player.x, self.engine.player.y)

        # Insert current map at the front of down_stack so re-descending returns here
        with self._stack_lock:
            self.down_stack.insert(0, (current_map, current_player_pos, self.current_floor))

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

        # Refresh ambient sounds for the restored map
        try:
            import sounds
            sounds.refresh_all_ambient_sounds(self.engine.player, prev_map.entities, prev_map)
        except Exception:
            pass
            
        # Clear level transition flag after restoration is complete
        self.engine.is_transitioning_level = False

