from __future__ import annotations
from enum import unique
from typing import Dict, Iterator, Tuple, List, TYPE_CHECKING
from webbrowser import get
from numpy import number
import tcod
import random

import engine
import entity_factories
from game_map import GameMap
import tile_types
from spawn_definitions import (
    max_items_by_floor,
    max_chests_by_floor,
    max_monsters_by_floor,
    max_flora_by_floor,
    item_chances,
    enemy_chances,
)

if TYPE_CHECKING:
    from engine import Engine
    from entity import Entity

def get_max_value_for_floor(
        max_value_by_floor: Dict[int, int], floor: int
) -> int:
    current_value = 0

    for floor_minimum, value in sorted(max_value_by_floor.items()):
        if floor_minimum > floor:
            break
        else:
            current_value = value

    return current_value

def get_entities_at_random(
        weighted_chances_by_floor: Dict[int, Dict[Entity, int]],
        number_of_entities: int,
        floor: int,
) -> List[Entity]:
    entity_weighted_chances = {}

    for key, values in sorted(weighted_chances_by_floor.items()):
        if key > floor:
            break
        else:
            for entity, weighted_chance in values.items():
                entity_weighted_chances[entity] = weighted_chance
    
    entities = list(entity_weighted_chances.keys())
    entity_weighted_chance_values = list(entity_weighted_chances.values())

    chosen_entities = random.choices(
        entities, weights = entity_weighted_chance_values, k=number_of_entities
    )

    return chosen_entities





class RectangularRoom:
    def __init__(self, x: int, y: int, width: int, height: int):
        self.x1 = x
        self.y1 = y
        self.x2 = x + width
        self.y2 = y + height
    
    @property
    def center(self) -> Tuple[int, int]:
        center_x = (self.x1 + self.x2) // 2
        center_y = (self.y1 + self.y2) // 2

        return (center_x, center_y)
    
    @property
    def inner(self) -> Tuple[slice, slice]:
        """Return the inner area of this room as a 2D array index."""
        return (slice(self.x1 + 1, self.x2), slice(self.y1 + 1, self.y2))
    
    def intersects(self, other: RectangularRoom) -> bool:
        """Return True if this room overlaps with another RectangularRoom."""
        return (
            self.x1 <= other.x2
            and self.x2 >= other.x1
            and self.y1 <= other.y2
            and self.y2 >= other.y1
        )
    
def place_entities(room: RectangularRoom, dungeon: GameMap, floor_number: int,) -> None:
    number_of_monsters = random.randint(
        0, get_max_value_for_floor(max_monsters_by_floor, floor_number)
    )
    number_of_items = random.randint(
        0, get_max_value_for_floor(max_items_by_floor, floor_number)
    )

    monsters: List[Entity] = get_entities_at_random(
        enemy_chances, number_of_monsters, floor_number
    )

    items: List[Entity] = get_entities_at_random(
        item_chances, number_of_items, floor_number
    )

    # Place chests based on floor
    for entity in range(random.randint(0, get_max_value_for_floor(max_chests_by_floor, floor_number))):
        chest = entity_factories.chest

        # Spawn chests in room, aligning to a wall if possible
        if random.random() < 0.5: # Align to horizontal wall
            x = random.randint(room.x1+1, room.x2-1)
            y = room.y1+1 if random.random() < 0.5 else room.y2-1
        else: # Align to vertical wall
            x = room.x1+1 if random.random() < 0.5 else room.x2-1
            y = random.randint(room.y1+1, room.y2-1)
        if not any(e.x == x and e.y == y for e in dungeon.entities):
            # Choose chest loot based on item weights from item dictionary
            print(get_max_value_for_floor(max_items_by_floor, floor_number))
            loot = get_entities_at_random(item_chances, random.randint(0, get_max_value_for_floor(max_items_by_floor, floor_number)), floor_number)
            chest = entity_factories.make_chest_with_loot(loot, capacity=6)
            chest.spawn(dungeon, x, y)

    # Place flora
    game_world = dungeon.engine.game_world
    for entity in range(random.randint(0, get_max_value_for_floor(max_flora_by_floor, floor_number))):
        fungus = game_world.fungi[random.randint(0, len(game_world.fungi)-1)]
        x = random.randint(room.x1+1, room.x2-1)
        y = random.randint(room.y1+1, room.y2-1)
        if not any(e.x == x and e.y == y for e in dungeon.entities):
            fungus.spawn(dungeon, x, y)

    for entity in monsters:
        x = random.randint(room.x1+1, room.x2-1)
        y= random.randint(room.y1+1, room.y2-1)

        if not any(entity.x == x and entity.y == y for entity in dungeon.entities):
            # Spawn mob with equipment automatically applied via spawn()
            entity.spawn(dungeon, x, y)

    # Place campfire using centralized logic
    place_campfires(dungeon, "dungeon_room", room=room)
