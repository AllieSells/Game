from __future__ import annotations

import random
from typing import List, Tuple, Optional, TYPE_CHECKING

import numpy as np
import tcod

from actions import Action, MeleeAction, BumpAction, MovementAction, WaitAction

import color

import tile_functions



if TYPE_CHECKING:
    from entity import Actor

class BaseAI(Action):

    def __init__(self, entity: "Actor"):
        super().__init__(entity)
        # Track doors that this AI has opened and should close
        self.opened_doors: List[Tuple[int, int]] = []
        # Track the entity's last position to detect when they've moved through a door
        self.last_position: Optional[Tuple[int, int]] = None
        self.type: str = "BaseAI"
        # Movement speed system: higher values = slower movement
        # 1 = normal speed (moves every turn), 2 = half speed (moves every 2 turns)
        self.movement_speed: int = 1
        self.movement_counter: int = 0

    def perform(self) -> None:
        raise NotImplementedError(
        )
    
    def should_move_this_turn(self) -> bool:
        """Check if this AI should move this turn based on movement speed."""
        self.movement_counter += 1
        if self.movement_counter >= self.movement_speed:
            self.movement_counter = 0
            return True
        return False
    
    def get_path_to(self, dest_x: int, dest_y: int) -> List[Tuple[int, int]]:
        
        # Create cost array where walkable tiles cost 1, non-walkable cost 0 (impassable)
        cost = np.array(self.entity.gamemap.tiles["walkable"], dtype=np.int8)
        
        # Make closed doors walkable for pathfinding purposes (AI will handle opening them)
        # This allows AI to plan paths through doors without making them expensive
        door_mask = self.entity.gamemap.tiles["name"] == "Door"
        cost[door_mask] = 1  # Treat doors as walkable for pathfinding

        for entity in self.entity.gamemap.entities:
            if entity.blocks_movement and cost[entity.x, entity.y]:
                cost[entity.x, entity.y] += 10

        graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
        pathfinder = tcod.path.Pathfinder(graph)

        pathfinder.add_root((self.entity.x, self.entity.y))

        path: List[List[int]] = pathfinder.path_to((dest_x, dest_y))[1:].tolist()

        return [(index[0], index[1]) for index in path]

    def is_door_tile(self, x: int, y: int) -> bool:
        """Check if the tile at (x, y) is a closed/open door."""
        try:
            if not self.entity.gamemap.in_bounds(x, y):
                return False
            tile_name = self.entity.gamemap.tiles["name"][x, y]
            return tile_name in ["Door", "Open Door"]
        except Exception:
            return False

    def can_open_door(self, x: int, y: int) -> bool:
        """Check if this AI can open a door at the given position."""
        try:
            # Check if it's actually a door
            if not self.is_door_tile(x, y):
                return False
            
            # Check if the entity is adjacent to the door
            dx = abs(self.entity.x - x)
            dy = abs(self.entity.y - y)
            is_adjacent = (dx <= 1 and dy <= 1 and (dx + dy) > 0)
            
            return is_adjacent
        except Exception:
            return False

    def toggle_door_at(self, x: int, y: int) -> bool:
        """Try to toggle a door at the given position. Returns True if successful."""
        try:
            if not self.can_open_door(x, y):
                return False
            
            # Check what type of door it is before toggling
            tile_name = self.entity.gamemap.tiles["name"][x, y]
            
            # Use the tile interaction system to toggle the door
            import tile_functions
            result = tile_functions.toggle_door(
                self.entity.gamemap.engine, self.entity, x, y
            )
            
            if result is not None:
                # If we opened a door, track it for later closing
                if tile_name == "Door":
                    self.opened_doors.append((x, y))
                # If we closed a door, remove it from tracking
                elif tile_name == "Open Door":
                    try:
                        self.opened_doors.remove((x, y))
                    except ValueError:
                        pass  # Door wasn't in our tracking list
                return True
            return False
                
        except Exception:
            return False

    def close_door_at(self, x: int, y: int) -> bool:
        """Try to close a door at the given position. Returns True if successful."""
        try:
            # Check if it's an open door
            if not self.entity.gamemap.in_bounds(x, y):
                return False
            
            tile_name = self.entity.gamemap.tiles["name"][x, y]
            if tile_name != "Open Door":
                return False
            
            # Check if there's an entity blocking the door
            blocking_entity = self.entity.gamemap.get_blocking_entity_at_location(x, y)
            if blocking_entity:
                return False  # Can't close if blocked
            
            # Use the tile interaction system to close the door
            try:
                import tile_functions
                result = tile_functions.close_door(
                    self.entity.gamemap.engine, self.entity, x, y
                )
                return result is not None
            except ImportError:
                # Fallback: directly change the tile
                import tile_types
                self.entity.gamemap.tiles[x, y] = tile_types.closed_door
                return True
                
        except Exception:
            return False

    def check_and_close_doors(self) -> bool:
        """Check if AI has moved away from any opened doors and close them. Returns True if any doors were closed."""
        if not self.opened_doors:
            return False
        
        current_pos = (self.entity.x, self.entity.y)
        doors_closed = False
        
        # Check each door we've opened
        for door_pos in list(self.opened_doors):
            door_x, door_y = door_pos
            
            # Calculate distance from entity to the door
            distance = max(abs(current_pos[0] - door_x), abs(current_pos[1] - door_y))
            
            # If we're more than 1 tile away from the door, close it
            if distance > 1:
                if self.close_door_at(door_x, door_y):
                    self.opened_doors.remove(door_pos)
                    doors_closed = True
                else:
                    # If we can't close it (blocked), remove from tracking anyway
                    self.opened_doors.remove(door_pos)
        
        return doors_closed

    def get_path_with_doors(self, dest_x: int, dest_y: int) -> List[Tuple[int, int]]:
        """Get path to destination, treating closed doors as walkable (AI can open them)."""
        try:
            # Create a modified walkable array that treats closed doors as walkable
            cost = np.array(self.entity.gamemap.tiles["walkable"], dtype=np.int8)
            
            # Mark closed doors as walkable (but with higher cost)
            door_mask = self.entity.gamemap.tiles["name"] == "Door"
            cost[door_mask] =  5  # Higher cost than normal movement but still walkable

            # Mark opened doors as normal walkable
            open_door_mask = self.entity.gamemap.tiles["name"] == "Open Door"
            cost[open_door_mask] = 1  # Normal walkable cost
            
            # Add entity blocking costs
            for entity in self.entity.gamemap.entities:
                if entity.blocks_movement and cost[entity.x, entity.y]:
                    cost[entity.x, entity.y] += 10

            graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
            pathfinder = tcod.path.Pathfinder(graph)

            pathfinder.add_root((self.entity.x, self.entity.y))

            path: List[List[int]] = pathfinder.path_to((dest_x, dest_y))[1:].tolist()

            return [(index[0], index[1]) for index in path]
        except Exception:
            # Fallback to regular pathfinding
            return self.get_path_to(dest_x, dest_y)

    def can_see_actor(self, actor: "Actor", radius: Optional[int] = None) -> bool:
        """Compute an FOV from this entity and return True if it can see `actor`.

        Uses tcod.map.compute_fov on the game map's transparency mask. If the
        actor or map is unavailable, returns False. The radius defaults to the
        entity's `sight_radius` attribute if present, otherwise 6.
        """
        try:
            gm = self.entity.gamemap
            if radius is None:
                radius = getattr(self.entity, "sight_radius", 6)

            fov = tcod.map.compute_fov(gm.tiles["transparent"], (self.entity.x, self.entity.y), radius)
            return bool(fov[actor.x, actor.y])
        except Exception:
            return False

