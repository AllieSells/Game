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

# ---------------------------------------------------------------------------
# Lightmap tuning parameters
# These control how the GPU per-tile MOD-blend lightmap looks.
# Adjust them freely — they are read each frame from build_lightmap().
# ---------------------------------------------------------------------------

# Minimum brightness in complete darkness (0.0 = pure black, 0.2 = 20% floor).
LIGHT_MIN_BRIGHTNESS: float = 0.2

# Lightmap multiplier for explored-but-not-currently-visible tiles.
# Set equal to LIGHT_MIN_BRIGHTNESS so explored areas match the darkest
# visible tiles (those with zero light_level at the FOV edge).  This makes
# the transition from lit FOV → explored fog completely seamless — bilinear
# interpolation between identical values produces no visible border at all.
# Range: 0.0 (black) – 1.0 (full bright).  Unexplored tiles get 0.0 (black).
LIGHT_EXPLORED_MOD: float = LIGHT_MIN_BRIGHTNESS  # = 0.2

# Warm-amber tint at full brightness on non-sunlit maps.
# Applied as a per-channel multiplicative reduction relative to neutral white.
# R channel is left at 1.0 (no change).
LIGHT_WARM_G: float = 0.12   # G reduces by this fraction at full brightness → slight amber
LIGHT_WARM_B: float = 0.40   # B reduces by this fraction at full brightness → strong warm tone


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
            self, engine: Engine, width: int, height: int, entities: Iterable[Entity] = (), type: str = "dungeon", name: str = "Dungeon", sunlit: bool = False, biome: str = "dungeon"
    ):
        self.engine = engine
        self.width, self.height = width, height
        self.entities = set(entities)
        self.type = type
        self.sunlit = sunlit
        self.temperature = 20
        self.biome = biome
        self.biome_str = None
        
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

        # Per-tile white/neutral light accumulator (separate from warm-tinted light_level).
        # Sources with light_color=(255,255,255) contribute here; build_lightmap blends
        # warm and white contributions to produce the final per-tile tint.
        self._white_light_level = np.zeros((width, height), dtype=np.float32, order="F")
        
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
                          wobble_dx: float = 0.0, wobble_dy: float = 0.0, di: float = 0.0,
                          light_color: tuple = None) -> None:
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
            if light_color is not None:
                wl = getattr(self, '_white_light_level', None)
                if wl is not None:
                    self._white_light_level = np.minimum(1.0, wl + light_intensity)

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
            if light_color is not None:
                wl = getattr(self, '_white_light_level', None)
                if wl is not None:
                    self._white_light_level = np.minimum(1.0, wl + light_intensity)
    
    def _apply_lighting_to_entity_color(self, entity_color: tuple, x: int, y: int) -> tuple:
        """Apply lighting effects to entity color based on tile light level."""
        try:
            # Get light level at entity position (0.0 = dark, 1.0 = full light)
            light_level = self.tiles["light_level"][x, y]
            light_level = float(light_level)
            light_level = max(0.0, min(1.0, light_level))

            # Apply lighting: dark multiplier increases with light level
            # 0.2 = very dark (20% brightness), 1.0 = full brightness
            brightness = 0.2 + (0.8 * light_level)

            r, g, b = entity_color
            r = r * brightness
            g = g * brightness
            b = b * brightness

            # Match the warm amber tint applied to tiles on non-sunlit maps.
            # Tint strength scales with light_level so dark areas stay neutral.
            if not getattr(self, "sunlit", False):
                # warm_tint matches _render_tiles_with_gradient: [1.0, 0.88, 0.60]
                r = r * (1.0 + light_level * (1.0 - 1.0))   # R unchanged
                g = g * (1.0 + light_level * (0.88 - 1.0))  # G slightly dimmed
                b = b * (1.0 + light_level * (0.60 - 1.0))  # B noticeably cut

            return (int(max(0, min(255, r))),
                    int(max(0, min(255, g))),
                    int(max(0, min(255, b))))
        except Exception:
            return entity_color
    
    def get_viewport(self, console: Console) -> tuple[int, int, int, int]:
        """Return the world-space viewport origin and visible dimensions for a console."""
        view_width = min(console.width, self.width)
        view_height = min(console.height, self.height)
        origin_x, origin_y = self.engine.get_camera_origin(view_width, view_height)
        return origin_x, origin_y, view_width, view_height

    def screen_coords(self, console: Console, x: int, y: int) -> Optional[tuple[int, int]]:
        """Convert world coordinates to viewport-relative console coordinates."""
        _, _, view_width, view_height = self.get_viewport(console)
        return self.engine.world_to_screen(x, y, view_width, view_height)

    def screen_print(
        self,
        console: Console,
        x: int,
        y: int,
        string: str,
        fg: tuple[int, int, int] | None = None,
        bg: tuple[int, int, int] | None = None,
    ) -> None:
        """Print using world coordinates, clipped to the current viewport."""
        screen_position = self.screen_coords(console, x, y)
        if screen_position is None:
            return
        screen_x, screen_y = screen_position
        console.print(x=screen_x, y=screen_y, string=string, fg=fg, bg=bg)

    def screen_print_lit(
        self,
        console: Console,
        x: int,
        y: int,
        string: str,
        fg: tuple[int, int, int] | None = None,
        bg: tuple[int, int, int] | None = None,
    ) -> None:
        """Like screen_print but with tile lighting applied.

        Lighting is now handled entirely by the GPU lightmap MOD pass in
        main.py, so this is a direct passthrough to screen_print.  Keeping
        the method signature intact avoids changing every call-site in
        animations.py and elsewhere.
        """
        self.screen_print(console, x, y, string, fg=fg, bg=bg)

    def _render_tiles_with_gradient(self, console: Console) -> None:
        """Render tiles for the visible viewport.

        Visible tiles are written at full 'light' variant brightness — the GPU
        lightmap pass in main.py (build_lightmap + MOD blend) handles per-pixel
        tinting and dimming with bilinear sub-tile interpolation.
        Explored-but-not-visible tiles use their 'dark' variant as before.
        """
        import tile_types

        origin_x, origin_y, view_width, view_height = self.get_viewport(console)
        x_slice = slice(origin_x, origin_x + view_width)
        y_slice = slice(origin_y, origin_y + view_height)
        
        visible_mask = self.visible[x_slice, y_slice]
        explored_mask = self.explored[x_slice, y_slice]
        
        result_tiles = np.full(
            (view_width, view_height), 
            tile_types.SHROUD, 
            dtype=console.tiles_rgb.dtype
        )
        
        dark_tiles = self.tiles["dark"][x_slice, y_slice]
        light_tiles = self.tiles["light"][x_slice, y_slice]
        # light_levels is a view into self.tiles so ambient writes propagate to build_lightmap.
        light_levels = self.tiles["light_level"][x_slice, y_slice]
        
        if np.any(visible_mask):
            # All visible tiles rendered at full 'light' brightness.
            # Dimming, warm-amber tint, and smooth falloff handled by GPU lightmap.
            result_tiles[visible_mask] = light_tiles[visible_mask]
        
        # Explored-but-not-visible: store light_tiles at full brightness.
        # The GPU lightmap applies LIGHT_EXPLORED_MOD to these tiles so:
        #   light_tile × LIGHT_EXPLORED_MOD ≈ dark_tile appearance
        # Using light_tiles (not dark_tiles) here means the lightmap value
        # for explored tiles (~0.35) is close to the lit-FOV boundary value
        # (~0.28 ambient), keeping bilinear interpolation artefacts invisible.
        explored_not_visible = explored_mask & (~visible_mask)
        if np.any(explored_not_visible):
            result_tiles[explored_not_visible] = light_tiles[explored_not_visible]
        
        console.tiles_rgb[:] = tile_types.SHROUD
        console.tiles_rgb[0:view_width, 0:view_height] = result_tiles

    def build_lightmap(self, console: Console) -> np.ndarray:
        """Build a per-tile RGBA lightmap for the GPU MOD blend lighting pass.

        Returns a ``(view_height, view_width, 4)`` uint8 array.  SDL's bilinear
        filtering (SDL_RENDER_SCALE_QUALITY=1) stretches this tiny texture to
        the full game-area pixel size, giving smooth sub-tile light falloff
        across every tile boundary without any CPU per-pixel work.

        Encoding (non-sunlit maps):
          R = brightness                      (warm tint leaves R unchanged)
          G = brightness × (1 − 0.12 × ll)   (slight amber at high light)
          B = brightness × (1 − 0.40 × ll)   (strong warm reduction at full light)
        where brightness = 0.2 + 0.8 × ll and ll = clamped light_level [0..1].

        Non-visible tiles are encoded as (255,255,255) so already-dim dark
        tile colours are not multiplied down a second time.
        Sunlit maps return a full-white array (MOD no-op).
        """
        origin_x, origin_y, view_width, view_height = self.get_viewport(console)
        x_slice = slice(origin_x, origin_x + view_width)
        y_slice = slice(origin_y, origin_y + view_height)

        out = np.empty((view_height, view_width, 4), dtype=np.uint8)
        out[..., 3] = 255

        if getattr(self, "sunlit", False):
            out[..., :3] = 255
            return out

        # self.tiles uses (width, height) F-order; transpose to (view_height, view_width).
        ll = self.tiles["light_level"][x_slice, y_slice].T.astype(np.float32)
        ll = np.clip(ll, 0.0, 1.0)


        brightness = LIGHT_MIN_BRIGHTNESS + (1.0 - LIGHT_MIN_BRIGHTNESS) * ll

        # Blend warm-amber tint with neutral white based on white-light contribution.
        # white_ratio=1.0 → pure white (no tint); white_ratio=0.0 → full warm amber.
        raw_wl = getattr(self, '_white_light_level', None)
        if raw_wl is not None:
            wl = np.clip(raw_wl[x_slice, y_slice].T.astype(np.float32), 0.0, 1.0)
        else:
            wl = np.zeros_like(ll)
        safe_ll = np.where(ll > 0.0, ll, np.float32(1.0))
        white_ratio = np.clip(wl / safe_ll, 0.0, 1.0)  # fraction of light that is white
        warm_ratio  = 1.0 - white_ratio

        r = brightness                                                               # R: unchanged for both tints
        g = brightness * (warm_ratio * (1.0 - LIGHT_WARM_G * ll) + white_ratio)    # G: amber only on warm portion
        b = brightness * (warm_ratio * (1.0 - LIGHT_WARM_B * ll) + white_ratio)    # B: amber only on warm portion

        # Lightmap encoding per tile state:
        #   visible          → brightness formula + warm-amber tint
        #   explored !visible → per-channel dark_bg/light_bg ratio capped at
        #                       LIGHT_EXPLORED_MOD.  For neutral tiles (stone/walls)
        #                       the ratio ≈ 0.31 which clamps to 0.2 — no change.
        #                       For colourful tiles (water) the low-value channels
        #                       (G/B ≈ 0.09/0.07) fall well below the cap, making
        #                       explored water near-black rather than teal-coloured.
        #                       Capping at LIGHT_EXPLORED_MOD ensures explored tiles
        #                       are never brighter than unlit visible tiles, so there
        #                       is no bright fringe at the FOV boundary.
        #   unexplored shroud → 0.0 (fully black)
        vis      = self.visible[x_slice, y_slice].T        # (view_height, view_width)
        explored = self.explored[x_slice, y_slice].T
        zero     = np.float32(0.0)

        dark_bg  = self.tiles["dark"]["bg"][x_slice, y_slice].astype(np.float32)   # (vw, vh, 3)
        light_bg = self.tiles["light"]["bg"][x_slice, y_slice].astype(np.float32)  # (vw, vh, 3)
        with np.errstate(divide='ignore', invalid='ignore'):
            bg_ratio = np.where(light_bg > 0.0, dark_bg / light_bg, 0.0)
        # Cap so explored tiles never exceed the brightness of unlit visible tiles.
        bg_ratio = np.clip(bg_ratio, 0.0, float(LIGHT_EXPLORED_MOD))  # (vw, vh, 3)
        exp_r = bg_ratio[..., 0].T  # (vh, vw)
        exp_g = bg_ratio[..., 1].T
        exp_b = bg_ratio[..., 2].T

        r = np.where(vis, r, np.where(explored, exp_r, zero))
        g = np.where(vis, g, np.where(explored, exp_g, zero))
        b = np.where(vis, b, np.where(explored, exp_b, zero))

        out[..., 0] = np.clip(r * 255.0, 0, 255).astype(np.uint8)
        out[..., 1] = np.clip(g * 255.0, 0, 255).astype(np.uint8)
        out[..., 2] = np.clip(b * 255.0, 0, 255).astype(np.uint8)
        return out
    
    def render(self, console: Console) -> None:
        # Update tile lighting with gradient falloff based on distance to light sources  
        # Reset all tiles to zero light level first
        self.tiles["light_level"][:] = 0.0
        if hasattr(self, '_white_light_level'):
            self._white_light_level[:] = 0.0

        # Advance the torch-flicker time variable exactly like fov_torchx in the
        # libtcod demo (0.2 per frame).  Three 1-D noise samples at fixed offsets
        # give independent wobble axes and intensity pulse per source.
        self.engine._torch_t = getattr(self.engine, "_torch_t", 0.0) + 0.2

        # Read flicker setting once per frame (avoid repeated disk reads).
        try:
            import json as _json
            with open("json/settings.json") as _sf:
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
            if hasattr(self, '_white_light_level'):
                self._white_light_level[:] = 1.0  # Sunlit = fully white light
        
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

            # Player always emits a subtle ambient glow so torchless players
            # can still navigate.  Darkvision replaces this with a larger dim cone.
            px, py = player.x, player.y
            has_darkvision = any(
                getattr(effect, "name", "") == "Darkvision"
                for effect in getattr(player, "effects", [])
            )
            if has_darkvision:
                self._add_light_source(px, py, radius=10, max_intensity=0.25)
            elif not has_torch:
                # Faint personal glow: just enough to see immediately around the player.
                self._add_light_source(px, py, radius=3, max_intensity=0.4)

            # Campfire and Bonfire lighting - doesn't affect FOV, only visual lighting
            try:
                for entity in self.entities:
                    try:
                        # Find entities with "Illuminated" effect
                        if any(getattr(effect, "name", "") == "Illuminated" for effect in getattr(entity, "effects", [])):
                            ex, ey = entity.x, entity.y
                            # Only apply lighting if entity is within map bounds
                            if not (0 <= ex < self.width and 0 <= ey < self.height):
                                continue
                            wdx, wdy, di = 0.0, 0.0, 0.0
                            self._add_light_source(ex, ey, radius=5, max_intensity=1.0,
                                                   wobble_dx=wdx, wobble_dy=wdy, di=di)
                    except Exception as e:
                        print(f"Error processing entity for lighting: {e}")
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

        # Find tile light sources 
        for x in range(self.width):
            for y in range(self.height):
                if not (0 <= x < self.width and 0 <= y < self.height):
                    continue
                else:
                    tile = self.tiles[x, y]
                    if tile["name"] == "Window":
                        self._add_light_source(x, y, radius=8, max_intensity=1.0, light_color=(255, 255, 255))

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
                # Render at full color — GPU lightmap MOD pass in main.py handles dimming.
                self.screen_print(console, entity.x, entity.y, entity.char, fg=entity.color)
                drawn_positions.add(pos)
            else:
                # If tile has been explored but is not currently visible, show a generic marker
                # Only show last-known marker for Items (not corpses or other non-actors)
                if self.explored[entity.x, entity.y] and pos not in drawn_positions and isinstance(entity, Item):
                    try:
                        self.screen_print(console, entity.x, entity.y, "*", fg=color.gray)
                        drawn_positions.add(pos)
                    except Exception:
                        try:
                            self.screen_print(console, entity.x, entity.y, "*", fg=(192,192,192))
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
                # Render at full color — GPU lightmap MOD pass in main.py handles dimming.
                self.screen_print(console, entity.x, entity.y, entity.char, fg=entity.color)
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
            self.fungi = []  # Global list of fungi in the world
            self._noise_rng = None

            # Noise values
            self.noise_temperature = None
            self.noise_erosion = None
            self.noise_weirdness = None


    def sample_noise(self, noise, x, scale):

        weight = 18

        return (
            noise.get_point(x * scale * 0.05) * 8.0 +
            noise.get_point(x * scale * 0.15) * 8.0 +
            noise.get_point(x * scale * 0.5) * 2.0
        ) / weight


    def generate_noise(self, floor_num: int) -> None:
        import tcod
        from setup_game import _current_seed

        self.noise_temperature = tcod.noise.Noise(dimensions=1, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=_current_seed+1)
        self.noise_erosion = tcod.noise.Noise(dimensions=1, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=_current_seed+2)
        self.noise_vegetation = tcod.noise.Noise(dimensions=1, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=_current_seed+3)
        self.noise_weirdness = tcod.noise.Noise(dimensions=1, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=_current_seed+4)


        # Clamped noise sampling, scaled
        t = self.sample_noise(self.noise_temperature, floor_num*2.0, 0.3) * 10
        e = self.sample_noise(self.noise_erosion, floor_num*2.0, 0.8) * 10.0
        v = self.sample_noise(self.noise_vegetation, floor_num*2.0, 1.2) * 10.0
        w = self.sample_noise(self.noise_weirdness, floor_num*2.0, 2.0) * 10.0

        t *= 2.0
        e *= 2.0
        v *= 2.0
        w *= 2.0

        print(f"World noise at floor {floor_num}: Temperature={t:.2f}, Erosion={e:.2f}, Vegetation={v:.2f}, Weirdness={w:.2f}.")

        return(t, e, v, w)

    def generate_world(self) -> None:
        """Generate the starting floor."""
        from procgen import generate_dungeon

        self.engine.game_map = generate_dungeon(
            max_rooms=self.max_rooms,
            room_min_size=self.room_min_size,
            room_max_size=self.room_max_size,
            map_width=self.map_width,
            map_height=self.map_height,
            engine=self.engine,
            floor_num=1,
            noise_vals = (self.generate_noise(1))
        )
        self.current_floor = 1


    def generate_floor(self) -> None:
        from procgen import generate_dungeon, generate_village, generate_tutorial_floor
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
        if 1 == 1:
            print("Generating village floor!")
            # Generate village and reset counter
            self.floors_since_village = 0  # Reset counter when village appears
            self.engine.game_map = generate_village(
                map_width=self.map_width,
                map_height=self.map_height,
                engine=self.engine,
            )
        else:
            # Generate dungeon (counter continues to accumulate)
            self.descend()  # Use the same generation method as normal descents
    def descend(self) -> None:
        """Descend one level."""
        # Save current floor to the up-stack so we can return to it.
        current_map = self.engine.game_map
        player_pos = (self.engine.player.x, self.engine.player.y)
        self.up_stack.append((current_map, player_pos, self.current_floor))

        # If we previously ascended from a floor below, reuse it instead of
        # regenerating so the player returns to the same dungeon layout.
        if self.down_stack:
            next_map, next_player_pos, next_floor = self.down_stack.pop()
            self.current_floor = next_floor
            self.engine.game_map = next_map
            px, py = next_player_pos
            self.engine.player.place(px, py, next_map)
        else:
            from procgen import generate_dungeon
            self.current_floor += 1
            new_map = generate_dungeon(
                max_rooms=self.max_rooms,
                room_min_size=self.room_min_size,
                room_max_size=self.room_max_size,
                map_width=self.map_width,
                map_height=self.map_height,
                engine=self.engine,
                noise_vals=self.generate_noise(self.current_floor),
                floor_num=self.current_floor,
            )
            self.engine.game_map = new_map
        # Clear stale animations from the previous floor.
        anim_q = getattr(self.engine, "animation_queue", None)
        if anim_q is not None:
            try:
                anim_q.clear()
            except Exception:
                while anim_q:
                    anim_q.popleft()

    def ascend(self) -> None:
        """Ascend one level."""
        if len(self.up_stack) == 0:
            return

        # Save current floor to the down-stack so descending again reuses it.
        current_map = self.engine.game_map
        player_pos = (self.engine.player.x, self.engine.player.y)
        self.down_stack.append((current_map, player_pos, self.current_floor))

        # Restore previous floor
        prev_map, prev_player_pos, prev_floor = self.up_stack.pop()
        self.engine.game_map = prev_map
        self.current_floor = prev_floor
        
        # Clear stale animations from the previous floor.
        anim_q = getattr(self.engine, "animation_queue", None)
        if anim_q is not None:
            try:
                anim_q.clear()
            except Exception:
                while anim_q:
                    anim_q.popleft()

        # Restore player position  
        px, py = prev_player_pos
        self.engine.player.place(px, py, prev_map)