def tunnel_between(
        start: Tuple[int, int], end: Tuple[int, int], doors: bool = True
) -> Iterator[Tuple[int, int]]:
    """Return an L-shaped tunnel between these two points."""
    x1, y1 = start
    x2, y2 = end

    if random.random() < 0.5:  # 50% chance
        # Move horizontally, then vertically.
        corner_x, corner_y = x2, y1
    else:
        # Move vertically, then horizontally.
        corner_x, corner_y = x1, y2

    # Generate the coordinates for this tunnel.
    for x, y in tcod.los.bresenham((x1, y1), (corner_x, corner_y)).tolist():
        if doors:
            yield x, y
            # TODO
    for x, y in tcod.los.bresenham((corner_x, corner_y), (x2, y2)).tolist():
        yield x, y

class Building:
    """Represents a square building in the village."""
    def __init__(self, x: int, y: int, size: int):
        self.x1 = x
        self.y1 = y
        self.x2 = x + size
        self.y2 = y + size
        self.size = size
    
    @property
    def center(self) -> Tuple[int, int]:
        center_x = (self.x1 + self.x2) // 2
        center_y = (self.y1 + self.y2) // 2
        return (center_x, center_y)
    
    @property
    def inner(self) -> Tuple[slice, slice]:
        """Return the inner area of this building as a 2D array index."""
        return (slice(self.x1 + 1, self.x2), slice(self.y1 + 1, self.y2))
    
    def intersects(self, other: Building) -> bool:
        """Return True if this building overlaps with another Building."""
        return (
            self.x1 <= other.x2
            and self.x2 >= other.x1
            and self.y1 <= other.y2
            and self.y2 >= other.y1
        )
    
    def distance_to_center(self, center_x: int, center_y: int) -> float:
        """Calculate distance from building center to town center."""
        bx, by = self.center
        return ((bx - center_x) ** 2 + (by - center_y) ** 2) ** 0.5

def place_campfires(game_map: GameMap, map_type: str, **kwargs) -> None:
    """Centralized campfire placement logic for different map types."""
    
    if map_type == "dungeon_room":
        # Random campfire in dungeon rooms (15% chance)
        room = kwargs.get("room")
        if room and random.random() < 0.15:
            x = random.randint(room.x1 + 1, room.x2 - 1)
            y = random.randint(room.y1 + 1, room.y2 - 1)
            if not any(e.x == x and e.y == y for e in game_map.entities):
                entity_factories.campfire.spawn(game_map, x, y)
    
    elif map_type == "dungeon_first_room":
        # Guaranteed campfire in first dungeon room
        room = kwargs.get("room")
        player_pos = kwargs.get("player_pos")
        if room and player_pos:
            cx, cy = player_pos
            camp_x, camp_y = cx, max(0, cy - 1)
            if not any(e.x == camp_x and e.y == camp_y for e in game_map.entities):
                entity_factories.campfire.spawn(game_map, camp_x, camp_y)
    
    
    elif map_type == "village_building":
        # Occasional campfire in village buildings (lower chance than dungeons)
        building = kwargs.get("building")
        if building and random.random() < 0.95:  # 95% chance for buildings
            print("Placing campfire in building")
            x = random.randint(building.x1 + 1, building.x2 - 1)
            y = random.randint(building.y1 + 1, building.y2 - 1)
            if not any(e.x == x and e.y == y for e in game_map.entities):
                entity_factories.campfire.spawn(game_map, x, y)