class ConfusedEnemy(BaseAI):
    # Will stumble around for a number of turns, it will attack if it bumps into you

    def __init__(
            self, entity: Actor, previous_ai: Optional[BaseAI], turns_remaining: int
    ):
        super().__init__(entity)

        self.previous_ai = previous_ai
        self.turns_remaining = turns_remaining

    def perform(self) -> None:
        # Reverts ai to original state after course has run

        if self.turns_remaining <= 0:
            self.engine.message_log.add_message(
                f"The {self.entity.name} is no longer confused!"
            )
            self.entity.ai = self.previous_ai

        else:
            direction_X, direction_y = random.choice(
                [
                    (-1, -1),  # Northwest
                    (0, -1),  # North
                    (1, -1),  # Northeast
                    (-1, 0),  # West
                    (1, 0),  # East
                    (-1, 1),  # Southwest
                    (0, 1),  # South
                    (1, 1),  # Southeast
                ]
            )

            self.turns_remaining -= 1

            return BumpAction(self.entity, direction_X, direction_y).perform()

class HostileEnemy(BaseAI):
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.path: List[Tuple[int, int]] = []

    def perform(self) -> None:
        target = self.engine.player
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))
        # Use per-enemy FOV so enemies can spot the player even when the player
        # doesn't see them.
        if self.can_see_actor(target):
            if distance <= 1:
                return MeleeAction(self.entity, dx, dy).perform()
            
            self.path = self.get_path_to(target.x, target.y)
        
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            return MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
        
        return WaitAction(self.entity).perform()

