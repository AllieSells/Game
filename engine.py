from __future__ import annotations

import lzma
import pickle
import trace
import traceback
from typing import TYPE_CHECKING

from tcod.console import Console
from tcod.map import compute_fov
from collections import deque
import random

from components import equipment
import exceptions
import game_map
from message_log import MessageLog
import render_functions
import sounds

if TYPE_CHECKING:
    from entity import Actor
    from game_map import GameMap, GameWorld

import time


class Engine:

    game_map: GameMap
    game_world: GameWorld

    def __init__(self, player: Actor):
        self.message_log = MessageLog()
        self.mouse_location = (0,0)
        self.player = player
        
        self.animation_queue = deque()
        self.animations_enabled = True
        self.debug = False
        
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
        
        try:
            for entity in list(self.game_map.entities):
                # Get Quest Givers on map
                if hasattr(entity, "type"):
                    if entity.type == "Quest Giver":
                        #print("Quest Giver found on map:", entity.name, "at", (entity.x, entity.y))
                        # Spawn a flicker or glow animation to highlight quest giver
                        if self.animations_enabled and random.random() < .01: 
                            try:
                                from animations import GivingQuestAnimation
                                # Pass the entity reference instead of static coordinates
                                self.animation_queue.append(GivingQuestAnimation(entity))
                            except Exception:
                                import traceback
                                traceback.print_exc()
                                pass
                

                # Periodically spawn fire animations for campfire and bonfire items on the map.
                # Get campfire and bonfire on map
                if entity.name in ("Campfire", "Bonfire"):
                    # Spawn flicker more frequently and independently from smoke.
                    if self.animations_enabled:
                        try:
                            from animations import FireFlicker, BonefireFlicker, FireSmoke

                            # Bonfire has more frequent and intense animations
                            flicker_chance = 0.35 if entity.name == "Bonfire" else 0.20
                            smoke_chance = 0.08 if entity.name == "Bonfire" else 0.01

                            # Flicker: frequent, short blips
                            if random.random() < flicker_chance and entity.name is "Campfire":
                                self.animation_queue.append(FireFlicker((entity.x, entity.y)))
                            elif random.random() < flicker_chance and entity.name is "Bonfire":
                                self.animation_queue.append(BonefireFlicker((entity.x, entity.y)))

                            # Smoke: rarer, longer lasting
                            if random.random() < smoke_chance:
                                self.animation_queue.append(FireSmoke((entity.x, entity.y)))
                        except Exception:
                            pass
        
            # Update ambient sounds based on player proximity
            import sounds

            sounds.update_all_ambient_sounds(self.player, self.game_map.entities, self.game_map)
        except Exception:
            import traceback
            traceback.print_exc()
            pass

        # Tick status effects on all actors (so effects update and expire)
        try:
            # game_map may not be set yet during early init
            for actor in list(getattr(self, "game_map", []).actors if hasattr(self, "game_map") else []):
                if not hasattr(actor, "effects") or not actor.effects:
                    continue
                for effect in list(actor.effects):
                    try:
                        expired = effect.tick(actor)
                        if expired:
                            try:
                                actor.effects.remove(effect)
                            except ValueError:
                                pass
                    except Exception:
                        # Don't let a broken effect crash the engine tick
                        pass
        except Exception:
            pass


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

        player = getattr(self, "player", None)
        gm = getattr(self, "game_map", None)
        if player is None or gm is None:
            return

        # Is the player in darkness? (case-insensitive name check)
        in_dark = any(getattr(e, "name", "").lower() == "darkness" for e in getattr(player, "effects", []))
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
        # check if player has a torch in grasped items
        has_torch = False
        try:
            if self.player.equipment:
                # Check grasped items for torches
                for item in self.player.equipment.grasped_items.values():
                    if hasattr(item, 'name') and item.name == "Torch":
                        has_torch = True
                        break
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
            # Deferred import to avoid circular imports at module load time
            from components.effect import Effect

            has_darkness = any(getattr(e, "name", "") == "Darkness" for e in self.player.effects)
            
            # Check current tile's light level
            current_light_level = 0.0
            if self.game_map.in_bounds(self.player.x, self.player.y):
                current_light_level = self.game_map.tiles["light_level"][self.player.x, self.player.y]
            
            # Consider tiles with only ambient light (≤ 0.1) as "dark" for darkness effects
            # This accounts for the dim view system that provides minimal visibility
            if current_light_level <= 0.1:
                # Player is in darkness (no real light sources): ensure they have the Darkness effect
                if not has_darkness:
                    try:
                        # duration=None => persistent until removed
                        self.player.add_effect(Effect(name="Darkness", duration=None, description="You are in darkness", type="Darkness"))
                    except Exception:
                        pass
            else:
                # Player has actual light sources: remove any Darkness effects
                if has_darkness:
                    for e in list(self.player.effects):
                        try:
                            if getattr(e, "type", "") == "Darkness":
                                self.player.remove_effect(e.type)
                        except Exception:
                            pass
        except Exception:
            # If anything goes wrong, don't break FOV update
            pass
            
    def render(self, console: Console) -> None:
        self.game_map.render(console)

        # Render damage indicator if active - render above all HUD elements
        if self.damage_indicator_timer > 0:
            self.render_damage_indicator(console)
            self.damage_indicator_timer -= 1

        # Draw UI border and background first, before all text elements
        render_functions.render_bottom_ui_border(
            console=console
        )

        self.message_log.render(console=console, x=21, y=43, width=58, height=3)

        render_functions.render_bar(
            console=console,
            current_value=self.player.fighter.hp,
            maximum_value=self.player.fighter.max_hp,
            total_width=20
        )
        render_functions.render_lucidity_bar(
            console=console,
            current_value=self.player.lucidity,
            maximum_value=self.player.max_lucidity,
            total_width=20
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

        render_functions.render_combat_stats(
            console=console,
            dodge_direction=getattr(self.player, "preferred_dodge_direction", "None"),
            attack_type=getattr(self.player, "current_attack_type", "None")
        )

        #print(self.player.current_attack_type)

        render_functions.render_effects(
            console=console,
            effects=self.player.effects
        )

        render_functions.render_player_level(
            console=console,
            current_value=self.player.level.current_xp,
            maximum_value=self.player.level.experience_to_next_level,
            total_value=self.player.level.current_level,
            total_width=20,

        )

        render_functions.render_names_at_mouse_location(
            console=console, x=1, y=42, engine=self
            )
        
        if self.debug:
            render_functions.render_debug_overlay(console, self.tick_rate, (self.player.x, self.player.y), self.__class__.__name__, len(self.game_map.entities))

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
