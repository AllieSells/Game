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

if TYPE_CHECKING:
    from entity import Actor
    from game_map import GameMap, GameWorld




class Engine:

    game_map: GameMap
    game_world: GameWorld

    def __init__(self, player: Actor):
        self.message_log = MessageLog()
        self.mouse_location = (0,0)
        self.player = player
        
        self.animation_queue = deque()
        self.animations_enabled = True

    def get_adjacent_tiles(self, x: int, y: int) -> list[tuple[int, int]]:
        # Returns adjacent (including diagonals) tiles
        adjacent = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                adjacent.append((x + dx, y + dy))

        return adjacent

    def tick(self, console: Console):
        # Don't call animation rendering here; rendering happens in GameMap.render().
        # Here we only clean up animations that were expired during the last render pass.
        expired = [anim for anim in list(self.animation_queue) if getattr(anim, "frames", 1) <= 0]
        for anim in expired:
            try:
                self.animation_queue.remove(anim)
            except ValueError:
                pass
        
        try:
            for entity in list(self.game_map.entities):
                # Get Quest Givers on map
                if hasattr(entity, "type"):
                    print(entity.type)
                    if entity.type == "Quest Giver":
                        #print("Quest Giver found on map:", entity.name, "at", (entity.x, entity.y))
                        # Spawn a flicker or glow animation to highlight quest giver
                        if self.animations_enabled and random.random() < .03: 
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
                            smoke_chance = 0.08 if entity.name == "Bonfire" else 0.03

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
                    self.message_log.add_message("You hear something moving in the dark...")
            except Exception:
                pass
        except Exception:
            self._dark_spawn_cooldown = 8
            return

        self._dark_spawn_cooldown = 40


    def update_fov(self) -> None:
        # check if player has a torch in either hand; be robust if slots are None
        try:
            weapon_name = (
                self.player.equipment.weapon.name if self.player.equipment and self.player.equipment.weapon else None
            )
        except Exception:
            weapon_name = None

        try:
            offhand_name = (
                self.player.equipment.offhand.name if self.player.equipment and self.player.equipment.offhand else None
            )
        except Exception:
            offhand_name = None

        # Determine if player is holding a torch
        has_torch = (weapon_name == "Torch" or offhand_name == "Torch")

        # Check if player's current tile is lit by any light source
        near_light_source = False
        try:
            px, py = self.player.x, self.player.y
            if self.game_map.in_bounds(px, py):
                near_light_source = self.game_map.tiles["lit"][px, py]
        except Exception:
            near_light_source = False



        # Torch increases FOV radius; campfires only affect Darkness (lighting), not FOV
        radius = 7 if has_torch else 2

        # If player in village, greatly increase FOV radius
        if self.game_map.type == "village":
            radius = 1000

        self.game_map.visible[:] = compute_fov(
            self.game_map.tiles["transparent"],
            (self.player.x, self.player.y),
            radius,
        )

        self.game_map.explored |= self.game_map.visible

        # Apply or remove the persistent Darkness effect depending on lighting
        try:
            # Deferred import to avoid circular imports at module load time
            from components.effect import Effect

            has_darkness = any(getattr(e, "name", "") == "Darkness" for e in self.player.effects)

            if not (has_torch or near_light_source):
                # Player is in darkness: ensure they have the Darkness effect
                if not has_darkness:
                    try:
                        # duration=None => persistent until removed
                        self.player.add_effect(Effect(name="Darkness", duration=None, description="You are in darkness"))
                    except Exception:
                        pass
            else:
                # Player is lit: remove any Darkness effects
                if has_darkness:
                    for e in list(self.player.effects):
                        try:
                            if getattr(e, "name", "") == "Darkness":
                                self.player.remove_effect(e)
                        except Exception:
                            pass
        except Exception:
            # If anything goes wrong, don't break FOV update
            pass
            
    def render(self, console: Console) -> None:
        self.game_map.render(console)

        self.message_log.render(console=console, x=21, y=43, width=39, height=4)

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
        render_functions.render_dungeon_level(
            console=console,
            dungeon_level=self.game_world.current_floor,
        )

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
            console=console, x=1, y=43, engine=self
            )
        
        render_functions.render_separator(
            console=console,
        )
        
        render_functions.render_equipment(
            console=console, x=61, y=43, engine=self
        )