class Friendly(BaseAI):
    # Friendly entity that paths around occasionally
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.path: List[Tuple[int, int]] = []
        self.wait_turns = random.randint(0, 20)  # Initial wait before first move
        self.type = "Friendly"
        # Set NPCs to move at half speed compared to player
        self.movement_speed = 2

    def perform(self) -> None:
        # Check if this AI should move this turn
        if not self.should_move_this_turn():
            return WaitAction(self.entity).perform()
        
        # Check and close any doors we've moved away from
        self.check_and_close_doors()
        
        if self.wait_turns > 0:
            self.wait_turns -= 1
            return WaitAction(self.entity).perform()
        
        if not self.path:
            # Pick a random location within 5 tiles to walk to
            dest_x = self.entity.x + random.randint(-5, 5)
            dest_y = self.entity.y + random.randint(-5, 5)

            # Ensure destination is in bounds and walkable (or a door that can be opened)
            if (0 <= dest_x < self.engine.game_map.width and
                0 <= dest_y < self.engine.game_map.height and
                (self.engine.game_map.tiles["walkable"][dest_x, dest_y] or 
                 self.is_door_tile(dest_x, dest_y)) and
                # Prefer to stay in radius of campfires, else will wander
                (not hasattr(self.engine.game_map, "items") or any(
                    item.name in ("Campfire", "Bonfire") and
                    (item.x - dest_x) ** 2 + (item.y - dest_y) ** 2 <= 10 * 10
                    for item in self.engine.game_map.items)
                )):
                self.path = self.get_path_with_doors(dest_x, dest_y)
            # If no campfire, just wander anywhere walkable
            elif (0 <= dest_x < self.engine.game_map.width and
                  0 <= dest_y < self.engine.game_map.height and
                  (self.engine.game_map.tiles["walkable"][dest_x, dest_y] or 
                   self.is_door_tile(dest_x, dest_y))):
                self.path = self.get_path_with_doors(dest_x, dest_y)
            else:

                # Invalid destination; wait instead
                self.wait_turns = random.randint(5,20)
                return WaitAction(self.entity).perform()
        
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            
            # Check if the destination is a closed door that needs to be opened
            if self.entity.gamemap.tiles["name"][dest_x, dest_y] == "Door":
                # Try to open the closed door
                if self.toggle_door_at(dest_x, dest_y):
                    # Door opened successfully, wait this turn and move next turn
                    return WaitAction(self.entity).perform()
                else:
                    # Couldn't open door, clear path and wait
                    self.path = []
                    self.wait_turns = random.randint(5, 20)
                    return WaitAction(self.entity).perform()
            
            # Store current position before moving
            self.last_position = (self.entity.x, self.entity.y)
            
            # Perform the movement
            result = MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
            
            return result
        
        # If no path found or path exhausted, wait a few turns before next move
        self.wait_turns = random.randint(5, 20)
        return WaitAction(self.entity).perform()


