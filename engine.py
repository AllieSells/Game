from __future__ import annotations

import lzma
import pickle
import trace
import traceback
from typing import TYPE_CHECKING, Optional
import os
from tcod.console import Console
from tcod.map import compute_fov
from collections import deque
import random

from components import equipment
import exceptions
import game_map
from liquid_system import LiquidType
from message_log import MessageLog
import render_functions
import sounds
from animations import TextPopupAnimation


if TYPE_CHECKING:
    from entity import Actor
    from game_map import GameMap, GameWorld

import time
from animations import FireFlicker, BonefireFlicker, FireSmoke



class Engine:

    game_map: Optional[GameMap]
    game_world: Optional[GameWorld]

    def __init__(self, player: Optional[Actor] = None):
        self.message_log = MessageLog()
        self.mouse_location = (0,0)
        self.player = player
        self.mouse_held = False
        
        self.animation_queue = deque()
        self.animations_enabled = True
        self.debug = False
        self.cursor_hint = None 
        self.hovered_inventory_button = None
        
        # Initialize turn manager for centralized turn processing
        self.turn_manager = None  # Will be set after import to avoid circular imports
        
        # Damage indicator system
        self.damage_indicator_timer = 0
        self.damage_indicator_duration = 20  # frames to show damage indicator
        
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
        self.dropped_stone_dummy_var = False

        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_ui_x = 0
        self.mouse_ui_y = 0

        # Auto-movement (pathfind-to-click)
        self.auto_move_path = []  # List of (x, y) tuples remaining in the queued path
        self._last_auto_move_time = 0.0
        self._pending_handler = None  # Handler change queued by auto-move (e.g. GameOver)

        # Persistent Simplex noise generator for torch/fire flicker.
        # Stored on the engine (not per-map) so the animation is continuous
        # across floor transitions and is preserved in save files.
        import tcod.noise as _tcod_noise
        self._noise_gen = _tcod_noise.Noise(
            dimensions=2, algorithm=_tcod_noise.Algorithm.PERLIN
        )
        # Scrolling time variable that advances 0.2 per frame, matching the
        # libtcod demo's fov_torchx.  Used to derive per-source wobble (dx, dy)
        # and intensity delta (di) for torch/fire flicker.
        self._torch_t: float = 0.0

    def get_camera_origin(self, view_width: int, view_height: int) -> tuple[int, int]:
        """Return the top-left world tile of the current viewport."""
        if not self.game_map or not self.player:
            return 0, 0

        max_x = max(0, self.game_map.width - view_width)
        max_y = max(0, self.game_map.height - view_height)
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
        world_x = origin_x + int(x)
        world_y = origin_y + int(y)
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
        import time
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
        if self.debug:
            print(f"[DEBUG] {message}")
        # If log file doesn't exist, create it and write header
        log_path = "logs/log.txt"
        if not os.path.exists(log_path):
            mkdir_path = os.path.dirname(log_path)
            if not os.path.exists(mkdir_path):
                os.makedirs(mkdir_path)

        else:
            with open(log_path, "a") as log_file:
                log_file.write(f" {time.ctime()}: Handler: {handler}, Event: {event}, Message: {message}\n")

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
                return existing
        effects.append(effect)
        return effect

    def tutorial_ticking(self, console: Console):
        """Special tick method used during the tutorial"""
        now = time.monotonic()
        _last = getattr(self, "_last_tick_time", None)

        if _last is None:
            # first tick: initialize storage
            self._last_tick_time = now
            self._tick_intervals = deque(maxlen=60)  # smooth over last N frames
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

        # Tutorial state management - only update when state changes
        current_tutorial_state = self._determine_tutorial_state()
        last_state = getattr(self, '_last_tutorial_state', None)
        
        if current_tutorial_state != last_state:
            self._update_tutorial_message(current_tutorial_state)
            self._last_tutorial_state = current_tutorial_state
            
        # Process animations - this was missing!
        # Don't call process_animations here as it needs console/game_map params
        # Instead just clean up expired animations
        expired = [anim for anim in list(self.animation_queue) if getattr(anim, "frames", 1) <= 0]
        for anim in expired:
            try:
                self.animation_queue.remove(anim)
            except ValueError:
                pass
    
    def _determine_tutorial_state(self):
        """Determine the current tutorial state based on player progress"""
        # No items in inventory - need to get items from chest
        
        if self.turn_manager.total_player_moves == 0:
            return "move"
        elif len(self.player.inventory.items) == 0:
            return "get_items"
        elif self.player.level.traits["arcana"]["level"] > 1:
            return "level_up_arcana"
        elif self.dropped_stone_dummy_var:
            return "sigil_stone_dropped"

        
        # Has items but none equipped - need to equip items
        elif len(self.player.inventory.items) > 0 and not any(item in self.player.equipment.equipped_items.values() for item in self.player.inventory.items):
            return "equip_items"
        
        elif any(entity.name == "Sigil Stone" for entity in self.game_map.entities):

            if self.dropped_stone_dummy_var == False:
                self.dropped_stone_dummy_var = True
                return "sigil_stone_dropped"
                
            else:
                return "sigil_stone_dropped"
            

            
                
        
        # Check for goblin corpse first - if defeated, move to next phase
        elif any(entity.name == "Corpse of Goblin" for entity in self.game_map.entities):
            return "goblin_defeated"
        
        # Has any item equipped - explain equipment usage and spawn goblin if needed
        elif any(item in self.player.equipment.equipped_items.values() for item in self.player.inventory.items):
            # Spawn goblin if not already present (alive or dead)
            if not any(entity.name == "Goblin" for entity in self.game_map.entities) and not any(entity.name == "Corpse of Goblin" for entity in self.game_map.entities):
                 # Spawn a goblin enemy to demonstrate combat after equipping
                import entity_factories
                goblin = entity_factories.goblin
                goblin.inventory.items.append(entity_factories.generate_sigil_stone())
                goblin.spawn(self.game_map, 42, 17)  # Spawn a bit away from player
            return "item_equipped"
        
        # Add more states here as needed
        # elif some_other_condition:
        #     return "next_state"
        
        return None
    
    def _update_tutorial_message(self, tutorial_state):
        """Update the tutorial message display based on current state"""
        # Only update if we don't already have this tutorial state showing
        if hasattr(self, '_last_tutorial_message_state') and self._last_tutorial_message_state == tutorial_state:
            return  # Already showing the correct message, don't interfere
        
        # Mark existing tutorial animation as expired
        if hasattr(self, '_current_tutorial_animation') and self._current_tutorial_animation:
            self._current_tutorial_animation.frames = 0
        
        # Tutorial messages for each state
        messages = {
            "move": """
>Arrow keys move you 
 cardinally. Numpad keys
 move ordinally. Try it!""",

            "get_items": """
>Interact with objects
 with ALT + Direction.
 Try interacting with the chest (C)
 and take the items inside.""",
            
            "equip_items": """
>Great job. You can
 interact with many
 objects. Try equipping
 those items using the 
 Equipment menu (E). """,
            
            "item_equipped": """
>Excellent! Try attacking
 this goblin (g) by moving
 into it, or using
 SHIFT + Direction.""",
            
            "goblin_defeated": """
>Great job! Inspect (S) the
 goblin corpse to see the
 loot it dropped. Interact with
 it like a chest! Use the drop (D)
 menu and drop the sigil stone. """,
            "sigil_stone_dropped": """
>Great. Sigil stones can be 
 used (SPACE) from your 
 inventory (TAB) to unlock
 spells and level magic.
 Pick up (G) the stone 
 and use it now!""",
            "level_up_arcana": """
>Check your levels with (F).
 Skills build from use. That
 is all from me! Use (ESC) to exit,
 and check the controls in settings
 if you need a refresh.""",

            
            # Add more tutorial messages here
            # "next_state": """Your next tutorial message here""",
        }
        
        # Add the appropriate tutorial animation and store reference
        if tutorial_state in messages:
            tutorial_animation = TextPopupAnimation(
                43, 21, 
                messages[tutorial_state],
                color=(255, 255, 0), 
                duration=99999
            )
            self.animation_queue.append(tutorial_animation)
            self._current_tutorial_animation = tutorial_animation
            self._last_tutorial_message_state = tutorial_state

                
    
    def tick(self, console: Console):


        # Calculate tick rate per second
        now = time.monotonic()
        _last = getattr(self, "_last_tick_time", None)

        if _last is None:
            # first tick: initialize storage
            self._last_tick_time = now
            self._tick_intervals = deque(maxlen=60)  # smooth over last N frames
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

        # Handle tutorial-specific ticking for tutorial maps
        if hasattr(self, 'game_map') and getattr(self.game_map, 'type', None) == "tutorial":
            self.tutorial_ticking(console)
            return  # Skip regular game ticking for tutorials
        
        # Generate water drop animations for random tiles 
        #try:
        #    if hasattr(self.game_map, "tiles") and "name" in self.game_map.tiles.dtype.names:
        #        if random.random() < 0.0 5:  # 5% chance each tick to try spawning drops
        #            for _ in range(2):  # Try to spawn a couple of drops each tick
        #               x = random.randint(0, self.game_map.width - 1)
        #               y = random.randint(0, self.game_map.height - 1)
        #               if (self.game_map.tiles["walkable"][x, y]
        #                       and self.game_map.visible[x, y]):
        #                   from animations import WaterDropAnimation
        #                    self.animation_queue.append(WaterDropAnimation((x, y)))
        #except Exception:
        #    traceback.print_exc()

        # Generate grass waves that sweep across the visible area
        try:
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


        # Don't call animation rendering here; rendering happens in GameMap.render().
        # Here we only clean up animations that were expired during the last render pass.
        expired = [anim for anim in list(self.animation_queue) if getattr(anim, "frames", 1) <= 0]
        for anim in expired:
            try:
                # Delete expired animations from queue
                self.animation_queue.remove(anim)
            except ValueError:
                pass

        # Body part coating system moved to turn_manager.py


        
        try:
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
                
                # Get liquid system - check for fire coatings on tiles
                for coating in self.game_map.liquid_system.coatings.values():
                    if coating.liquid_type == LiquidType.FIRE:
                        pos = coating.get_pos()
                        if not any(isinstance(a, FireFlicker) and a.position == pos for a in self.animation_queue):
                            self.animation_queue.append(FireFlicker(pos))
                        
                # Check entities for fire coatings on body parts
                if hasattr(entity, 'body_parts') and entity.body_parts:
                    # Check if this entity has fire coating on any body part
                    has_fire_coating = any(
                        part.coating == LiquidType.FIRE 
                        for part in entity.body_parts.body_parts.values()
                    )
                    
                    if has_fire_coating:
                        # Check if we already have an EntityFireFlicker animation for this entity
                        entity_has_fire_animation = any(
                            hasattr(anim, 'entity') and anim.entity == entity 
                            and type(anim).__name__ == 'EntityFireFlicker'
                            for anim in self.animation_queue
                        )
                        
                        if not entity_has_fire_animation:
                            from animations import EntityFireFlicker
                            self.animation_queue.append(EntityFireFlicker(entity))
                
                
                # Periodically spawn fire animations for campfire and bonfire items on the map.
                # Get campfire and bonfire on map
                

                if entity.name in ("Campfire", "Bonfire"):
                    # Spawn flicker more frequently and independently from smoke.
                    if self.animations_enabled:
                        try:
                            

                            # Flicker: always keep one running per position
                            pos = (entity.x, entity.y)
                            smoke_chance = 0.08 if entity.name == "Bonfire" else 0.01
                            if entity.name == "Campfire":
                                if not any(isinstance(a, FireFlicker) and a.position == pos for a in self.animation_queue):
                                    self.animation_queue.append(FireFlicker(pos))
                            elif entity.name == "Bonfire":
                                if not any(isinstance(a, BonefireFlicker) and a.position == pos for a in self.animation_queue):
                                    self.animation_queue.append(BonefireFlicker(pos))

                            # Smoke: rarer, longer lasting
                            if random.random() < smoke_chance:
                                self.animation_queue.append(FireSmoke((entity.x, entity.y)))
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
        
            # Update ambient sounds based on player proximity
            import sounds

            sounds.update_all_ambient_sounds(self.player, self.game_map.entities, self.game_map)
        except Exception:
            traceback.print_exc()
            pass

        # Auto-movement: advance one step along the queued path every 150 ms
        auto_path = getattr(self, 'auto_move_path', None)
        if auto_path and getattr(self, 'turn_manager', None):
            self.cursor_hint = "walk"
            import color as _color
            now_am = time.monotonic()
            if now_am - self._last_auto_move_time >= 0.05:
                # Cancel if an enemy is visible
                enemy_visible = any(
                    actor is not self.player and self.game_map.visible[actor.x, actor.y]
                    for actor in self.game_map.actors
                )
                if enemy_visible:
                    self.auto_move_path = []
                    self.cursor_hint = None
                    self.message_log.add_message("No longer pathing, spotted an enemy.", _color.yellow)
                else:
                    next_pos = auto_path.pop(0)
                    dx = next_pos[0] - self.player.x
                    dy = next_pos[1] - self.player.y
                    from actions import MovementAction
                    try:
                        self.turn_manager.process_pre_player_turn()
                        MovementAction(self.player, dx, dy).perform()
                        self._last_auto_move_time = now_am
                        # Clear cursor hint when path is exhausted
                        if not auto_path:
                            self.cursor_hint = None
                        result = self.turn_manager.process_player_turn_end()
                        if result is not None:
                            self.auto_move_path = []
                            self.cursor_hint = None
                            self._pending_handler = result
                    except exceptions.Impossible as exc:
                        self.auto_move_path = []
                        self.cursor_hint = None
                        self.message_log.add_message(exc.args[0], _color.impossible)
                        self.message_log.add_message(exc.args[0], _color.impossible)




    def process_animations(self):
        if not self.animation_queue:
            return
        
        for animation in list(self.animation_queue):
            animation.tick()
            if animation.frames <= 0:
                self.animation_queue.remove(animation)

    def save_as(self, filename: str) -> None:
        # save this engine instance as a compressed file
        save_data = lzma.compress(pickle.dumps(self))
        with open(filename, "wb") as f:
            f.write(save_data)
            # Write game savename 
            f.write(filename.encode('utf-8'))
    
    def handle_enemy_turns(self) -> None:
        """Legacy method - use turn_manager.process_player_turn_end() instead."""
        for entity in set(self.game_map.actors) - {self.player}:
            if entity.ai:
                try:
                    entity.ai.perform()
                except exceptions.Impossible:
                    pass # Ignore


    def _find_dark_spawn_pos(self, max_radius: int = 8, min_radius: int = 2):
        """Return a random (x,y) near the player that is walkable, empty and not visible.
        Returns None if none found.
        """
        import random

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
        import random
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
            
        # Find all visible grass tiles
        grass_tiles = []
        for x in range(self.game_map.width):
            for y in range(self.game_map.height):
                if (self.game_map.visible[x, y] and 
                    self.game_map.tiles["name"][x, y] == "Grass"):
                    grass_tiles.append((x, y))
        
        if not grass_tiles:
            return
            
        # Pick a random grass tile as the wave origin
        origin_x, origin_y = random.choice(grass_tiles)
        
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

    def render_ui(self, console: Console) -> None:
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
            if self.debug:
                render_functions.render_debug_overlay(console, self.tick_rate, (self.player.x, self.player.y), self.__class__.__name__, len(self.game_map.entities), self)
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
                    # Check if interactable
                    if hasattr(ent, "container") and ent.container and (
                        ent.x == self.mouse_x and ent.y == self.mouse_y
                    ):
                        interactable = True
                    # Check if enemy, has hp, and NOT player
                    if hasattr(ent, "fighter") and ent.fighter and ent.fighter.hp > 0 and ent.fighter != self.player.fighter and (
                        ent.x == self.mouse_x and ent.y == self.mouse_y
                    ):
                        fightable = True
            if interactable:
                self.cursor_hint = "interact"
            elif fightable:
                self.cursor_hint = "fight"
        render_functions.render_names_at_mouse_location(
            console=console, x=1, y=42, engine=self  # MOUSE_LOCATION coordinates
            )
        
        if self.debug:
            render_functions.render_debug_overlay(console, self.tick_rate, (self.player.x, self.player.y), self.__class__.__name__, len(self.game_map.entities), self)

    def render(self, console: Console) -> None:
        self.render_game(console)
        self.render_ui(console)

    def trigger_damage_indicator(self):
        """Trigger the damage indicator visual effect"""
        self.damage_indicator_timer = self.damage_indicator_duration
        # Debug: Add a message to see if this is being called
        #if hasattr(self, 'message_log'):
        #    self.message_log.add_message("Damage indicator triggered!", (255, 255, 0))  # Yellow debug message
    
    def render_damage_indicator(self, console):
        """Render red corners on screen edges when player takes damage"""
        # Calculate fade effect based on remaining timer
        fade_ratio = self.damage_indicator_timer / self.damage_indicator_duration
        red_intensity = int(255 * fade_ratio)
        red_color = (red_intensity, 0, 0)
        
        # Get console dimensions
        width = console.width
        height = console.height
        
        # Corner size
        corner_size = 8  # Made bigger to see better
        
        # Test: Just draw simple rectangles in all four corners to make sure it's working
        # Top-left corner (L facing inward)
        for x in range(corner_size):
            for y in range(corner_size):
                if x < 2 or y < 2:  # Thinner L shape
                    console.print(x, y, " ", bg=red_color)
        
        # Top-right corner (backwards L facing inward)
        for x in range(corner_size):
            for y in range(corner_size):
                if x >= corner_size - 2 or y < 2:  # Thinner backwards L shape
                    console.print(width - corner_size + x, y, " ", bg=red_color)
        
        # Bottom-left corner (upside-down L facing inward)
        for x in range(corner_size):
            for y in range(corner_size):
                if x < 2 or y >= corner_size - 2:  # Thinner upside-down L shape
                    console.print(x, height - corner_size + y, " ", bg=red_color)
        
        # Bottom-right corner (upside-down backwards L facing inward)
        for x in range(corner_size):
            for y in range(corner_size):
                if x >= corner_size - 2 or y >= corner_size - 2:  # Thinner upside-down backwards L shape
                    console.print(width - corner_size + x, height - corner_size + y, " ", bg=red_color)