def place_village_entities(building: Building, village: GameMap, floor_number: int) -> None:
    """Place entities inside a village building."""
    # Buildings have fewer monsters than dungeon rooms
    number_of_items = random.randint(1, 2)     # 1-2 items
    


    items: List[Entity] = get_entities_at_random(
        item_chances, number_of_items, floor_number
    )

    # Place NPCs in each building
    number_of_npcs = random.randint(0, 2)  # 0-2 NPCs
    for _ in range(number_of_npcs):
        x = random.randint(building.x1 + 1, building.x2 - 1)
        y = random.randint(building.y1 + 1, building.y2 - 1)
        
        if not any(e.x == x and e.y == y for e in village.entities):
            # Create a unique copy of the villager with a new name
            import copy
            from components import names
            if random.random() < .20:
            
                
                unique_villager = copy.deepcopy(entity_factories.quest_giver)

                unique_villager.description = unique_villager.generate_villager()
                unique_villager.name = names.get_names("Human", gender = unique_villager.knowledge["gender"])
                unique_villager.knowledge["name"] = unique_villager.name
                unique_villager.unknown_name = f"{unique_villager.knowledge['age_group']} {unique_villager.knowledge['gendered_noun']}"
                unique_villager.knowledge["location"] = village.name
                unique_villager.knowledge["name"] = unique_villager.name
            else:
                unique_villager = copy.deepcopy(entity_factories.villager)
                
                unique_villager.description = unique_villager.generate_villager()
                unique_villager.name = names.get_names("Human", gender = unique_villager.knowledge["gender"])
                unique_villager.knowledge["name"] = unique_villager.name
                unique_villager.unknown_name = f"{unique_villager.knowledge['age_group']} {unique_villager.knowledge['gendered_noun']}"
                unique_villager.knowledge["location"] = village.name
                unique_villager.knowledge["name"] = unique_villager.name
            # Generate a new name for this villager
            
            unique_villager.spawn(village, x, y)


    
    # Place items
    for entity in items:
        x = random.randint(building.x1 + 1, building.x2 - 1)
        y = random.randint(building.y1 + 1, building.y2 - 1)
        
        if not any(e.x == x and e.y == y for e in village.entities):
            entity.spawn(village, x, y)


    
    # Maybe place a chest (lower chance than dungeons)
    if random.random() < 0.3:
        try:
            import copy as _copy
            loot = get_entities_at_random(item_chances, random.randint(1, 2), floor_number)
            chest = entity_factories.make_chest_with_loot(loot, capacity=4)
            
            # Place chest against a wall
            if random.random() < 0.5:  # Horizontal wall
                x = random.randint(building.x1 + 1, building.x2 - 1)
                y = building.y1 + 1 if random.random() < 0.5 else building.y2 - 1
            else:  # Vertical wall
                x = building.x1 + 1 if random.random() < 0.5 else building.x2 - 1
                y = random.randint(building.y1 + 1, building.y2 - 1)
            
            if not any(e.x == x and e.y == y for e in village.entities):
                chest.spawn(village, x, y)
        except Exception:
            pass