class DarkHostileEnemy(BaseAI):
    # Enemy that avoids light, only moves in darkness
    def __init__(self, entity: Actor):
        super().__init__(entity)
        self.path: List[Tuple[int, int]] = []
    
    def perform(self) -> None:
        target = self.engine.player
        dx = target.x - self.entity.x
        dy = target.y - self.entity.y
        distance = max(abs(dx), abs(dy))
        gm = self.engine.game_map
        if self.can_see_actor(target):
            # Build a walkable cost map similar to get_path_to but mark lit tiles as impassable
            try:
                import numpy as _np

                cost = _np.array(gm.tiles["walkable"], dtype=_np.int8)

                # mark lit tiles as non-walkable so pathfinder avoids them
                # Determine lit mask using same rules as GameMap.render
                lit_mask = _np.zeros((gm.width, gm.height), dtype=bool, order="F")

                # Check player-held torch
                try:
                    weapon_name = (
                        self.engine.player.equipment.weapon.name
                        if self.engine.player.equipment and self.engine.player.equipment.weapon
                        else None
                    )
                except Exception:
                    weapon_name = None
                try:
                    offhand_name = (
                        self.engine.player.equipment.offhand.name
                        if self.engine.player.equipment and self.engine.player.equipment.offhand
                        else None
                    )
                except Exception:
                    offhand_name = None

                has_torch = (weapon_name == "Torch" or offhand_name == "Torch")
                if has_torch:
                    rr = 7
                    px, py = self.engine.player.x, self.engine.player.y
                    xs = _np.arange(0, gm.width)
                    ys = _np.arange(0, gm.height)
                    dxs = xs[:, None] - px
                    dys = ys[None, :] - py
                    dist2 = dxs * dxs + dys * dys
                    lit_mask |= dist2 <= (rr * rr)

                # campfires and bonfires
                for item in getattr(gm, "items", []):
                    try:
                        if item.name == "Campfire" or item.name == "Bonfire":
                            cx, cy = item.x, item.y
                            xs = _np.arange(0, gm.width)
                            ys = _np.arange(0, gm.height)
                            dxs = xs[:, None] - cx
                            dys = ys[None, :] - cy
                            dist2 = dxs * dxs + dys * dys
                            if item.name == "Campfire":
                                lit_mask |= dist2 <= (3 * 3)  # radius 3 for campfires (matches game_map.py)
                            elif item.name == "Bonfire":
                                lit_mask |= dist2 <= (15 * 15)  # radius 15 for bonfires (matches game_map.py)
                    except Exception:
                        continue

                # treat lit tiles as non-walkable by setting cost to 0 where lit
                try:
                    cost[lit_mask] = 0
                except Exception:
                    # fallback: iterate
                    for lx, ly in zip(*_np.where(lit_mask)):
                        cost[lx, ly] = 0

                # increase cost for occupied tiles so pathfinder avoids them
                for entity in gm.entities:
                    try:
                        if entity.blocks_movement and cost[entity.x, entity.y]:
                            cost[entity.x, entity.y] += 10
                    except Exception:
                        continue

                graph = tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3)
                pathfinder = tcod.path.Pathfinder(graph)
                pathfinder.add_root((self.entity.x, self.entity.y))

                raw_path = pathfinder.path_to((target.x, target.y))[1:]
                # raw_path may be empty or contain coordinates in chained lists; coerce
                path = raw_path.tolist() if hasattr(raw_path, "tolist") else list(raw_path)
                self.path = [(p[0], p[1]) for p in path]
            except Exception:
                # If anything goes wrong, don't move into light; clear path so we wait
                self.path = []
            
            # attack if adjacent and not lit
            # ensure current tile is not lit
            try:
                current_lit = False
                if has_torch:
                    ddx = self.entity.x - self.engine.player.x
                    ddy = self.entity.y - self.engine.player.y
                    if ddx * ddx + ddy * ddy <= 7 * 7:
                        current_lit = True
                if not current_lit:
                    for item in getattr(gm, "items", []):
                        try:
                            if item.name == "Campfire":
                                cx = item.x - self.entity.x
                                cy = item.y - self.entity.y
                                if cx * cx + cy * cy <= 3 * 3:  # radius 3 for campfires
                                    current_lit = True
                                    break
                            elif item.name == "Bonfire":
                                bx = item.x - self.entity.x
                                by = item.y - self.entity.y
                                if bx * bx + by * by <= 15 * 15:  # radius 15 for bonfires
                                    current_lit = True
                                    break
                        except Exception:
                            continue
                # If the enemy is currently lit, it vanishes
                if current_lit:
                    try:
                        # optional message
                        if hasattr(self.engine, "message_log"):
                            self.engine.message_log.add_message(f"The {self.entity.name} dissolves in the light.", color.purple)
                    except Exception:
                        pass

                    try:
                        # Remove entity safely from map
                        if hasattr(gm, "entities") and self.entity in gm.entities:
                            try:
                                gm.entities.remove(self.entity)
                            except Exception:
                                try:
                                    gm.entities.discard(self.entity)
                                except Exception:
                                    pass
                        # clear ai to mark dead
                        try:
                            self.entity.ai = None
                        except Exception:
                            pass
                    except Exception:
                        pass

                    return

                if not current_lit and distance <= 1:
                    return MeleeAction(self.entity, dx, dy).perform()
            except Exception:
                pass
        
        if self.path:
            dest_x, dest_y = self.path.pop(0)
            return MovementAction(
                self.entity, dest_x - self.entity.x, dest_y - self.entity.y,
            ).perform()
        
        return WaitAction(self.entity).perform()
