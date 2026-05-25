from __future__ import annotations

import lzma
import pickle
import traceback
from typing import TYPE_CHECKING, Optional
import os
import math
import numpy as np
from tcod.console import Console
from tcod.map import compute_fov
from collections import deque
import random

from components import equipment
import components
import exceptions
import game_map
from liquid_system import LiquidType
from message_log import MessageLog
import render_functions
import sounds
from animations import TextPopupAnimation, WaterMoveAnimation, GlobalWaterAnimation, GlobalOceanAnimation, GlobalBeachWaterAnimation, GlobalRiverAnimation, GlobalDungeonWaterAnimation
import color

if TYPE_CHECKING:
    from entity import Actor
    from game_map import GameMap, GameWorld
    from actions import Action

import time
from animations import FireFlicker, BonefireFlicker, FlameAnimation
from gpu_stack import SmokeCloudParticle, EmberParticle, DripParticle, LightShaftParticles, BurningParticle, SleepingParticle, DustParticle
import sprite_manager
import tcod.noise


class Engine:

    game_map: Optional[GameMap]
    game_world: Optional[GameWorld]

    def __init__(self, player: Optional[Actor] = None):
        self.message_log = MessageLog()
        self.mouse_location = (0,0)
        self.player = player
        self.mouse_held = False

        # Tutorial checkpoints
        self.tutorial_checkpoints: list = []
        
        self.animation_queue = deque()
        self.animations_enabled = True
        self.debug = False
        self.cursor_hint = None 
        self.context_hints = []
        self.show_minimap = 1  # 0=map, 1=keys, 2=minimized, 3=hidden
        self._dungeon_minimap_state = 1  # Last minimap state used in a dungeon/level
        self.hovered_inventory_button = None
        
        # Initialize turn manager for centralized turn processing
        self.turn_manager = None  # Will be set after import to avoid circular imports
        self.tick_count = 0
        self._ambient_particle_tick = 0
        self._ambient_particle_interval = 2
        self._ambient_particle_caps = {
            "dust_tile": 3,
            "dust_global": 120,
        }
        self._ambient_particle_gates = {
            "dust": None,
        }
        
        # Damage indicator system
        self.damage_indicator_timer = 0
        self.damage_indicator_duration = 20  # frames to show damage indicator
        self.pending_damage_glitch = False   # set True when player takes damage; consumed by main.py
        
        # Movement sound system
        self.last_movement_time = 0
        self.min_time_between_sounds = 0.15  # Minimum 150ms between walk sounds

        
        # Sound control flags
        self.is_generating_world = False  # Flag to suppress sounds during world generation
        self.is_transitioning_level = False  # Flag to suppress sounds during level transitions
        
        # Grass wave system
        self.grass_wave_timer = 0
        self.grass_wave_cooldown = 180  # Ticks between waves (about 3 seconds at 60fps)
        self.active_grass_waves = []
        # Store speech bubble anims
        self.speech_bubbles: list = []
        # Store swimming anims
        self.swimming_entities: list = []

        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_ui_x = 0
        self.mouse_ui_y = 0

        # Auto-movement (pathfind-to-click)
        self.auto_move_path = []  # List of (x, y) tuples remaining in the queued path
        self._last_auto_move_time = 0.0
        self._auto_move_step_interval = 0.05
        self._pending_handler = None  # Handler change queued by auto-move (e.g. GameOver)
        self._pending_handler_ready = False  # Delay until one final sprite-update frame completes before switching handler

        # Turn counter and doge 
        self.turn_count = 0
        # Persistent Simplex noise generator for torch/fire flicker.
        # Stored on the engine (not per-map) so the animation is continuous
        # across floor transitions and is preserved in save files.
        self._noise_gen = tcod.noise.Noise(
            dimensions=2, algorithm=tcod.noise.Algorithm.PERLIN
        )
        # Scrolling time variable that advances 0.2 per frame, matching the
        # libtcod demo's fov_torchx.  Used to derive per-source wobble (dx, dy)
        # and intensity delta (di) for torch/fire flicker.
        self._torch_t: float = 0.0

        # F1 lag profiler overlay toggle (independent of F2 debug mode).
        self.show_lag_profiler = False

        # Lightweight frame profiler (used by F1 lag chart).
        self.lag_profiler = {
            "ema_ms": {},
            "last_frame_ms": {},
            "external_frame_ms": {},
            "frame_count": 0,
        }

        # Camera smoothing state (camera-only interpolation).
        self.camera_tile_x = 0
        self.camera_tile_y = 0
        self.camera_render_x = 0.0
        self.camera_render_y = 0.0
        self.camera_smoothing = 0.25
        self._camera_initialized = False

    def profile_external_ms(self, section: str, elapsed_ms: float) -> None:
        """Queue a profiling sample (milliseconds) from non-tick systems.

        Samples are merged into the next tick frame report so F2 shows them in
        the same chart as core engine timings.
        """
        try:
            profiler = getattr(self, "lag_profiler", None)
            if not isinstance(profiler, dict):
                return

            ms = max(0.0, float(elapsed_ms))
            ext = profiler.setdefault("external_frame_ms", {})
            ext[section] = float(ext.get(section, 0.0) or 0.0) + ms
        except Exception:
            pass

    def _profile_section(self, section: str, elapsed_seconds: float) -> None:
        """Record one timing sample for a named section as an EMA in milliseconds."""
        try:
            profiler = getattr(self, "lag_profiler", None)
            if not isinstance(profiler, dict):
                return

            elapsed_ms = max(0.0, float(elapsed_seconds) * 1000.0)
            ema_map = profiler.setdefault("ema_ms", {})
            alpha = 0.2  # EMA smoothing factor.
            previous = float(ema_map.get(section, elapsed_ms))
            ema_map[section] = previous + (elapsed_ms - previous) * alpha
        except Exception:
            pass

    def _finalize_frame_profile(self, frame_samples_ms: dict[str, float]) -> None:
        """Commit frame samples and update smoothed profiler values."""
        try:
            profiler = getattr(self, "lag_profiler", None)
            if not isinstance(profiler, dict):
                return

            ext = profiler.get("external_frame_ms", {}) or {}
            if isinstance(ext, dict) and ext:
                for section, ms in ext.items():
                    frame_samples_ms[section] = float(frame_samples_ms.get(section, 0.0) or 0.0) + float(ms or 0.0)
                # Keep total coherent with merged sections.
                frame_samples_ms["total"] = float(frame_samples_ms.get("total", 0.0) or 0.0) + sum(
                    float(v or 0.0) for v in ext.values()
                )
                profiler["external_frame_ms"] = {}

            profiler["last_frame_ms"] = dict(frame_samples_ms)
            profiler["frame_count"] = int(profiler.get("frame_count", 0)) + 1
            for section, ms in frame_samples_ms.items():
                self._profile_section(section, ms / 1000.0)
        except Exception:
            pass

    def get_camera_origin(self, view_width: int, view_height: int) -> tuple[int, int]:
        """Return the top-left world tile of the current viewport, centering the player."""
        if not self.game_map or not self.player:
            return 0, 0

        max_x = max(0, self.game_map.width - view_width)
        max_y = max(0, self.game_map.height - view_height)
        # Center player in viewport
        origin_x = min(max(0, self.player.x - view_width // 2), max_x)
        origin_y = min(max(0, self.player.y - view_height // 2), max_y)
        return origin_x, origin_y

    def world_to_screen(self, x: int, y: int, view_width: int, view_height: int) -> Optional[tuple[int, int]]:
        """Convert a world-space tile into viewport-relative console coordinates."""
        origin_x, origin_y = self.get_camera_origin(view_width, view_height)
        screen_x = int(x) - origin_x
        screen_y = int(y) - origin_y
        if 0 <= screen_x < view_width and 0 <= screen_y < view_height:
            return screen_x, screen_y
        return None

    def screen_to_world(self, x: int, y: int, view_width: int, view_height: int) -> Optional[tuple[int, int]]:
        """Convert viewport-relative console coordinates into world-space tile coordinates."""
        if not self.game_map:
            return None

        origin_x, origin_y = self.get_camera_origin(view_width, view_height)
        x_f = float(x)
        y_f = float(y)

        # Keep input mapping aligned with camera-smoothed world render offset.
        tile_px_w = float(getattr(self, "base_tile_w", 0.0) or 0.0)
        tile_px_h = float(getattr(self, "base_tile_h", 0.0) or 0.0)
        zoom = float(getattr(self, "game_zoom", 1.0) or 1.0)
        if tile_px_w > 0.0 and tile_px_h > 0.0 and zoom > 0.0:
            cam_off_x, cam_off_y = self.get_camera_render_offset_px(tile_px_w * zoom, tile_px_h * zoom)
            x_f -= float(cam_off_x) / (tile_px_w * zoom)
            y_f -= float(cam_off_y) / (tile_px_h * zoom)

        # Convert to nearest tile so interaction remains accurate while camera eases.
        # Half-away-from-zero avoids banker's rounding jitter at .5 boundaries.
        screen_x_i = int(x_f + 0.5) if x_f >= 0.0 else int(x_f - 0.5)
        screen_y_i = int(y_f + 0.5) if y_f >= 0.0 else int(y_f - 0.5)
        screen_x = min(max(screen_x_i, 0), max(0, int(view_width) - 1))
        screen_y = min(max(screen_y_i, 0), max(0, int(view_height) - 1))

        world_x = origin_x + screen_x
        world_y = origin_y + screen_y
        if self.game_map.in_bounds(world_x, world_y):
            return world_x, world_y
        return None

    def get_adjacent_tiles(self, x: int, y: int) -> list[tuple[int, int]]:
        # Returns adjacent (including diagonals) tiles
        adjacent = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                adjacent.append((x + dx, y + dy))

        return adjacent

    def should_play_movement_sound(self) -> bool:
        """Check if movement sound should play (prevents rapid-fire from holding keys)."""
        current_time = time.time()
        
        # Check if enough time has passed since the last movement sound
        time_since_last = current_time - self.last_movement_time
        
        if time_since_last >= self.min_time_between_sounds:
            self.last_movement_time = current_time
            return True
        else:
            return False

    def debug_log(self, message: str, handler: Optional[str] = None, event: Optional[str] = None) -> None:
        """Log a debug message if debug mode is enabled."""
        if not self.debug:
            return
        print(f"[DEBUG] {message}")
        log_path = "logs/log.txt"
        os.makedirs("logs", exist_ok=True)
        with open(log_path, "a") as log_file:
            log_file.write(f" {time.ctime()}: Handler: {handler}, Event: {event}, Message: {message}\n")

    def update_camera_interpolation(
        self,
        tile_px_w: float,
        tile_px_h: float,
        view_width: int,
        view_height: int,
    ) -> None:
        """Smooth camera render position while keeping world updates tile-snapped."""
        if not self.player:
            self._camera_initialized = False
            return

        origin_x, origin_y = self.get_camera_origin(int(view_width), int(view_height))
        self.camera_tile_x = int(origin_x)
        self.camera_tile_y = int(origin_y)

        target_x = float(self.camera_tile_x) * float(tile_px_w)
        target_y = float(self.camera_tile_y) * float(tile_px_h)

        if not self._camera_initialized:
            self.camera_render_x = target_x
            self.camera_render_y = target_y
            self._camera_initialized = True
            return

        smoothing = float(getattr(self, "camera_smoothing", 0.16) or 0.16)
        if getattr(self, "auto_move_path", None):
            smoothing = max(smoothing, 0.24)
        smoothing = min(max(smoothing, 0.0), 1.0)
        self.camera_render_x += (target_x - self.camera_render_x) * smoothing
        self.camera_render_y += (target_y - self.camera_render_y) * smoothing

        if abs(target_x - self.camera_render_x) < 0.01:
            self.camera_render_x = target_x
        if abs(target_y - self.camera_render_y) < 0.01:
            self.camera_render_y = target_y

    def get_camera_render_offset_px(self, tile_px_w: float, tile_px_h: float) -> tuple[int, int]:
        """Return rounded pixel offset to apply to the rendered world texture."""
        target_x = float(self.camera_tile_x) * float(tile_px_w)
        target_y = float(self.camera_tile_y) * float(tile_px_h)
        dx = target_x - self.camera_render_x
        dy = target_y - self.camera_render_y
        # Use deterministic half-away-from-zero rounding to avoid frame-to-frame
        # wobble from Python's banker's rounding at +/-0.5.
        off_x = int(dx + 0.5) if dx >= 0.0 else int(dx - 0.5)
        off_y = int(dy + 0.5) if dy >= 0.0 else int(dy - 0.5)
        return off_x, off_y

    def _effect_list(self, target) -> list:
        effects = getattr(target, "effects", None)
        if effects is None:
            effects = []
            setattr(target, "effects", effects)
        return effects

    def has_effect(self, target, effect_cls) -> bool:
        return any(isinstance(effect, effect_cls) for effect in self._effect_list(target))

    def add_or_refresh_effect(self, target, effect):
        effects = self._effect_list(target)
        for existing in effects:
            if isinstance(existing, effect.__class__):
                if existing.duration is None or effect.duration is None:
                    existing.duration = None
                else:
                    existing.duration = max(existing.duration, effect.duration)
                try:
                    existing.on_apply(target)
                except Exception:
                    pass
                return existing
        effects.append(effect)
        try:
            effect.on_apply(target)
        except Exception:
            pass
        return effect

    def tutorial_ticking(self, console: Console):
        for entity in self.game_map.entities:
            if getattr(entity, "type", None) == "Guide":
                guide = entity
                break
        try:
            if "start" not in self.tutorial_checkpoints:
                self.tutorial_checkpoints.append("start")
                guide.ai.say(custom="Welcome adventurer. Use WASD or right click to move. Try it out a bit!")
            else:
                if "moved" not in self.tutorial_checkpoints:
                    if self.turn_count > 5:
                        self.tutorial_checkpoints.append("moved")
                        guide.ai.say(custom="Excellent. Now, move to that chest northward, and right click on it to get some basic equipment.")
                else:
                    if "looted" not in self.tutorial_checkpoints:
                        if len(self.player.inventory.items) > 0:
                            self.tutorial_checkpoints.append("looted")
                            guide.ai.say(custom="Well done. Equip items using the (TAB) inventory. Try defeating that training dummy by moving into it, or left clicking it.")
                    else:
                        if "defeat" not in self.tutorial_checkpoints:
                            dummy = next((e for e in self.game_map.entities if getattr(e, "name", None) == "Training Dummy"), None)
                            if not dummy or (dummy.fighter and dummy.fighter.hp <= 0):
                                self.tutorial_checkpoints.append("defeat")
                                guide.ai.say(custom="That was a real challenge. You will gain levels as you hone your skills (F). Open your inventory (TAB) and use the sigil stone from the chest.")
                        else:
                            if "stoneused" not in self.tutorial_checkpoints:
                                # check if player has level 2 arcana
                                if self.player.level and self.player.level.traits['arcana']['level'] >= 2:
                                    self.tutorial_checkpoints.append("stoneused")
                                    guide.ai.say(custom="Well done. Access the controls menu (M) if you need a refresher. Ascend (>) the stairs to the west, and best of luck traveller.")
        except Exception as e:
            print(f"ERROR: Exception in tutorial ticking: {e}")


    
    def tick(self, console: Console):
        _frame_start = time.perf_counter()
        _frame_samples_ms: dict[str, float] = {}

        def _mark(section_name: str, section_start: float) -> None:
            _frame_samples_ms[section_name] = _frame_samples_ms.get(section_name, 0.0) + (
                (time.perf_counter() - section_start) * 1000.0
            )


        # Calculate tick rate per second
        now = time.monotonic()
        _last = getattr(self, "_last_tick_time", None)

        if _last is None:
            # first tick: initialize storage
            self._last_tick_time = now
            self._tick_intervals = deque(maxlen=120)  # smooth over last N frames
            self.tick_rate = 0.0
        else:
            dt = now - _last
            self._last_tick_time = now
            if dt > 0:
                self._tick_intervals.append(dt)
                total = sum(self._tick_intervals)
                # ticks per second = number of recorded ticks / total time covered
                self.tick_rate = (len(self._tick_intervals) / total) if total > 0 else 0.0
            else:
                # very unlikely, but avoid division by zero
                self.tick_rate = getattr(self, "tick_rate", 0.0)

        # Always clean up expired animations regardless of map type.
        _section_start = time.perf_counter()
        expired = [anim for anim in list(self.animation_queue) if getattr(anim, "frames", 1) <= 0]
        for anim in expired:
            try:
                self.animation_queue.remove(anim)
            except ValueError:
                pass
        _mark("cleanup", _section_start)

        # Always advance auto-move regardless of map type.
        _section_start = time.perf_counter()
        auto_path = getattr(self, 'auto_move_path', None)
        if auto_path and getattr(self, 'turn_manager', None):
            self.cursor_hint = "walk"
            now_am = time.monotonic()
            auto_step_interval = float(getattr(self, "_auto_move_step_interval", 0.05) or 0.05)
            if now_am - self._last_auto_move_time >= auto_step_interval:
                _am_scan_start = time.perf_counter()
                enemy_visible = any(
                    actor is not self.player and self.game_map.visible[actor.x, actor.y] and isinstance(actor.ai, components.ai.HostileEnemy)
                    for actor in self.game_map.actors
                )
                _mark("autopath_scan", _am_scan_start)
                if enemy_visible:
                    self.auto_move_path = []
                    self.cursor_hint = None
                    self.message_log.add_message("No longer pathing, spotted an enemy.", color.yellow)
                else:
                    next_pos = auto_path.pop(0)
                    dx = next_pos[0] - self.player.x
                    dy = next_pos[1] - self.player.y
                    from actions import MovementAction
                    try:
                        _am_step_start = time.perf_counter()
                        # execute_action with is_player_action=True already runs
                        # pre/post turn processing. Calling turn_manager methods
                        # separately here double-processes a turn and is very costly.
                        result = self.execute_action(
                            MovementAction(self.player, dx, dy),
                            is_player_action=True,
                        )
                        _mark("autopath_step", _am_step_start)
                        self._last_auto_move_time = now_am
                        if not auto_path:
                            self.cursor_hint = None
                        if result is not None:
                            self.auto_move_path = []
                            self.cursor_hint = None
                            self._pending_handler = result
                    except exceptions.Impossible as exc:
                        _mark("autopath_step", _am_step_start)
                        self.auto_move_path = []
                        self.cursor_hint = None
                        self.message_log.add_message(exc.args[0], color.impossible)
        _mark("auto_move", _section_start)

        # Handle tutorial-specific ticking for tutorial maps
        _section_start = time.perf_counter()
        if hasattr(self, 'game_map') and getattr(self.game_map, 'biome', None) == "tutorial":
            self.tutorial_ticking(console)
        _mark("tutorial", _section_start)
        


        # Generate grass waves that sweep across the visible area
        # Disabled on the overworld — it uses a Dwarf Fortress-style tile map.
        _section_start = time.perf_counter()
        try:
            if getattr(self.game_map, 'type', '') != 'overworld':
                self.grass_wave_timer += 1
             
                # Start a new wave periodically
                if self.grass_wave_timer >= self.grass_wave_cooldown:
                    self.grass_wave_timer = 0
                    # Create a new wave from a random edge
                    self._spawn_grass_wave()
                
                # Update existing waves
                for wave in list(self.active_grass_waves):
                    self._update_grass_wave(wave)
                
        except Exception:
            traceback.print_exc()
        _mark("grass_waves", _section_start)


        # Body part coating system moved to turn_manager.py

        # Keep a single persistent GlobalWaterAnimation instead of per-tile spawns
        _section_start = time.perf_counter()
        if not any(type(a).__name__ == 'GlobalWaterAnimation' for a in self.animation_queue):
            from animations import GlobalWaterAnimation
            self.animation_queue.appendleft(GlobalWaterAnimation())
        if not any(type(a).__name__ == 'GlobalOceanAnimation' for a in self.animation_queue):
            from animations import GlobalOceanAnimation
            self.animation_queue.appendleft(GlobalOceanAnimation())
        if not any(type(a).__name__ == 'GlobalBeachWaterAnimation' for a in self.animation_queue):
            from animations import GlobalBeachWaterAnimation
            self.animation_queue.appendleft(GlobalBeachWaterAnimation())
        if not any(type(a).__name__ == 'GlobalRiverAnimation' for a in self.animation_queue):
            from animations import GlobalRiverAnimation
            self.animation_queue.appendleft(GlobalRiverAnimation())
        if not any(type(a).__name__ == 'GlobalDungeonWaterAnimation' for a in self.animation_queue):
            from animations import GlobalDungeonWaterAnimation
            self.animation_queue.appendleft(GlobalDungeonWaterAnimation())
        _mark("global_anims", _section_start)

        # Spawn directional light shaft particles for visible Window tiles.
        # Check north (y-1) and south (y+1) independently: if that side is open
        # (transparent), spawn a shaft going in that direction.
        _section_start = time.perf_counter()
        if self.animations_enabled and hasattr(self, 'game_map'):
            existing_shafts = {
                (int(a.fx), int(a.fy), a.shaft_direction)
                for a in self.animation_queue
                if isinstance(a, LightShaftParticles) and a.frames > 0
            }
            visible_windows = np.argwhere(
                self.game_map.visible & (self.game_map.tiles["name"] == "Window")
            )
            for x, y in visible_windows:
                ix, iy = int(x), int(y)
                # North side open → shaft goes north (up on screen, direction=-1)
                if (self.game_map.in_bounds(ix, iy - 1)
                        and self.game_map.tiles[ix, iy - 1]["transparent"]
                        and (ix, iy, -1) not in existing_shafts):
                    self.animation_queue.append(LightShaftParticles((ix, iy), shaft_direction=-1))
                # South side open → shaft goes south (down on screen, direction=+1)
                if (self.game_map.in_bounds(ix, iy + 1)
                        and self.game_map.tiles[ix, iy + 1]["transparent"]
                        and (ix, iy, 1) not in existing_shafts):
                    self.animation_queue.append(LightShaftParticles((ix, iy), shaft_direction=1))
            _mark("light_shafts", _section_start)

        
        _section_start = time.perf_counter()
        try:
            # Build particle count cache once per frame to avoid O(n*m) lookups
            tile_fire_counts, entity_fire_counts, position_ember_counts, position_drip_counts, position_dust_counts = self._build_particle_count_cache()

            self._tick_ambient_particles(position_dust_counts)
            
            # Get liquid system - check for fire coatings on tiles (outside entity loop)
            for coating in self.game_map.liquid_system.coatings.values():
                if coating.liquid_type == LiquidType.FIRE:
                    pos = coating.get_pos()
                    # Count existing tile-based fire particles at this position
                    FIRE_CAP = 36
                    current_fires = tile_fire_counts.get(pos, 0)
                    # Spawn multiple particles per tick (like entities do)
                    if current_fires < FIRE_CAP:
                        for _ in range(random.randint(3, 5)):
                            self.animation_queue.append(BurningParticle(pos, None))
            
            for entity in list(self.game_map.entities):
                # Update corpse sprite based on whether it still has loot
                if getattr(entity, 'type', None) == 'Dead' and hasattr(entity, 'container') and entity.container:
                    has_loot = bool(entity.container.items)
                    current_cp = ord(entity.char) if isinstance(entity.char, str) else entity.char
                    in_loot_range = 0xE013 <= current_cp <= 0xE015
                    in_empty_range = 0xE010 <= current_cp <= 0xE012
                    if has_loot and not in_loot_range:
                        entity.char = random.choice([chr(0xE013), chr(0xE014), chr(0xE015)])
                    elif not has_loot and not in_empty_range:
                        entity.char = random.choice([chr(0xE010), chr(0xE011), chr(0xE012)])
                # Update actor sprite if swimming state changed

                # Get Quest Givers on map
                if hasattr(entity, "type"):
                    if entity.type == "Quest Giver":

                        # Spawn a flicker or glow animation to highlight quest giver
                        if self.animations_enabled and random.random() < .10: 
                            try:
                                from animations import GivingQuestAnimation
                                # Pass the entity reference instead of static coordinates
                                self.animation_queue.append(GivingQuestAnimation(entity))
                            except Exception:
                                traceback.print_exc()
                                pass
                
                # Check entities for fire coatings on body parts
                if hasattr(entity, 'body_parts') and entity.body_parts:
                    # Check if this entity has fire coating on any body part
                    has_fire_coating = any(
                        part.coating == LiquidType.FIRE 
                        for part in entity.body_parts.body_parts.values()
                    )
                    
                    if has_fire_coating:
                        # Spawn a burst of flame sparks each turn, capped so the
                        # queue doesn't grow unbounded for long-burning entities.
                        FIRE_CAP = 36
                        current_fires = entity_fire_counts.get(entity, 0)
                        if current_fires < FIRE_CAP:
                            for _ in range(random.randint(3, 5)):
                                self.animation_queue.append(
                                    BurningParticle((entity.x, entity.y), entity))

                    # Spawn drip particles for blood/water body-part coatings
                    if self.animations_enabled and getattr(entity, 'ai', True) is not None:
                        drip_coatings = [
                            part.coating for part in entity.body_parts.body_parts.values()
                            if part.coating in (LiquidType.BLOOD, LiquidType.WATER)
                        ]
                        if drip_coatings:
                            drip_cap = 3
                            current_drips = position_drip_counts.get((entity.x, entity.y), 0)
                            if current_drips < drip_cap and random.random() < 0.15:
                                coating = drip_coatings[0]
                                drip_color = (180, 20, 20) if coating == LiquidType.BLOOD else (80, 140, 220)
                                self.animation_queue.append(DripParticle((entity.x, entity.y), drip_color))
                
                
                # Periodically spawn fire animations for campfire and bonfire items on the map.
                # Get campfire and bonfire on map
                

                if entity.name in ("Campfire", "Bonfire"):
                    # Spawn flicker more frequently and independently from smoke.
                    if self.animations_enabled:
                        try:
                            

                            # Flicker: always keep one running per position
                            pos = (entity.x, entity.y)
                            is_bonfire = entity.name == "Bonfire"
                            smoke_chance = 0.08 if is_bonfire else 0.05
                            if entity.name == "Campfire":
                                if not any(isinstance(a, FireFlicker) and a.position == pos for a in self.animation_queue):
                                    self.animation_queue.append(FireFlicker(pos))
                            elif is_bonfire:
                                if not any(isinstance(a, BonefireFlicker) and a.position == pos for a in self.animation_queue):
                                    self.animation_queue.append(BonefireFlicker(pos))

                            # Smoke: rarer, longer lasting
                            if random.random() < smoke_chance:
                                self.animation_queue.append(SmokeCloudParticle((entity.x, entity.y-0.5)))

                            # Embers: bright single-pixel sparks for heavy bloom
                            ember_chance = 0.20 if is_bonfire else 0.10
                            ember_cap = 8 if is_bonfire else 4
                            if random.random() < ember_chance:
                                current_embers = position_ember_counts.get(pos, 0)
                                if current_embers < ember_cap:
                                    self.animation_queue.append(EmberParticle(pos))
                        except Exception:
                            pass
                
                # Get sigil stone items on map
                if entity.name == "Sigil Stone":
                    # Spawn pulsing animation only occasionally since they now loop forever
                    if self.animations_enabled:
                        try:
                            from animations import SigilStoneAnimation
                            
                            # Very low chance since animations loop - we only need one per sigil stone
                            if random.random() < 0.01:  # 1% chance per tick
                                # Check if there's already an animation at this position
                                position = (entity.x, entity.y)
                                has_existing_animation = any(
                                    hasattr(anim, 'position') and anim.position == position 
                                    and type(anim).__name__ == 'SigilStoneAnimation'
                                    for anim in self.animation_queue
                                )
                                if not has_existing_animation:
                                    self.animation_queue.append(SigilStoneAnimation(position))
                        except Exception:
                            pass

                # Keep exactly one persistent IlluminatedParticle per illuminated entity
                if self.animations_enabled:
                    try:
                        is_illuminated = any(
                            getattr(e, 'name', '') == 'Illuminated'
                            for e in getattr(entity, 'effects', [])
                        )
                        if is_illuminated:
                            from gpu_stack import IlluminatedParticle as _IllumP
                            already = any(
                                type(a).__name__ == 'IlluminatedParticle'
                                and a.entity is entity
                                and a.frames > 0
                                for a in self.animation_queue
                            )
                            if not already:
                                self.animation_queue.append(_IllumP(entity))
                    except Exception:
                        pass

                if self.animations_enabled:
                    try:
                        is_sleeping = any(
                            getattr(e, 'name', '') == 'Sleep'
                            for e in getattr(entity, 'effects', [])
                        )
                        if is_sleeping:
                            already = any(
                                type(a).__name__ == 'SleepingParticle'
                                and a.entity is entity
                                and a.frames > 0
                                for a in self.animation_queue
                            )
                            if not already:
                                self.animation_queue.append(SleepingParticle(entity))
                    except Exception:
                        pass
        
            # Update ambient sounds based on player proximity
            sounds.update_all_ambient_sounds(self.player, self.game_map.entities, self.game_map)
        except Exception:
            traceback.print_exc()
            pass
        _mark("entity_updates", _section_start)

        _frame_samples_ms["total"] = (time.perf_counter() - _frame_start) * 1000.0
        self._finalize_frame_profile(_frame_samples_ms)
    
    def _build_particle_count_cache(self):
        """Build a cache of particle counts by position and entity to avoid O(n*m) lookups.
        
        Returns:
            tuple: (tile_fire_counts, entity_fire_counts, position_ember_counts, position_drip_counts, position_dust_counts)
                - tile_fire_counts: dict mapping (x, y) -> count of tile-based BurningParticles
                - entity_fire_counts: dict mapping entity -> count of entity-based BurningParticles  
                - position_ember_counts: dict mapping (x, y) -> count of EmberParticles
                - position_drip_counts: dict mapping (x, y) -> count of DripParticles
                - position_dust_counts: dict mapping source tile -> count of DustParticles
        """
        tile_fire_counts = {}
        entity_fire_counts = {}
        position_ember_counts = {}
        position_drip_counts = {}
        position_dust_counts = {}
        
        for anim in self.animation_queue:
            if isinstance(anim, BurningParticle):
                entity = getattr(anim, 'entity', None)
                if entity is None:
                    # Tile-based fire particle
                    pos = (int(round(anim.fx)), int(round(anim.fy)))
                    tile_fire_counts[pos] = tile_fire_counts.get(pos, 0) + 1
                else:
                    # Entity-based fire particle
                    entity_fire_counts[entity] = entity_fire_counts.get(entity, 0) + 1
            elif isinstance(anim, EmberParticle):
                pos = (int(round(anim.fx)), int(round(anim.fy)))
                position_ember_counts[pos] = position_ember_counts.get(pos, 0) + 1
            elif isinstance(anim, DripParticle):
                pos = (int(round(anim.fx)), int(round(anim.fy)))
                position_drip_counts[pos] = position_drip_counts.get(pos, 0) + 1
            elif isinstance(anim, DustParticle):
                pos = getattr(anim, 'source_pos', (int(round(anim.fx)), int(round(anim.fy))))
                position_dust_counts[pos] = position_dust_counts.get(pos, 0) + 1
        
        return tile_fire_counts, entity_fire_counts, position_ember_counts, position_drip_counts, position_dust_counts

    def _tick_ambient_particles(self, position_dust_counts: dict[tuple[int, int], int]) -> None:
        """Spawn ambient particles on a fixed cadence with per-tile and global caps."""
        if not self.animations_enabled or not hasattr(self, 'game_map'):
            return

        self._ambient_particle_tick += 1
        if self._ambient_particle_tick % self._ambient_particle_interval != 0:
            return

        dust_global_cap = int(self._ambient_particle_caps.get("dust_global", 0))
        if sum(position_dust_counts.values()) >= dust_global_cap:
            return

        visible_tiles = np.argwhere(self.game_map.visible)
        if len(visible_tiles) == 0:
            return

        sample_count = min(len(visible_tiles), 96)
        sampled_indices = random.sample(range(len(visible_tiles)), sample_count)
        tile_cap = int(self._ambient_particle_caps.get("dust_tile", 0))

        for idx in sampled_indices:
            x_raw, y_raw = visible_tiles[idx]
            x, y = int(x_raw), int(y_raw)
            pos = (x, y)
            if position_dust_counts.get(pos, 0) >= tile_cap:
                continue
            if not self._is_dust_ambient_tile(x, y):
                continue

            spawn_chance = 0.32
            if random.random() >= spawn_chance:
                continue

            self.animation_queue.append(DustParticle(pos))
            position_dust_counts[pos] = position_dust_counts.get(pos, 0) + 1
            if sum(position_dust_counts.values()) >= dust_global_cap:
                break

    def _is_dust_ambient_tile(self, x: int, y: int) -> bool:
        if not self.game_map.in_bounds(x, y):
            return False

        tile = self.game_map.tiles[x, y]
        if not bool(tile["walkable"]) or not bool(tile["transparent"]):
            return False
        if tile["name"] == "Water":
            return False

        return self._passes_ambient_particle_gate("dust", x, y)

    def _passes_ambient_particle_gate(self, particle_key: str, x: int, y: int) -> bool:
        """Return True when the tile passes the configured future gate for a particle type."""
        gate = self._ambient_particle_gates.get(particle_key)
        if gate is None:
            return True
        return bool(gate(self, x, y))

    def process_animations(self):
        if not self.animation_queue:
            return
        
        for animation in list(self.animation_queue):
            animation.tick()
            if animation.frames <= 0:
                self.animation_queue.remove(animation)

    def is_actor_asleep(self, actor) -> bool:
        """Return True when the actor currently has a sleep effect."""
        try:
            from components.effect import has_effect_name
            return has_effect_name(actor, "Sleep")
        except Exception:
            return False

    def execute_action(self, action: Action, is_player_action: bool = False) -> Optional[object]:
        """
        **CENTRALIZED ACTION EXECUTION HUB**
        
        ALL actions should pass through this method to ensure:
        - Proper turn order and initiative processing
        - Status effects and environmental effects are applied
        - Consistent action logging and game state management
        
        Args:
            action: The action to execute
            is_player_action: Whether this is a player action (affects pre/post-turn processing)
        
        Returns:
            A handler if a state change is needed, None otherwise
        """
        actor = getattr(action, "entity", None)
        if actor is not None and self.is_actor_asleep(actor):
            from actions import WaitAction
            if isinstance(action, WaitAction):
                pass
            else:
                if actor is self.player:
                    self.message_log.add_message("You are asleep and cannot act.", color.impossible)
                elif getattr(actor, "name", None):
                    self.message_log.add_message(f"{actor.name} is asleep and cannot act.", color.impossible)
                return None

        # Pre-action processing (only for player actions)
        if is_player_action and self.turn_manager:
            handler_change = self.turn_manager.process_pre_player_turn()
            if handler_change:
                return handler_change
        
        # Execute the actual action
        try:
            result = action.perform()
        except exceptions.Impossible as exc:
            print(f"ERROR: Impossible action attempted: {exc.args[0]}")
            return None
        
        # Post-action processing (for player actions)
        if is_player_action and self.turn_manager:
            handler_change = self.turn_manager.process_player_turn_end()
            if handler_change:
                return handler_change
        
        # Return handler if action resulted in one, otherwise None
        return result if isinstance(result, object) and hasattr(result, '__class__') and 'BaseEventHandler' in str(result.__class__.__mro__) else None

    def save_as(self, filename: str) -> None:
        # save this engine instance as a compressed file
        save_data = lzma.compress(pickle.dumps(self))
        with open(filename, "wb") as f:
            f.write(save_data)
            # Write game savename 
            f.write(filename.encode('utf-8'))
    


    def _find_dark_spawn_pos(self, max_radius: int = 8, min_radius: int = 2):
        """Return a random (x,y) near the player that is walkable, empty and not visible.
        Returns None if none found.
        """
        player = getattr(self, "player", None)
        gm = getattr(self, "game_map", None)
        if player is None or gm is None:
            return None

        candidates = []
        for radius in range(min_radius, max_radius + 1):
            ring = []
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    # Prefer perimeter for variety
                    if abs(dx) != radius and abs(dy) != radius:
                        continue
                    x = player.x + dx
                    y = player.y + dy

                    # bounds check
                    try:
                        if not gm.in_bounds(x, y):
                            continue
                    except Exception:
                        if not (0 <= x < getattr(gm, "width", 0) and 0 <= y < getattr(gm, "height", 0)):
                            continue

                    # must be walkable
                    try:
                        if not gm.tiles["walkable"][x, y]:
                            continue
                    except Exception:
                        continue

                    # don't spawn on player or existing actor
                    try:
                        if getattr(gm, "get_actor_at_location", lambda a,b: None)(x, y):
                            continue
                    except Exception:
                        continue

                    # don't spawn on currently visible tiles
                    try:
                        if getattr(gm, "visible", None) is not None and gm.visible[x, y]:
                            continue
                    except Exception:
                        pass

                    # don't spawn on lit tiles (enemies prefer darkness)
                    try:
                        if gm.tiles["lit"][x, y]:
                            continue
                    except Exception:
                        pass

                    ring.append((x, y))

            if ring:
                candidates.extend(ring)

            if candidates:
                break

        if not candidates:
            return None

        return random.choice(candidates)


    def _maybe_spawn_enemy_in_dark(self) -> None:
        """Try to spawn an enemy when the player is in darkness.
        This is defensive and will no-op if factories or map API are unavailable.
        """
        import copy
        from components.effect import Darkness

        player = getattr(self, "player", None)
        gm = getattr(self, "game_map", None)
        if player is None or gm is None:
            return

        # Is the player currently affected by Darkness?
        in_dark = self.has_effect(player, Darkness)
        if not in_dark:
            # ensure cooldown exists but do nothing
            self._dark_spawn_cooldown = getattr(self, "_dark_spawn_cooldown", 0)
            return

        # init cooldown
        if not hasattr(self, "_dark_spawn_cooldown"):
            self._dark_spawn_cooldown = 0

        if self._dark_spawn_cooldown > 0:
            self._dark_spawn_cooldown -= 1
            return

        # spawn chance when ready
        if random.random() > 0.10:  # 20% chance per ready tick
            self._dark_spawn_cooldown = 8
            return

        spawn_pos = self._find_dark_spawn_pos(max_radius=8, min_radius=2)
        if spawn_pos is None:
            self._dark_spawn_cooldown = 8
            return

        sx, sy = spawn_pos

        # Try to find a suitable enemy template in entity_factories
        try:
            import entity_factories as factories
        except Exception:
            self._dark_spawn_cooldown = 8
            return

        enemy_template = factories.shade
        
        try:
            enemy = copy.deepcopy(enemy_template)
            enemy.x = sx
            enemy.y = sy
            enemy.parent = gm

            # Add to map using common APIs
            if hasattr(gm, "spawn"):
                try:
                    gm.spawn(enemy)
                except Exception:
                    # fallback to entities set/list
                    if hasattr(gm, "entities") and isinstance(gm.entities, set):
                        gm.entities.add(enemy)
                    elif hasattr(gm, "entities") and isinstance(gm.entities, list):
                        gm.entities.append(enemy)
                    else:
                        self._dark_spawn_cooldown = 8
                        return
            elif hasattr(gm, "entities") and isinstance(gm.entities, set):
                gm.entities.add(enemy)
            elif hasattr(gm, "entities") and isinstance(gm.entities, list):
                gm.entities.append(enemy)
            else:
                try:
                    gm.entities.add(enemy)
                except Exception:
                    self._dark_spawn_cooldown = 8
                    return

            # optional message/log
            try:
                if hasattr(self, "message_log"):
                    sounds.play_darkness_spawn_sound()
                    self.message_log.add_message("You hear something moving in the dark...")
            except Exception:
                pass
        except Exception:
            self._dark_spawn_cooldown = 8
            return

        self._dark_spawn_cooldown = 40

    def _spawn_grass_wave(self):
        """Create a new grass wave ripple from a random point in the visible area"""
        if not hasattr(self.game_map, 'visible'):
            return

        coords = np.argwhere(self.game_map.visible & (self.game_map.tiles["name"] == "Grass"))
        if not len(coords):
            return
        origin_x, origin_y = coords[random.randrange(len(coords))]
        
        wave = {
            'origin': (origin_x, origin_y),
            'radius': 0.0,
            'speed': random.uniform(0.3, 0.8),  # radius expansion per tick
            'max_radius': random.randint(4, 8),  # maximum wave radius
            'intensity': random.uniform(0.4, 0.8),  # animation trigger chance
            'wave_width': random.uniform(1.0, 2.5),  # thickness of the wave ring
            'direction': random.uniform(0, 360),  # direction the wave is moving (degrees)
            'arc_width': random.uniform(120, 180),  # how wide the arc is (degrees)
        }
        
        self.active_grass_waves.append(wave)
        

    def _update_grass_wave(self, wave):
        """Update a grass wave ripple and spawn animations in the expanding curved front"""
        from animations import GrassRustleAnimation
        import math
        
        origin_x, origin_y = wave['origin']
        radius = wave['radius']
        speed = wave['speed']
        max_radius = wave['max_radius']
        intensity = wave['intensity']
        wave_width = wave['wave_width']
        direction = wave['direction']
        arc_width = wave['arc_width']
        
        # Calculate the wave ring - tiles within the wave band
        inner_radius = max(0, radius - wave_width)
        outer_radius = radius
        
        wave_tiles = []
        
        # Convert direction and arc to radians
        direction_rad = math.radians(direction)
        arc_half = math.radians(arc_width / 2)
        
        # Find tiles in the current wave arc (curved front)
        search_range = int(outer_radius + 2)  # Add buffer for safety
        for dx in range(-search_range, search_range + 1):
            for dy in range(-search_range, search_range + 1):
                x = origin_x + dx
                y = origin_y + dy
                
                if not self.game_map.in_bounds(x, y):
                    continue
                    
                # Calculate distance and angle from origin
                distance = (dx * dx + dy * dy) ** 0.5
                
                # Check if this tile is in the wave ring distance
                if not (inner_radius <= distance <= outer_radius):
                    continue
                
                # Calculate angle from origin to this point
                if dx == 0 and dy == 0:
                    continue
                
                point_angle = math.atan2(dy, dx)
                
                # Calculate angular difference from wave direction
                angle_diff = abs(point_angle - direction_rad)
                # Handle wrap-around (angles near 0/360 degrees)
                if angle_diff > math.pi:
                    angle_diff = 2 * math.pi - angle_diff
                
                # Check if this point is within the arc width
                if angle_diff <= arc_half:
                    wave_tiles.append((x, y))
        
        # Spawn animations on grass tiles in the wave arc
        for x, y in wave_tiles:
            if (self.game_map.visible[x, y] and 
                self.game_map.tiles["name"][x, y] == "Grass" and
                random.random() < intensity):
                
                # Add some randomness to prevent all animations starting at once
                if random.random() < 0.6:  # 60% chance per tile in wave arc
                    self.animation_queue.append(GrassRustleAnimation((x, y)))
        
        # Update wave radius
        wave['radius'] += speed
        
        # Remove completed waves
        if wave['radius'] > max_radius:
            self.active_grass_waves.remove(wave)


    def update_fov(self) -> None:
        from components.effect import Darkness, DarkvisionEffect

        # Check if player has a torch equipped using optimized helper
        has_torch = False
        try:
            if self.player.equipment:
                has_torch = self.player.equipment.has_item_equipped("Torch")
        except Exception:
            has_torch = False

        # Check if player's current tile is lit by any light source
        near_light_source = False
        try:
            px, py = self.player.x, self.player.y
            if self.game_map.in_bounds(px, py):
                near_light_source = self.game_map.tiles["lit"][px, py]
        except Exception:
            near_light_source = False



        # Torch increases FOV radius; campfires only affect Darkness (lighting), not FOV
        radius = 6 if has_torch else 3
        if self.has_effect(self.player, DarkvisionEffect):
            radius = 10

        if self.game_map.sunlit:
            radius = max(radius, 1000)  # Sunlit areas have large FOV regardless of torch
        if self.game_map.biome == "tutorial":
            radius = 10
        # If player in village, greatly increase FOV radius
        if self.game_map.type == "village":
            radius = 1000

        self.game_map.visible[:] = compute_fov(
            self.game_map.tiles["transparent"],
            (self.player.x, self.player.y),
            radius,
        )

        self.game_map.explored |= self.game_map.visible

        # Apply or remove the persistent Darkness effect based on tile light level
        try:
            has_darkness = self.has_effect(self.player, Darkness)
            
            # Check current tile's light level
            current_light_level = 0.0
            if self.game_map.in_bounds(self.player.x, self.player.y):
                current_light_level = self.game_map.tiles["light_level"][self.player.x, self.player.y]
            
            # Consider tiles with only ambient light (≤ 0.1) as "dark" for darkness effects
            # This accounts for the dim view system that provides minimal visibility
            if current_light_level <= 0.2:
                # Player is in darkness (no real light sources): ensure they have the Darkness effect
                if not has_darkness:
                    self.add_or_refresh_effect(self.player, Darkness(duration=None))
            else:
                # Player has actual light sources: remove any Darkness effects
                if has_darkness:
                    self.player.effects = [e for e in self.player.effects if not isinstance(e, Darkness)]
        except Exception:
            # If anything goes wrong, don't break FOV update
            pass
            
    def render_game(self, console: Console) -> None:
        self.game_map.render(console)
        
        for bubble in self.speech_bubbles[:]:
            if bubble.tick():
                self.speech_bubbles.remove(bubble)

        for swim in self.swimming_entities[:]:
            if swim.tick():
                self.swimming_entities.remove(swim)




    def render_ui(self, console: Console, skip_debug: bool = False) -> None:
        # Render damage indicator if active - render above all HUD elements
        if self.damage_indicator_timer > 0:
            self.render_damage_indicator(console)
            self.damage_indicator_timer -= 1

        # Draw UI border and background first, before all text elements
        render_functions.render_bottom_ui_border(
            console=console
        )



        self.message_log.render(console=console, x=21, y=43, width=58, height=3)  # MESSAGE_LOG coordinates
        render_functions.render_bar(
            console=console,
            current_value=self.player.fighter.hp,
            maximum_value=self.player.fighter.max_hp,
            total_width=21
        )
        render_functions.render_lucidity_bar(
            console=console,
            current_value=self.player.lucidity,
            maximum_value=self.player.max_lucidity,
            total_width=21
        )
        render_functions.render_mana_bar(
            console=console,
            current_value=self.player.mana,
            maximum_value=self.player.mana_max,
            total_width=21
        )
        render_functions.render_gold(
            console=console,
            gold_amount=self.player.gold
        )
        render_functions.render_biome(
            console=console,
            biome_name=self.game_map.biome_str,
            map=self.game_map
        )
        render_functions.render_dungeon_level(
            console=console,
            dungeon_level=self.game_world.current_floor,
            map=self.game_map
        )


        render_functions.render_ui_buttons(
            console=console,
            hovered_button=self.hovered_inventory_button
        )

        render_functions.render_combat_stats(
            console=console,
            dodge_direction=getattr(self.player, "preferred_dodge_direction", "None"),
            attack_type=getattr(self.player, "current_attack_type", "None"),
            player=self.player,
        )



        render_functions.render_status_hover_panel(
            console=console,
            mouse_ui_x=self.mouse_ui_x,
            mouse_ui_y=self.mouse_ui_y,
            player=self.player,
        )

        if getattr(self, 'auto_move_path', None):
            self.cursor_hint = "walk"
            render_functions.render_names_at_mouse_location(
                console=console, x=1, y=42, engine=self
            )
            render_functions.render_context_hints(
                console=console, hints=self.context_hints
            )
            render_functions.render_minimap_box(
                console=console, engine=self
            )
            if self.debug:
                if not skip_debug:
                    render_functions.render_debug_overlay(console, getattr(self, "frame_fps", self.tick_rate), (self.player.x, self.player.y), self.__class__.__name__, len(self.game_map.entities), self)
            return

        tile = self.mouse_x, self.mouse_y
        # Only recompute cursor_hint when the mouse tile changes
        if getattr(self, '_last_cursor_tile', None) != (tile, self.mouse_ui_y):
            self._last_cursor_tile = (tile, self.mouse_ui_y)
            interactable = False
            fightable = False
            self.cursor_hint = None
            if self.mouse_ui_y > 38:
                interactable = False
                fightable = False
            elif self.game_map.in_bounds(*tile):
                if self.game_map.tiles[tile]['interactable']:
                    interactable = True
            if self.mouse_ui_y <= 38:
                # Get entities at mouse location
                for ent in self.game_map.entities:
                    if ent.x != self.mouse_x or ent.y != self.mouse_y:
                        continue
                    # Friendly NPCs are interactable, not fightable
                    if hasattr(ent, "ai") and getattr(ent.ai, "type", None) == "Friendly":
                        interactable = True
                        continue
                    # Check if interactable container
                    if hasattr(ent, "container") and ent.container:
                        interactable = True
                    # Check if campfire / bonfire — opens cooking UI
                    elif getattr(ent, "name", None) in ("Campfire", "Bonfire"):
                        interactable = True
                    # Check if enemy, has hp, and NOT player
                    elif hasattr(ent, "fighter") and ent.fighter and ent.fighter.hp > 0 and ent.fighter != self.player.fighter:
                        fightable = True
            if interactable:
                self.cursor_hint = "interact"
            elif fightable:
                self.cursor_hint = "fight"
        render_functions.render_names_at_mouse_location(
            console=console, x=1, y=42, engine=self  # MOUSE_LOCATION coordinates
            )

        render_functions.render_context_hints(
            console=console, hints=self.context_hints
        )

        render_functions.render_minimap_box(
            console=console, engine=self
        )

        if self.debug and not skip_debug:
            render_functions.render_debug_overlay(console, getattr(self, "frame_fps", self.tick_rate), (self.player.x, self.player.y), self.__class__.__name__, len(self.game_map.entities), self)

    def render(self, console: Console) -> None:
        self.render_game(console)
        self.render_ui(console)

    def trigger_damage_indicator(self):
        self.damage_indicator_timer = self.damage_indicator_duration
    
    def render_damage_indicator(self, console):
        return