def generate_circle_based_grass(game_map: GameMap, map_width: int, map_height: int) -> None:
    """Generate natural grass distribution using overlapping circles with priority system."""
    # Track which tiles have been placed (first value never overwrites second)
    placed = [[False for _ in range(map_height)] for _ in range(map_width)]
    
    # Generate multiple circles for natural distribution - front to back priority
    num_circles = random.randint(12, 20)  # More circles for better coverage
    
    for circle_idx in range(num_circles):
        # Random center point for each circle
        circle_x = random.randint(-map_width // 4, map_width + map_width // 4)  # Allow circles to extend beyond map
        circle_y = random.randint(-map_height // 4, map_height + map_height // 4)
        
        # Random radius - varying sizes for natural distribution
        radius = random.randint(2,5)
        
        # Get a grass type for this entire circle
        
        # Fill circle area
        for x in range(max(0, circle_x - radius), min(map_width, circle_x + radius + 1)):
            for y in range(max(0, circle_y - radius), min(map_height, circle_y + radius + 1)):
                # Check if point is within circle bounds
                distance_sq = (x - circle_x) ** 2 + (y - circle_y) ** 2
                if distance_sq <= radius ** 2:
                    # Only place if not already placed (priority system: first never overwrites second)
                    if not placed[x][y]:
                        game_map.tiles[x, y] = tile_types.fill_random_grasses()
                        placed[x][y] = True
    
    # Fill any remaining unplaced tiles with default grass
    for x in range(map_width):
        for y in range(map_height):
            if not placed[x][y]:
                game_map.tiles[x, y] = tile_types.fill_random_grasses()
                placed[x][y] = True


def generate_overworld_chunk(
        map_width: int,
        map_height: int,
        engine: Engine,
) -> GameMap:
    """Generate an overworld chunk with natural grass distribution."""
    player = engine.player
    chunk = GameMap(engine, map_width, map_height, entities=[player], type="overworld", name="Overworld", sunlit=True)  # Sunlit for overworld
    
    # Use circle-based natural grass distribution
    generate_circle_based_grass(chunk, map_width, map_height)
    
    # Place player in center  
    player.place(map_width // 2, map_height // 2, chunk)
    
    return chunk
            



def generate_village(
        map_width: int,
        map_height: int,
        engine: Engine,
) -> GameMap:


    """Generate a village with a large open center and square buildings dotted around."""
    player = engine.player
    import components.names as names
    name = names.get_location_name("Village")
    village = GameMap(engine, map_width, map_height, entities=[player], type="dungeon", name=name)  # Use dungeon type for world borders
    
    # Create town center area (large open space in the middle)
    center_x = map_width // 2
    center_y = map_height // 2
    town_center_radius = min(map_width, map_height) // 4
    
    # Create the main village area (leave border walls)
    # The GameMap constructor already filled everything with walls and world borders
    village_border = 2  # 2-tile thick walls around the perimeter
    
    # Generate random floor tiles for each position
    for x in range(village_border, map_width - village_border):
        for y in range(village_border, map_height - village_border):
            village.tiles[x, y] = tile_types.random_floor_tile()
    
    buildings: List[Building] = []
    
    # Generate square buildings dotted around the town center
    # Ensure minimum 4 buildings, but allow for more randomness
    min_buildings = 4
    max_buildings = random.randint(6, 12)  # 6-12 buildings for more variety
    min_building_size = 3
    max_building_size = 7
    min_distance_from_center = town_center_radius + 2
    # Account for the village border walls when calculating max distance
    max_distance_from_center = min(map_width, map_height) // 2 - village_border - 3
    
    attempts = 0
    max_attempts = 500  # Increased attempts to ensure we get minimum buildings
    
    # First, ensure we place at least the minimum number of buildings
    while len(buildings) < max_buildings and attempts < max_attempts:
        attempts += 1
        
        # Random building size
        building_size = random.randint(min_building_size, max_building_size)
        
        # Try to place building at various distances from center
        angle = random.uniform(0, 2 * 3.14159)  # Random angle
        distance = random.randint(min_distance_from_center, max_distance_from_center)
        
        # Calculate position based on angle and distance
        building_x = int(center_x + distance * random.uniform(-1, 1))
        building_y = int(center_y + distance * random.uniform(-1, 1))
        
        # Ensure building fits within village walls (not on the border walls)
        if (building_x + building_size >= map_width - village_border - 1 or 
            building_y + building_size >= map_height - village_border - 1 or
            building_x < village_border + 1 or building_y < village_border + 1):
            continue
        
        new_building = Building(building_x, building_y, building_size)
        
        # Check distance from town center
        if new_building.distance_to_center(center_x, center_y) < min_distance_from_center:
            continue
        
        # Check if building intersects with existing buildings (with spacing)
        too_close = False
        for existing_building in buildings:
            # Add spacing between buildings
            expanded_building = Building(
                new_building.x1 - 2, new_building.y1 - 2, 
                new_building.size + 4
            )
            if expanded_building.intersects(existing_building):
                too_close = True
                break
        
        if too_close:
            continue
        
        # Create the building walls
        # Outer walls
        for x in range(new_building.x1, new_building.x2 + 1):
            village.tiles[x, new_building.y1] = tile_types.random_wall_tile()
            village.tiles[x, new_building.y2] = tile_types.random_wall_tile()
        for y in range(new_building.y1, new_building.y2 + 1):
            village.tiles[new_building.x1, y] = tile_types.random_wall_tile()
            village.tiles[new_building.x2, y] = tile_types.random_wall_tile()
        
        # Interior floor (already floor from initial fill, but ensure it)
        village.tiles[new_building.inner] = tile_types.wooden_floor
        
        # Add an entrance (opening) to each building facing the town center
        # Determine which wall is closest to town center
        bx, by = new_building.center
        if abs(bx - center_x) > abs(by - center_y):
            # Closer horizontally, put entrance on left/right wall
            if bx < center_x:  # Building is left of center, entrance on right wall
                entrance_x = new_building.x2
                entrance_y = random.randint(new_building.y1 + 1, new_building.y2 - 1)
            else:  # Building is right of center, entrance on left wall
                entrance_x = new_building.x1
                entrance_y = random.randint(new_building.y1 + 1, new_building.y2 - 1)
        else:
            # Closer vertically, put entrance on top/bottom wall
            if by < center_y:  # Building is above center, entrance on bottom wall
                entrance_x = random.randint(new_building.x1 + 1, new_building.x2 - 1)
                entrance_y = new_building.y2
            else:  # Building is below center, entrance on top wall
                entrance_x = random.randint(new_building.x1 + 1, new_building.x2 - 1)
                entrance_y = new_building.y1
        
        # Create the entrance (opening in the wall)
        village.tiles[entrance_x, entrance_y] = tile_types.closed_door


        buildings.append(new_building)
    
    # If we don't have enough buildings, try a more aggressive placement strategy
    if len(buildings) < min_buildings:
        # Try placing buildings with relaxed constraints
        extra_attempts = 0
        while len(buildings) < min_buildings and extra_attempts < 300:
            extra_attempts += 1
            
            # Use smaller buildings if needed
            building_size = random.randint(min_building_size, min_building_size + 2)
            
            # Try placing anywhere within the village area
            building_x = random.randint(village_border + 1, map_width - village_border - building_size - 1)
            building_y = random.randint(village_border + 1, map_height - village_border - building_size - 1)
            
            new_building = Building(building_x, building_y, building_size)
            
            # Relaxed spacing check (minimum 1 tile apart)
            too_close = False
            for existing_building in buildings:
                expanded_building = Building(
                    new_building.x1 - 1, new_building.y1 - 1, 
                    new_building.size + 2
                )
                if expanded_building.intersects(existing_building):
                    too_close = True
                    break
            
            # Also check distance from town center (allow closer if needed)
            min_dist_relaxed = max(2, town_center_radius // 2)
            if (not too_close and 
                new_building.distance_to_center(center_x, center_y) >= min_dist_relaxed):
                
                # Create building walls and door (same as before)
                for x in range(new_building.x1, new_building.x2 + 1):
                    village.tiles[x, new_building.y1] = tile_types.random_wall_tile()
                    village.tiles[x, new_building.y2] = tile_types.random_wall_tile()
                for y in range(new_building.y1, new_building.y2 + 1):
                    village.tiles[new_building.x1, y] = tile_types.random_wall_tile()
                    village.tiles[new_building.x2, y] = tile_types.random_wall_tile()
                
                village.tiles[new_building.inner] = tile_types.floor
                
                # Add entrance for fallback buildings too
                bx, by = new_building.center
                if abs(bx - center_x) > abs(by - center_y):
                    # Closer horizontally, put entrance on left/right wall
                    if bx < center_x:  # Building is left of center, entrance on right wall
                        entrance_x = new_building.x2
                        entrance_y = random.randint(new_building.y1 + 1, new_building.y2 - 1)
                    else:  # Building is right of center, entrance on left wall
                        entrance_x = new_building.x1
                        entrance_y = random.randint(new_building.y1 + 1, new_building.y2 - 1)
                else:
                    # Closer vertically, put entrance on top/bottom wall
                    if by < center_y:  # Building is above center, entrance on bottom wall
                        entrance_x = random.randint(new_building.x1 + 1, new_building.x2 - 1)
                        entrance_y = new_building.y2
                    else:  # Building is below center, entrance on top wall
                        entrance_x = random.randint(new_building.x1 + 1, new_building.x2 - 1)
                        entrance_y = new_building.y1
                
                # Create the entrance (gap in the wall)
                village.tiles[entrance_x, entrance_y] = tile_types.floor
                
                buildings.append(new_building)
        
    # Place player in the town center
    player.place(center_x, center_y, village)
    

    

    


    # Add down stairs in a random building or at edge of town square
    if buildings:
        stair_building = random.choice(buildings)
        stair_x, stair_y = stair_building.center
        village.tiles[stair_x, stair_y] = tile_types.down_stairs
        village.downstairs_location = (stair_x, stair_y)
    else:
        # Fallback: place stairs at edge of town center
        village.tiles[center_x + town_center_radius, center_y] = tile_types.down_stairs
        village.downstairs_location = (center_x + town_center_radius, center_y)

    # Place entities in buildings
    for building in buildings:
        #place_village_entities(building, village, engine.game_world.current_floor)
        # Possibly place campfires in buildings
        place_campfires(village, "village_building", building=building)
        place_village_entities(building, village, engine.game_world.current_floor)
    # Place central bonfire just above player if possible
    center_pos = (center_x, center_y - 1)
    if center_pos:
        center_x, center_y = center_pos
        camp_x, camp_y = center_x, center_y - 1
        if not any(e.x == camp_x and e.y == camp_y for e in village.entities):
            entity_factories.bonfire.spawn(village, camp_x, camp_y)
    
    # Post-processing: Remove isolated walls that have no floors touching them
    remove_isolated_walls(village)
    
    # Apply wall merging system to create connected wall appearances
    apply_wall_merging(village)
    
    return village

def remove_isolated_walls(dungeon: GameMap) -> None:
    """Remove walls that have no floor tiles touching them in a 3x3 grid."""
    walls_to_remove = []
    
    for x in range(dungeon.width):
        for y in range(dungeon.height):
            # Check if this tile is a wall
            if not dungeon.tiles[x, y]["walkable"] and not dungeon.tiles[x, y]["interactable"]:
                # Check 3x3 grid around this wall tile
                has_adjacent_floor = False
                
                for dx in range(-1, 2):  # -1, 0, 1
                    for dy in range(-1, 2):  # -1, 0, 1
                        if dx == 0 and dy == 0:  # Skip the center tile (the wall itself)
                            continue
                            
                        check_x = x + dx
                        check_y = y + dy
                        
                        # Check if coordinates are in bounds
                        if 0 <= check_x < dungeon.width and 0 <= check_y < dungeon.height:
                            # Check if this neighboring tile is a floor (walkable)
                            if dungeon.tiles[check_x, check_y]["walkable"]:
                                has_adjacent_floor = True
                                break
                        else:
                            # Out of bounds counts as "floor" for border walls
                            has_adjacent_floor = True
                            break
                    
                    if has_adjacent_floor:
                        break
                
                # If no floor tiles are adjacent, mark this wall for removal
                if not has_adjacent_floor:
                    walls_to_remove.append((x, y))
    
    # Replace isolated walls with floor tiles
    for x, y in walls_to_remove:
        dungeon.tiles[x, y] = tile_types.random_floor_tile()

def get_wall_connections(dungeon: GameMap, x: int, y: int) -> Dict[str, bool]:
    """Check which directions have wall connections in a 3x3 grid around the position."""
    connections = {
        'north': False,
        'south': False, 
        'east': False,
        'west': False,
        'northeast': False,
        'northwest': False,
        'southeast': False,
        'southwest': False
    }
    
    # Direction mappings
    directions = {
        'north': (0, -1),
        'south': (0, 1),
        'east': (1, 0), 
        'west': (-1, 0),
        'northeast': (1, -1),
        'northwest': (-1, -1),
        'southeast': (1, 1),
        'southwest': (-1, 1)
    }
    
    for direction, (dx, dy) in directions.items():
        check_x = x + dx
        check_y = y + dy
        
        # Check if coordinates are in bounds
        if 0 <= check_x < dungeon.width and 0 <= check_y < dungeon.height:
            # Check if this neighboring tile is a wall or door, but not a world border
            tile = dungeon.tiles[check_x, check_y]
            is_wall = not tile["walkable"] and not tile["interactable"]
            is_door = not tile["walkable"] and tile["interactable"]
            is_world_border = tile["name"] == "World Border"
            
            # Only connect to walls and doors, not world borders
            if (is_wall or is_door) and not is_world_border:
                connections[direction] = True
        # Note: Out of bounds is NOT considered a wall connection
        # Only actual walls and doors within the map count as connections
    
    return connections

def determine_wall_tile(connections: Dict[str, bool]):
    """Determine the appropriate wall tile based on connection pattern."""
    # Extract main directions for easier checking
    n = connections['north']
    s = connections['south']
    e = connections['east']
    w = connections['west']
    ne = connections['northeast']
    nw = connections['northwest']
    se = connections['southeast']
    sw = connections['southwest']

    if n and s and e and w and nw and sw and not ne and not se:
        return tile_types.get_wall_top_left()
    
    # Double wall reduction - vertical
    if n and s and e and w:
        return tile_types.get_wall_cross()
    
    if n and nw and w and s and sw:
        # Return vertical
        return tile_types.get_wall_vertical()
    if n and ne and e and s and se:
        # Return vertical
        return tile_types.get_wall_vertical()
    
    # Double wall reduction - horizontal
    if e and se and s and w and sw:
        # Return horizontal
        return tile_types.get_wall_horizontal()
    if w and nw and n and e and ne:
        # Return horizontal
        return tile_types.get_wall_horizontal()
    

    
    
    
    
    # T-junctions (3 directions)
    if n and s and w and not e:  # T facing right (╣) - connects up, down, left
        return tile_types.get_wall_t_right()
    if n and s and e and not w:  # T facing left (╠) - connects up, down, right
        return tile_types.get_wall_t_left()
    if e and w and s and not n:  # T facing up (╦) - connects left, right, down
        return tile_types.get_wall_t_up()
    if e and w and n and not s:  # T facing down (╩) - connects left, right, up
        return tile_types.get_wall_t_down()
    
    # Corners (2 perpendicular directions)
    if n and e and not s and not w:  # Top-left corner
        return tile_types.get_wall_top_left()
    if n and w and not s and not e:  # Top-right corner
        return tile_types.get_wall_top_right()
    if s and e and not n and not w:  # Bottom-left corner
        return tile_types.get_wall_bottom_left()
    if s and w and not n and not e:  # Bottom-right corner
        return tile_types.get_wall_bottom_right()
    
    # Straight lines (2 opposite directions or single direction)
    if (n and s) or (n and not s and not e and not w) or (s and not n and not e and not w):
        return tile_types.get_wall_vertical()
    if (e and w) or (e and not w and not n and not s) or (w and not e and not n and not s):
        return tile_types.get_wall_horizontal()
    
    # Fallback to basic wall for complex or unhandled patterns
    return tile_types.wall

def apply_wall_merging(dungeon: GameMap) -> None:
    """Apply wall merging system to all wall tiles in the dungeon."""
    walls_to_update = []
    
    # First pass: identify all wall tiles and their appropriate replacements
    for x in range(dungeon.width):
        for y in range(dungeon.height):
            # Check if this tile is a wall, but not a world border
            tile = dungeon.tiles[x, y]
            is_wall = not tile["walkable"] and not tile["interactable"]
            is_world_border = tile["name"] == "World Border"
            
            if is_wall and not is_world_border:
                # Get wall connections in 3x3 grid
                connections = get_wall_connections(dungeon, x, y)
                
                # Determine appropriate wall tile
                new_wall_tile = determine_wall_tile(connections)
                
                # Store the update for later application
                walls_to_update.append((x, y, new_wall_tile))
    
    # Second pass: apply all updates
    for x, y, new_tile in walls_to_update:
        dungeon.tiles[x, y] = new_tile



def generate_dungeon(
        max_rooms: int,
        room_min_size: int,
        room_max_size: int,
        map_width: int,
        map_height: int,
        engine: Engine,
) -> GameMap:
    # Generates new map
    player = engine.player
    dungeon = GameMap(engine, map_width, map_height, entities=[player], type="dungeon", name="Dungeon")

    rooms: List[RectangularRoom] = []

    center_of_last_room = (0, 0)


    for r in range(max_rooms):
        room_width = random.randint(room_min_size, room_max_size)
        room_height = random.randint(room_min_size, room_max_size)

        # Keep rooms away from world borders - ensure at least 2 tiles buffer
        # This prevents room walls from being adjacent to world borders
        min_x = 2
        max_x = dungeon.width - room_width - 3
        min_y = 2  
        max_y = dungeon.height - room_height - 3
        
        # Make sure we have valid bounds for room placement
        if max_x <= min_x or max_y <= min_y:
            continue
            
        x = random.randint(min_x, max_x)
        y = random.randint(min_y, max_y)

        new_room = RectangularRoom(x, y, room_width, room_height)

        if any(new_room.intersects(other_room) for other_room in rooms):
            continue

        if len(rooms) == 0:
            # First room, where player starts
            player.place(*new_room.center, dungeon)
            # Guaranteed campfire in first room
            place_campfires(dungeon, "dungeon_first_room", room=new_room, player_pos=new_room.center)
            # Spawn a chest on first floor only
            if engine.game_world.current_floor == 1:
                # Build a small loot list: health potion + torch (deepcopy to avoid shared parents)
                import copy as _copy
                loot = [
                    _copy.deepcopy(entity_factories.health_potion),
                    _copy.deepcopy(entity_factories.torch),
                    _copy.deepcopy(entity_factories.dagger),
                    _copy.deepcopy(entity_factories.generate_leather_armor()),
                    _copy.deepcopy(entity_factories.leather_cap),
                    _copy.deepcopy(entity_factories.bow),
                    _copy.deepcopy(entity_factories.arrow),
                    _copy.deepcopy(entity_factories.arrow),
                    _copy.deepcopy(entity_factories.arrow),
                    _copy.deepcopy(entity_factories.arrow)
                ]
                test_chest = entity_factories.make_chest_with_loot(loot, capacity=10)
                cx, cy = new_room.center
                chest_x, chest_y = min(dungeon.width - 1, cx + 1), cy
                # Only place if empty
                if not any(e.x == chest_x and e.y == chest_y for e in dungeon.entities):
                    test_chest.place(chest_x, chest_y, dungeon)
        else:
            for x, y in tunnel_between(rooms[-1].center, new_room.center):
                dungeon.tiles[x,y] = tile_types.random_floor_tile()

                # Place doors at the entrances of the new room
                if (x == new_room.x1 or x == new_room.x2) and (y >= new_room.y1 and y <= new_room.y2):
                    dungeon.tiles[x,y] = tile_types.closed_door
                # Place doors at the exits of the previous room
                if (x == rooms[-1].x1 or x == rooms[-1].x2) and (y >= rooms[-1].y1 and y <= rooms[-1].y2):
                    dungeon.tiles[x,y] = tile_types.closed_door
                


            center_of_last_room = new_room.center

        # Carve out the room floor with random tiles for each position
        for x in range(new_room.x1 + 1, new_room.x2):
            for y in range(new_room.y1 + 1, new_room.y2):
                dungeon.tiles[x, y] = tile_types.random_floor_tile()



        
        place_entities(new_room, dungeon, engine.game_world.current_floor)

        dungeon.tiles[center_of_last_room] = tile_types.down_stairs
        dungeon.downstairs_location = center_of_last_room

        rooms.append(new_room)

    # Post-processing: Remove isolated walls that have no floors touching them
    remove_isolated_walls(dungeon)
    
    # Apply wall merging system to create connected wall appearances
    apply_wall_merging(dungeon)

    return dungeon
