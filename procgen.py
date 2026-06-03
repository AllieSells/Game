from __future__ import annotations
from typing import Dict, Iterator, Tuple, List, TYPE_CHECKING
import copy
import tcod
import random

import sprite_manager
import entity_factories
from game_map import GameMap
from typing import Optional
import numpy as np
import tile_types
from enemy_spawning import get_enemies_for_floor


# Spawn configuration data
max_items_by_floor = {1: 2, 4: 2}
max_chests_per_room_by_floor = {1: 1, 3: 3}
chest_spawn_chance_per_room_by_floor = {1: 0.60, 3: 0.80}
max_flora_by_floor = {1: 3, 4: 5}

# Tile names that should never have anything spawned on them.
_NO_SPAWN_NAMES = {
    "Water", "Foliage", "Mossy Floor",
    "<purple>Down Stairs</purple>", "<purple>Up Stairs</purple>",
}

def _spawnable(dungeon: GameMap, x: int, y: int) -> bool:
    """Return True only if (x, y) is a plain walkable tile with no entity and
    no water-edge animation overlay, and not a special tile like stairs/foliage."""
    tile = dungeon.tiles[x, y]
    if not tile["walkable"]:
        return False
    if str(tile["name"]) in _NO_SPAWN_NAMES:
        return False
    # Exclude water-edge floor tiles that have animated bite overlays.
    dw_anim = getattr(dungeon, "dungeon_water_anim", None)
    if dw_anim and (x, y) in dw_anim:
        return False
    if any(e.x == x and e.y == y for e in dungeon.entities):
        return False
    return True

# Item spawn chances - uses callable factories for dynamic generation
item_chances = {
    0: {
        entity_factories.lesser_health_potion: 35,
        entity_factories.lightning_scroll: 25,
        entity_factories.shortsword: 10,
    },
    2: {
        entity_factories.confusion_scroll: 10,
    },
    4: {
        entity_factories.lightning_scroll: 25
    },
    6: {
        entity_factories.fireball_scroll: 25,
    },
}

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

def get_chance_for_floor(
        chance_by_floor: Dict[int, float], floor: int
) -> float:
    current_value = 0.0

    for floor_minimum, value in sorted(chance_by_floor.items()):
        if floor_minimum > floor:
            break
        current_value = float(value)

    return max(0.0, min(1.0, current_value))

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
    
    # If entity is callable (factory), call it to get instance; otherwise deepcopy
    result = []
    for entity in chosen_entities:
        if callable(entity):
            result.append(entity())
        else:
            result.append(copy.deepcopy(entity))
    
    return result


class CavernRoom:
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


    def intersects(self, other: CavernRoom) -> bool:
        """Return True if this room overlaps with another CavernRoom."""
        return (
            self.x1 <= other.x2
            and self.x2 >= other.x1
            and self.y1 <= other.y2
            and self.y2 >= other.y1
        )
    




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
    
def _find_valid_stair_tile_in_room(dungeon: GameMap, room: RectangularRoom, avoid_positions: set = None) -> Optional[Tuple[int, int]]:
    """Find a valid tile for stair placement within a room.
    
    A valid tile must be:
    - Inside the room (not on walls)
    - Walkable floor
    - Not water, foliage, or mossy floor
    - Not occupied by an entity
    - At least 2 tiles from room edges (to avoid water edge composition issues)
    """
    if avoid_positions is None:
        avoid_positions = set()
    
    candidates = []
    # Search inner area of room, staying away from edges
    for x in range(room.x1 + 2, max(room.x1 + 3, room.x2 - 1)):
        for y in range(room.y1 + 2, max(room.y1 + 3, room.y2 - 1)):
            if (x, y) in avoid_positions:
                continue
            
            tile = dungeon.tiles[x, y]
            if not tile["walkable"]:
                continue
            
            tile_name = str(tile["name"])
            if tile_name in {"Water", "Foliage", "Mossy Floor", "<purple>Down Stairs</purple>", "<purple>Up Stairs</purple>"}:
                continue
            
            # Check for entities
            if any(e.x == x and e.y == y for e in dungeon.entities):
                continue
            
            candidates.append((x, y))
    
    if candidates:
        # Return a random candidate to avoid predictable placement
        return random.choice(candidates)
    
    return None

def place_entities(room: RectangularRoom, dungeon: GameMap, floor_number: int, biome: str = "any") -> None:
    # Don't re-seed here as it breaks dungeon generation flow
    # The main generation seed is set at the start of generate_dungeon
    
    # Use budget-based enemy spawning system (count determined by budget)
    monsters, traps = get_enemies_for_floor(floor_number, biome=biome)
    
    number_of_items = random.randint(
        0, get_max_value_for_floor(max_items_by_floor, floor_number)
    )



    # Place chests based on floor: separate spawn chance from per-room cap.
    chest_max_per_room = get_max_value_for_floor(max_chests_per_room_by_floor, floor_number)
    chest_spawn_chance = get_chance_for_floor(chest_spawn_chance_per_room_by_floor, floor_number)
    number_of_chests = random.randint(1, chest_max_per_room) if chest_max_per_room > 0 and random.random() < chest_spawn_chance else 0
    for entity in range(number_of_chests):
        # Spawn chests in room, aligning to a wall if possible; retry up to 10 times.
        for _ in range(10):
            if random.random() < 0.5:
                x = random.randint(room.x1+1, room.x2-1)
                y = room.y1+1 if random.random() < 0.5 else room.y2-1
            else:
                x = room.x1+1 if random.random() < 0.5 else room.x2-1
                y = random.randint(room.y1+1, room.y2-1)
            if _spawnable(dungeon, x, y):
                import loot_tables
                chest_tier = "basic" if floor_number <= 3 else "advanced"
                loot = loot_tables.generate_tiered_chest_loot(chest_tier)
                chest = entity_factories.make_chest_with_loot(loot, capacity=6)
                chest.spawn(dungeon, x, y)
                break

    # Place flora
    game_world = dungeon.engine.game_world
    for entity in range(random.randint(0, get_max_value_for_floor(max_flora_by_floor, floor_number))):
        fungus = game_world.fungi[random.randint(0, len(game_world.fungi)-1)]
        for _ in range(10):
            x = random.randint(room.x1+1, room.x2-1)
            y = random.randint(room.y1+1, room.y2-1)
            if _spawnable(dungeon, x, y):
                fungus.spawn(dungeon, x, y)
                break

    for entity in monsters:
        for _ in range(10):
            x = random.randint(room.x1+1, room.x2-1)
            y = random.randint(room.y1+1, room.y2-1)
            if _spawnable(dungeon, x, y):
                entity.spawn(dungeon, x, y)
                break

    for entity in traps:
        for _ in range(10):
            x = random.randint(room.x1+1, room.x2-1)
            y = random.randint(room.y1+1, room.y2-1)
            if _spawnable(dungeon, x, y):
                entity.spawn(dungeon, x, y)
                break

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

            x = random.randint(building.x1 + 1, building.x2 - 1)
            y = random.randint(building.y1 + 1, building.y2 - 1)
            if not any(e.x == x and e.y == y for e in game_map.entities):
                entity_factories.campfire.spawn(game_map, x, y)

def place_village_entities(building: Building, village: GameMap, floor_number: int) -> None:
    """Place entities inside a village building."""
    # Don't re-seed here to avoid breaking village generation flow
    
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
            import loot_tables
            loot = loot_tables.generate_tiered_chest_loot("basic")
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
    # Use existing random state - no need to re-seed here
    
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
    
    # Don't re-seed here - let it use the initial seed from setup_game.py
    
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
                
                village.tiles[new_building.inner] = tile_types.random_floor_tile()
                
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
                village.tiles[entrance_x, entrance_y] = tile_types.random_floor_tile()
                
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

def ensure_room_walls(dungeon: GameMap, rooms: list) -> None:
    for room in rooms:
        for x in range(room.x1 - 1, room.x2 + 2):
            for y in range(room.y1 - 1, room.y2 + 2):
                # Check if this tile is on the border of the room
                if (x == room.x1 - 1 or x == room.x2 + 1 or y == room.y1 - 1 or y == room.y2 + 1):
                    # Check if in bounds
                    if dungeon.in_bounds(x,y):
                        # If it's currently a floor, 40% chance to turn it into a wall
                        if not dungeon.tiles[x, y]["walkable"] and not dungeon.tiles[x, y]["interactable"]:
                            if random.random() < 0.6:
                                dungeon.tiles[x, y] = tile_types.random_wall_tile()


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

def determine_wall_tile(connections: Dict[str, bool], tile_type: Optional[str] = None):
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
        return tile_types.get_wall_top_left(tile_type)
    
    # Double wall reduction - vertical
    if n and s and e and w:
        return tile_types.get_wall_cross(tile_type)
    
    if n and nw and w and s and sw:
        # Return vertical
        return tile_types.get_wall_vertical(tile_type)
    if n and ne and e and s and se:
        # Return vertical
        return tile_types.get_wall_vertical(tile_type)
    
    # Double wall reduction - horizontal
    if e and se and s and w and sw:
        # Return horizontal
        return tile_types.get_wall_horizontal(tile_type)
    if w and nw and n and e and ne:
        # Return horizontal
        return tile_types.get_wall_horizontal(tile_type)
    # T-junctions (3 directions)
    if n and s and w and not e:  # T facing right (╣) - connects up, down, left
        return tile_types.get_wall_t_right(tile_type)
    if n and s and e and not w:  # T facing left (╠) - connects up, down, right
        return tile_types.get_wall_t_left(tile_type)
    if e and w and s and not n:  # T facing up (╦) - connects left, right, down
        return tile_types.get_wall_t_up(tile_type)
    if e and w and n and not s:  # T facing down (╩) - connects left, right, up
        return tile_types.get_wall_t_down(tile_type)
    
    # Corners (2 perpendicular directions)
    if n and e and not s and not w:  # Top-left corner
        return tile_types.get_wall_top_left(tile_type)
    if n and w and not s and not e:  # Top-right corner
        return tile_types.get_wall_top_right(tile_type)
    if s and e and not n and not w:  # Bottom-left corner
        return tile_types.get_wall_bottom_left(tile_type)
    if s and w and not n and not e:  # Bottom-right corner
        return tile_types.get_wall_bottom_right(tile_type)
    
    # Straight lines (2 opposite directions or single direction)
    if (n and s) or (n and not s and not e and not w) or (s and not n and not e and not w):
        return tile_types.get_wall_vertical(tile_type)
    if (e and w) or (e and not w and not n and not s) or (w and not e and not n and not s):
        return tile_types.get_wall_horizontal(tile_type)
    
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
            # Check if name has wall in it
            is_wall = "Wall" in tile["name"] 
            is_world_border = tile["name"] == "World Border"
            
            if is_wall and not is_world_border:
                # Get wall connections in 3x3 grid
                connections = get_wall_connections(dungeon, x, y)
                
                # Determine appropriate wall tile
                new_wall_tile = determine_wall_tile(connections, tile["type"])
                
                # Store the update for later application
                walls_to_update.append((x, y, new_wall_tile))
    
    # Second pass: apply all updates
    for x, y, new_tile in walls_to_update:
        dungeon.tiles[x, y] = new_tile


def place_entities_cave(floor_tiles: List[Tuple[int, int]], dungeon: GameMap, floor_number: int, max_rooms: int, biome: str = "any") -> None:
    """Place monsters, chests, and campfires on walkable tiles within a cave section."""
    if len(floor_tiles) < 8:
        return
    # Clamp cave sections to max rooms
    if len(floor_tiles) > max_rooms:
        floor_tiles = random.sample(floor_tiles, max_rooms)

    # Use budget-based enemy spawning system
    monsters, traps = get_enemies_for_floor(floor_number, biome=biome)

    shuffled = list(floor_tiles)
    random.shuffle(shuffled)

    # Place monsters
    for entity in monsters:
        for x, y in shuffled:
            if _spawnable(dungeon, x, y):
                entity.spawn(dungeon, x, y)
                break
    for trap in traps:
        for x, y in shuffled:
            if _spawnable(dungeon, x, y):
                trap.spawn(dungeon, x, y)
                break

    # Maybe place a chest (30% chance per section)
    if random.random() < 0.30:
        import loot_tables
        chest_tier = "basic" if floor_number <= 3 else "advanced"
        loot = loot_tables.generate_tiered_chest_loot(chest_tier)
        chest = entity_factories.make_chest_with_loot(loot, capacity=6)
        for x, y in shuffled:
            if _spawnable(dungeon, x, y):
                chest.spawn(dungeon, x, y)
                break

    # Maybe place a campfire (15% chance per section)
    if random.random() < 0.15:
        for x, y in shuffled:
            if _spawnable(dungeon, x, y):
                entity_factories.campfire.spawn(dungeon, x, y)
                break


class DisjointSet:
    """Union-Find data structure with path compression and union by rank.
    Used to track connected cave regions during cavern generation."""

    def __init__(self) -> None:
        self.parent: Dict[Tuple[int, int], Tuple[int, int]] = {}
        self.rank: Dict[Tuple[int, int], int] = {}

    def find(self, x: Tuple[int, int]) -> Tuple[int, int]:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        # Iterative path compression — avoids Python recursion limits on large maps
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, x: Tuple[int, int], y: Tuple[int, int]) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank.get(rx, 0) < self.rank.get(ry, 0):
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank.get(rx, 0) == self.rank.get(ry, 0):
            self.rank[rx] = self.rank.get(rx, 0) + 1


def join_caverns(dungeon: GameMap, width: int, height: int) -> None:
    """Connect disjoint cave regions by drawing meandering lines toward the map center.

    Closely follows the Monte Carlo cave-joining algorithm from CA_CaveFactory:
      1. Build a DisjointSet for all floor tiles (8-directional adjacency).
      2. Collect one representative point per distinct cave.
      3. For each cave, walk a randomly-meandering line toward the map centre.
      4. Stop only when the NEXT tile is:
           (a) already a floor belonging to a DIFFERENT cave's set, OR
           (b) already connected to the centre reference tile.
         (Stepping onto your own freshly-carved tiles does NOT stop the walk.)
      5. Each stop unions the two sets, progressively merging all caves.
    """
    ds = DisjointSet()

    # Build DS: union all 8-directionally adjacent interior floor pairs
    for x in range(1, width - 1):
        for y in range(1, height - 1):
            if dungeon.tiles[x, y]["walkable"]:
                ds.find((x, y))
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue
                        nx2, ny2 = x + dx, y + dy
                        if 1 <= nx2 < width - 1 and 1 <= ny2 < height - 1:
                            if dungeon.tiles[nx2, ny2]["walkable"]:
                                ds.union((x, y), (nx2, ny2))

    # Find the nearest floor tile to map centre as destination reference
    cx0, cy0 = width // 2, height // 2
    center_ref: Optional[Tuple[int, int]] = None
    for r in range(max(width, height)):
        found = False
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if abs(dx) != r and abs(dy) != r:
                    continue
                tx, ty = cx0 + dx, cy0 + dy
                if 1 <= tx < width - 1 and 1 <= ty < height - 1 and dungeon.tiles[tx, ty]["walkable"]:
                    center_ref = (tx, ty)
                    found = True
                    break
            if found:
                break
        if found:
            break

    if center_ref is None:
        return  # No floor tiles — nothing to connect

    # Collect one representative point per distinct cave
    cave_reps: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for x in range(1, width - 1):
        for y in range(1, height - 1):
            if dungeon.tiles[x, y]["walkable"]:
                root = ds.find((x, y))
                if root not in cave_reps:
                    cave_reps[root] = (x, y)

    def get_dir(pt1: Tuple[int, int], pt2: Tuple[int, int]) -> Tuple[int, int]:
        h = 0 if pt1[0] == pt2[0] else (1 if pt2[0] > pt1[0] else -1)
        v = 0 if pt1[1] == pt2[1] else (1 if pt2[1] > pt1[1] else -1)
        return h, v

    def should_stop(pt: Tuple[int, int], npt: Tuple[int, int]) -> bool:
        """Stop if npt is already a floor tile from a DIFFERENT cave set.
        Mirrors the reference __stop_drawing logic exactly."""
        npt_root = ds.find(npt)
        # Condition 1: npt is connected to the centre reference
        if npt_root == ds.find(center_ref):
            return True
        # Condition 2: npt is a pre-existing floor in a different set
        if dungeon.tiles[npt[0], npt[1]]["walkable"] and npt_root != ds.find(pt):
            return True
        return False

    # Process one representative from every distinct cave
    for start_pt in cave_reps.values():
        pt = start_pt
        for _ in range(width * height):  # safety bound
            h_dir, v_dir = get_dir(pt, (cx0, cy0))

            # Equal-probability 3-way step: row-only, col-only, or diagonal
            # (matches the reference randrange(0,3) distribution)
            move = random.randint(0, 2)
            if move == 0:
                npt = (pt[0] + h_dir, pt[1])
            elif move == 1:
                npt = (pt[0], pt[1] + v_dir)
            else:
                npt = (pt[0] + h_dir, pt[1] + v_dir)

            # Clamp to interior
            npt = (max(1, min(width - 2, npt[0])), max(1, min(height - 2, npt[1])))

            # No progress (already at centre or fully clamped) — stop this line
            if npt == pt:
                break

            if should_stop(pt, npt):
                ds.union(pt, npt)
                break

            # Carve wall → floor, union with current position, advance
            if not dungeon.tiles[npt[0], npt[1]]["walkable"]:
                dungeon.tiles[npt[0], npt[1]] = tile_types.random_floor_tile()
            ds.find(npt)
            ds.union(pt, npt)
            # Widen corridor: carve the 4 cardinal neighbors of npt
            for _wx, _wy in [(npt[0]+1, npt[1]), (npt[0]-1, npt[1]),
                             (npt[0], npt[1]+1), (npt[0], npt[1]-1)]:
                if 1 <= _wx < width - 1 and 1 <= _wy < height - 1:
                    if not dungeon.tiles[_wx, _wy]["walkable"]:
                        dungeon.tiles[_wx, _wy] = tile_types.random_floor_tile()
                    ds.find((_wx, _wy))
                    ds.union(npt, (_wx, _wy))
            pt = npt

def generate_boss_room(
        map_width: int,
        map_height: int,
        engine: Engine,
) -> GameMap:
    _placer = engine.player

    # Generate a boss room with a large chamber
    boss_room = GameMap(engine, map_width, map_height, entities=[engine.player], type="dungeon", name="Boss Room")
    room = RectangularRoom(x=map_width//2 - 10, y=map_height//2, width=20, height=10)
    for x in range(room.x1, room.x2 + 1):
        for y in range(room.y1, room.y2 + 1):
            if x == room.x1 or x == room.x2 or y == room.y1 or y == room.y2:
                boss_room.tiles[x, y] = tile_types.random_wall_tile()
            else:
                boss_room.tiles[x, y] = tile_types.random_floor_tile()

    # one tile in-set from top/bottom walls, every other tile is a statue
    for x in range(room.x1 + 1, room.x2):
        if x % 2 == 0:
            for y in [room.y1 + 2, room.y2 - 2]:
                statue = tile_types.random_statue()            
                tile = boss_room.tiles[x,y]
                tile_cp = int(tile["light"]["ch"])
                statue_cp = int(statue["light"]["ch"])
                sprite = sprite_manager.compose_sprite([tile_cp, statue_cp])
                composed_cp = ord(sprite)
                result = statue.copy()
                result["light"]["ch"] = composed_cp
                result["dark"]["ch"]  = composed_cp
                boss_room.tiles[x, y] = result

    boss_room.upstairs_location = (room.x1 + 2, (room.y1 + room.y2) // 2)
    boss_room.tiles[boss_room.upstairs_location[0], boss_room.upstairs_location[1]] = tile_types.up_stairs
    _placer.place(*boss_room.upstairs_location, boss_room)
    apply_wall_merging(boss_room)
    # Spawn multi-part dragon boss (2 tiles tall) - head at player level, legs below
    entity_factories.create_dragon(boss_room, room.x2 - 3, (room.y1 + room.y2) // 2)
    
    # Start boss music
    import sounds
    sounds.start_boss_music()
    
    return boss_room


def generate_first_floor(
        map_width: int,
        map_height: int,
        engine: Engine,
) -> GameMap:
    # Generate tutorial floor

    _placer = engine.player
    _placer.char = chr(0xE030)  # human character for tutorial

    dungeon = GameMap(engine, map_width, map_height, entities=[_placer], type="dungeon", name="Dungeon", sunlit=False, biome="tutorial")
    rooms: List[RectangularRoom] = []
    center_of_last_room = (0, 0)
    dungeon.biome_str = "Mouth of Aerrok"
    tut_room = RectangularRoom(x=map_width//2, y=map_height//2, width=20, height=9)
    for x in range(tut_room.x1, tut_room.x2 + 1):
        for y in range(tut_room.y1, tut_room.y2 + 1):
            if x == tut_room.x1 or x == tut_room.x2 or y == tut_room.y1 or y == tut_room.y2:
                dungeon.tiles[x, y] = tile_types.random_wall_tile()
            else:
                dungeon.tiles[x, y] = tile_types.wooden_floor
            # top and bottom walls, between x49 and x59
            if y == tut_room.y1 or y == tut_room.y2:
                if x > tut_room.x1 + 1 and x < tut_room.x2 - 2:
                    # every 5 tiles
                    if (x - (tut_room.x1 + 2)) % 5 == 0:
                        dungeon.tiles[x, y] = tile_types.window
                        # Place floor tile behind the window to prevent it from being a solid wall
                        if y == tut_room.y1:
                            dungeon.tiles[x, y - 1] = tile_types.func_light
                        elif y == tut_room.y2:
                            dungeon.tiles[x, y + 1] = tile_types.func_light
    center_y = (tut_room.y1 + tut_room.y2) // 2

    # Locked door on the west wall — the only exit, unlocked with a Dungeon Key
    dungeon.tiles[tut_room.x1, center_y] = tile_types.locked_door
    dungeon.upstairs_location = (tut_room.x1, center_y)

    # Down stairs leading deeper into the dungeon
    dungeon.tiles[tut_room.x2 - 2, center_y] = tile_types.down_stairs
    dungeon.downstairs_location = (tut_room.x2 - 2, center_y)

    import loot_tables
    _start_chest = entity_factories.make_chest_with_loot(loot_tables.generate_starter_chest_loot(), capacity=15)
    #_start_chest.spawn(dungeon, 46, 21)

    #dungeon.tiles[56, 21] = tile_types.generate_foliage_tile()
    #dungeon.tiles[55, 21] = tile_types.generate_foliage_tile()
    #dungeon.tiles[55, 28] = tile_types.generate_foliage_tile()
    #dungeon.tiles[56, 28] = tile_types.generate_foliage_tile()


    apply_wall_merging(dungeon)

    rooms.append(tut_room)

    entity_factories.training_dummy.spawn(dungeon, 47, 22)
    guide = copy.deepcopy(entity_factories.tutorial_guide)
    guide.generate_villager(
        job="guide",
        gendered_noun="man",
        age=100,
        hair_color="white",
        hair_style="long",
        facial_hair="bearded",
        skin_tone="fair",
        eye_color="blue",
        clothing_style="formal",
        head="white cone hat",
        torso="brown silk robe",
        legs="silk trousers",
        feet="leather shoes",
        accessories="gold necklaces",
        pitch=0.7
    )
    guide.spawn(dungeon, 47, 27)

    player_start = (tut_room.x1 + 2, center_y)
    _placer.place(*player_start, dungeon)
    dungeon.player_start = player_start

    return dungeon




def generate_dungeon(
        max_rooms: int,
        room_min_size: int,
        room_max_size: int,
        map_width: int,
        map_height: int,
        engine: Engine,
        noise_vals: Tuple,
        player_proxy=None,
        floor_num: Optional[int] = None,
) -> GameMap:
    # Don't re-seed here - it breaks room generation variety
    # Seeding is handled at the top level in setup_game.py
    

    # Use proxy instead of real player for background floor generation
    _placer = player_proxy if player_proxy is not None else engine.player
    _floor = floor_num if floor_num is not None else engine.game_world.current_floor

    # Noise params
    temperature = noise_vals[0]
    erosion = noise_vals[1]
    vegetation = noise_vals[2]
    weirdness = noise_vals[3]

    if temperature < -2.0:
        vegetation = -10

    # Determine if should generate rooms, caves, or mixed
    # Inbetween -2,2 gives ruins 

    if _floor == 11:
        return generate_boss_room(map_width, map_height, engine)
        

    # Generates new map
    dungeon = GameMap(engine, map_width, map_height, entities=[_placer], type="dungeon", name="Dungeon")
    rooms: List[RectangularRoom] = []
    center_of_last_room = (0, 0)

    # Cavern Type
    if erosion > 2.0 or (erosion <= 2.0 and erosion >= -2.0):
        if erosion > 2.0:
            dungeon.biome = "caverns"
            dungeon.biome_str = "Caverns"
        else:
            pass  # Ruins biome is set later in mixed section after room/cave split
        # Seed map: 40% floor, 60% wall
        for x in range(1, dungeon.width - 1):
            for y in range(1, dungeon.height - 1):
                if random.random() < 0.4:
                    dungeon.tiles[x, y] = tile_types.random_floor_tile()
                else:
                    dungeon.tiles[x, y] = tile_types.cave_wall

        # Cellular automata smoothing — 4 passes, double-buffered so each pass
        # reads cleanly from the previous iteration without in-place bias.
        for _pass in range(4):
            new_tiles = dungeon.tiles.copy()
            for x in range(1, dungeon.width - 1):
                for y in range(1, dungeon.height - 1):
                    wall_count = 0
                    for dx in range(-1, 2):
                        for dy in range(-1, 2):
                            if dx == 0 and dy == 0:
                                continue
                            neighbor_tile = dungeon.tiles[x + dx, y + dy]
                            if not neighbor_tile["walkable"] and not neighbor_tile["interactable"]:
                                wall_count += 1
                    if wall_count > 5:
                        new_tiles[x, y] = tile_types.cave_wall
                    elif wall_count < 5:
                        new_tiles[x, y] = tile_types.random_floor_tile()
                    # else: keep same (already copied)
            dungeon.tiles = new_tiles

        # Connect all disjoint cave regions into one traversable map
        join_caverns(dungeon, map_width, map_height)

        # Place player near map centre in the main (joined) cave
        for _r in range(max(map_width, map_height)):
            _placed = False
            for _dx in range(-_r, _r + 1):
                for _dy in range(-_r, _r + 1):
                    if abs(_dx) != _r and abs(_dy) != _r:
                        continue
                    _px, _py = map_width // 2 + _dx, map_height // 2 + _dy
                    if (1 <= _px < map_width - 1 and 1 <= _py < map_height - 1
                            and dungeon.tiles[_px, _py]["walkable"]):
                        _placer.place(_px, _py, dungeon)
                        _placed = True
                        break
                if _placed:
                    break
            if _placed:
                break

        # Spawn entities in grid sections across the cave (skip player start section)
        _section_size = 20
        _player_sx = (_placer.x // _section_size) * _section_size
        _player_sy = (_placer.y // _section_size) * _section_size
        for _gx in range(1, map_width - 1, _section_size):
            for _gy in range(1, map_height - 1, _section_size):
                if _gx == _player_sx and _gy == _player_sy:
                    continue  # Skip the player's starting section
                _section_tiles = [
                    (_tx, _ty)
                    for _tx in range(_gx, min(_gx + _section_size, map_width - 1))
                    for _ty in range(_gy, min(_gy + _section_size, map_height - 1))
                    if dungeon.tiles[_tx, _ty]["walkable"]
                ]
                place_entities_cave(_section_tiles, dungeon, _floor, max_rooms, dungeon.biome)

        # Place down stairs in caves - find accessible location far from player
        # Collect all valid walkable tiles that are reasonably far from player
        _min_distance = min(map_width, map_height) // 4
        _stair_candidates = []
        for _sx in range(3, map_width - 3):
            for _sy in range(3, map_height - 3):
                if not dungeon.tiles[_sx, _sy]["walkable"]:
                    continue
                if str(dungeon.tiles[_sx, _sy]["name"]) in {"Water", "Foliage"}:
                    continue
                # Check distance from player
                _dist = ((abs(_sx - _placer.x) ** 2 + abs(_sy - _placer.y) ** 2) ** 0.5)
                if _dist >= _min_distance:
                    _stair_candidates.append((_sx, _sy, _dist))
        
        if _stair_candidates:
            # Sort by distance and pick one from the farthest quartile
            _stair_candidates.sort(key=lambda c: c[2], reverse=True)
            _far_candidates = _stair_candidates[:max(1, len(_stair_candidates) // 4)]
            _sx, _sy, _ = random.choice(_far_candidates)
            dungeon.tiles[_sx, _sy] = tile_types.down_stairs
            dungeon.downstairs_location = (_sx, _sy)
            print(f"[GEN] Cave down stairs placed at {(_sx, _sy)}, distance from player: {_}")
        else:
            print("[GEN] WARNING: Could not place cave down stairs, will rely on safety pass")

        # Place up stairs at player start for cavern-only floors
        if erosion > 2.0:
            dungeon.tiles[_placer.x, _placer.y] = tile_types.up_stairs
            dungeon.upstairs_location = (_placer.x, _placer.y)

    # Dungeon Type
    if erosion < -2.0 or (-2.0 <= erosion <= 2.0):
        if erosion < -2.0:
            dungeon.biome = "dungeon"
            dungeon.biome_str = "Dungeons"
        else:
            dungeon.biome = "ruins"
            dungeon.biome_str = "Ruins"
        if rooms:
            rooms = [] # Clear cave generated rooms for ruins type
        for r in range(max_rooms):
            room_height = random.randint(room_min_size, room_max_size)
            room_width = random.randint(room_min_size, room_max_size)

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
                _placer.place(*new_room.center, dungeon)
                # Guaranteed campfire in first room
                place_campfires(dungeon, "dungeon_first_room", room=new_room, player_pos=new_room.center)
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

            # Add the room to the list BEFORE entity placement
            rooms.append(new_room)

            # Place entities in non-first rooms
            if len(rooms) > 1:  # Skip first room for entity placement  
                place_entities(new_room, dungeon, _floor, dungeon.biome)
    
    # Place stairs in rooms IMMEDIATELY after room generation, BEFORE water pools/foliage.
    # This ensures water and foliage generation can avoid stair locations.
    if rooms:
        # Place down stairs in last room (dungeon exit)
        avoid_tiles = set()
        for room in reversed(rooms):  # Try rooms from last to first
            down_pos = _find_valid_stair_tile_in_room(dungeon, room, avoid_tiles)
            if down_pos:
                dungeon.tiles[down_pos] = tile_types.down_stairs
                dungeon.downstairs_location = down_pos
                print(f"[GEN] Down stairs placed at {down_pos} in room")
                avoid_tiles.add(down_pos)
                break
        else:
            print("[GEN] WARNING: Could not place down stairs in any room")
        
        # Place up stairs in first room (dungeon entrance)
        up_pos = _find_valid_stair_tile_in_room(dungeon, rooms[0], avoid_tiles)
        if up_pos:
            dungeon.tiles[up_pos] = tile_types.up_stairs
            dungeon.upstairs_location = up_pos
            print(f"[GEN] Up stairs placed at {up_pos} in first room")
        else:
            print("[GEN] WARNING: Could not place up stairs in first room")



    # Post-processing: Remove isolated walls that have no floors touching them
    # Skip for caverns - it destroys wall masses by hollowing out their interiors
    print(f"[GEN] post-processing: remove_isolated_walls/ensure_room_walls start (erosion={erosion:.3f})")
    if erosion < -2.0:
        remove_isolated_walls(dungeon)
    elif -2.0 <= erosion <= 2.0:
        ensure_room_walls(dungeon=dungeon, rooms=rooms)
    print("[GEN] post-processing walls done")
    # Check if door has neighbor wall
    print("[GEN] door-neighbor check start")
    wall_count = 0
    for x in range(1, dungeon.width - 1):
        for y in range(1, dungeon.height - 1):
            if dungeon.tiles[x,y]["interactable"]:
                wall_count = 0
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue
                        neighbor_tile = dungeon.tiles[x + dx, y + dy]
                        if not neighbor_tile["walkable"] and not neighbor_tile["interactable"]:
                            wall_count += 1
                if wall_count == 0:        
                    # Convert door to floor if no adjacent walls
                    dungeon.tiles[x,y] = tile_types.random_floor_tile()

    print("[GEN] door-neighbor check done")
    # Seal the border: overwrite the 1-tile inset ring with walls so the world
    # border is never directly reachable regardless of map type or generation.
    print("[GEN] border seal start")
    for _bx in range(1, dungeon.width - 1):
        dungeon.tiles[_bx, 1] = tile_types.wall
        dungeon.tiles[_bx, dungeon.height - 2] = tile_types.wall
    for _by in range(1, dungeon.height - 1):
        dungeon.tiles[1, _by] = tile_types.wall
        dungeon.tiles[dungeon.width - 2, _by] = tile_types.wall

    print("[GEN] border seal done")
    # Apply wall merging system to create connected wall appearances
    print("[GEN] apply_wall_merging start")
    apply_wall_merging(dungeon)
    print("[GEN] apply_wall_merging done")
    if vegetation > 0:# Mossification
        print(f" Moss val: {(vegetation/4)**2}")
        for x in range(dungeon.width):
            for y in range(dungeon.height):
                tile = dungeon.tiles[x, y]
                if not tile["walkable"] and not tile["interactable"]:
                    if random.random() < (vegetation/4)**2:
                        
                        dungeon.tiles[x, y] = tile_types.mossify_wall_tile(tile)
                elif tile["walkable"]:
                    if random.random() < (vegetation/6)**2:
                        # Ensure tile is not a stair
                        if tile["name"] not in ["<purple>Down Stairs</purple>", "<purple>Up Stairs</purple>"]:
                            dungeon.tiles[x, y] = tile_types.random_mossy_floor_tile()

    print("[GEN] mossification done")
    # Water pool post-processing
    def _noise_pool_tiles(cx: int, cy: int, base_radius: float, noise_amp: float, seed: int) -> list:
        """Return floor-tile positions inside a noise-perturbed circle.
        Boundary is determined per-angle so the edge is smooth and organic,
        not the staircase pattern a random walk produces."""
        rng = np.random.default_rng(seed)
        n_ctrl = 14
        angles_ctrl = np.linspace(0.0, 2.0 * np.pi, n_ctrl + 1)
        radii_ctrl  = base_radius + rng.uniform(-noise_amp, noise_amp, n_ctrl + 1)
        radii_ctrl[-1] = radii_ctrl[0]   # make periodic
        max_r = int(base_radius + noise_amp) + 1
        tiles = []
        for dx in range(-max_r, max_r + 1):
            for dy in range(-max_r, max_r + 1):
                angle = np.arctan2(dy, dx) % (2.0 * np.pi)
                thresh = float(np.interp(angle, angles_ctrl, radii_ctrl))
                dist   = (dx * dx + dy * dy) ** 0.5
                if dist <= thresh:
                    nx, ny = cx + dx, cy + dy
                    if 2 <= nx < dungeon.width - 2 and 2 <= ny < dungeon.height - 2:
                        tiles.append((nx, ny))
        return tiles

    if 0 == 0:#-4 < temperature < 4:
        water_pool_count = random.randint(1, 10)
        print(f"Generating {water_pool_count} water pools with noise temperature value: {temperature}")
        for _ in range(water_pool_count):
            base_radius = random.uniform(2.0, 4.5)
            noise_amp   = random.uniform(0.6, 1.4)
            start_x = random.randint(2, dungeon.width - 3)
            start_y = random.randint(2, dungeon.height - 3)
            pool_seed = random.getrandbits(32)
            pool_tiles = _noise_pool_tiles(start_x, start_y, base_radius, noise_amp, pool_seed)
            # Only overwrite walkable tiles so pools don't erase walls
            for x, y in pool_tiles:
                # Never let water pools overwrite staircase tiles (already placed).
                if dungeon.tiles[x, y]["walkable"] and str(dungeon.tiles[x, y]["name"]) not in {
                    "<purple>Down Stairs</purple>",
                    "<purple>Up Stairs</purple>",
                }:
                    dungeon.tiles[x, y] = tile_types.water
    print("[GEN] water pools done")
    # Note: Stairs are already placed immediately after room generation, so no stamping needed here.

    # Foliage post processing (must happen before water animation build)
    if vegetation > 0:
        for x in range(dungeon.width):
            for y in range(dungeon.height):
                tile = dungeon.tiles[x, y]
                if tile["walkable"] and random.random() < (2**(vegetation/20)-1) and random.randint(1,3) == 1:
                    if tile["name"] not in ["<purple>Down Stairs</purple>", "<purple>Up Stairs</purple>"]:
                        foliage = tile_types.generate_foliage_tile()
                        tile = dungeon.tiles[x,y]
                        tile_cp = int(tile["light"]["ch"])
                        foliage_cp = int(foliage["light"]["ch"])
                        foliage_tint = tuple(int(v) for v in foliage["light"]["fg"])
                        sprite = sprite_manager.compose_sprite(
                            [tile_cp, foliage_cp],
                            layer_tints=[None, foliage_tint],
                        )
                        composed_cp = ord(sprite)
                        result = dungeon.tiles[x, y].copy()
                        result["light"]["ch"] = composed_cp
                        result["dark"]["ch"]  = composed_cp
                        dungeon.tiles[x, y] = result
    print("[GEN] foliage done")
    
    # Ice-ification (applied AFTER water and foliage so they get tinted too, but BEFORE water animation build)
    if temperature < -2.0:
        print(f"[GEN] Ice-ification start, val: {(abs(temperature)/4)**2}")
        for x in range(dungeon.width):
            for y in range(dungeon.height):
                # Make sure is not water 
                tile = dungeon.tiles[x, y]
                if tile["name"] == "Water":
                    continue
                if not tile["walkable"] and not tile["interactable"]:
                    dungeon.tiles[x, y] = tile_types.icify_wall_tile(tile)
                elif tile["walkable"]:
                    if tile["name"] not in ["<purple>Down Stairs</purple>", "<purple>Up Stairs</purple>"]:
                        dungeon.tiles[x, y] = tile_types.icify_floor_tile(tile)
        print("[GEN] ice-ification done")
        dungeon.biome = "frozen"
        dungeon.biome_str = "Frozen " + dungeon.biome_str
        vegetation = 0  # No moss or foliage in frozen biome

    # Build composited water animation frames AFTER ice-ification so icy floor tints are preserved
    # Must run while the tileset is available (deferred mode is active during
    # background gen, so sprites are queued and flushed on the main thread).
    sprite_manager.build_dungeon_water_anim(dungeon)
    print("[GEN] water animation build done")

    if vegetation > 4:
        dungeon.biome = "lush"
        dungeon.biome_str = "Lush " + dungeon.biome_str
    elif vegetation > 2:
        dungeon.biome_str = "Overgrown " + dungeon.biome_str

    # Final stair safety pass: guarantee downstairs exists on a valid, non-water, unoccupied tile.
    _down = getattr(dungeon, "downstairs_location", (0, 0))

    def _tile_has_entity(x: int, y: int) -> bool:
        return any(e.x == x and e.y == y for e in dungeon.entities)

    def _valid_downstairs_tile(pos: Tuple[int, int]) -> bool:
        if not isinstance(pos, tuple) or len(pos) != 2:
            return False
        x, y = pos
        if not dungeon.in_bounds(x, y):
            return False
        tile = dungeon.tiles[x, y]
        if not tile["walkable"]:
            return False
        if str(tile["name"]) in {"Water", "Foliage", "Mossy Floor"}:
            return False
        dw_anim = getattr(dungeon, "dungeon_water_anim", None)
        if dw_anim and (x, y) in dw_anim:
            return False
        if _tile_has_entity(x, y):
            return False
        return True

    if not _valid_downstairs_tile(_down):
        # Clean up invalid stair tile FIRST before placing new stairs
        if isinstance(_down, tuple) and len(_down) == 2 and dungeon.in_bounds(_down[0], _down[1]):
            old_tile_name = str(dungeon.tiles[_down[0], _down[1]]["name"])
            if old_tile_name == "<purple>Down Stairs</purple>":
                dungeon.tiles[_down[0], _down[1]] = tile_types.random_floor_tile()
                print(f"[GEN] Cleaned up invalid stairs at {_down} - replacing with floor")
        
        _candidates: List[Tuple[int, int]] = []
        for _x in range(2, dungeon.width - 2):
            for _y in range(2, dungeon.height - 2):
                _tile = dungeon.tiles[_x, _y]
                if not _tile["walkable"]:
                    continue
                _name = str(_tile["name"])
                if _name in {"Water", "<purple>Up Stairs</purple>", "Foliage", "Mossy Floor", "<purple>Down Stairs</purple>"}:
                    continue
                dw_anim = getattr(dungeon, "dungeon_water_anim", None)
                if dw_anim and (_x, _y) in dw_anim:
                    continue
                if _tile_has_entity(_x, _y):
                    continue
                _candidates.append((_x, _y))

        if _candidates:
            # Favor a location far from player spawn for progression pacing.
            _sx, _sy = max(
                _candidates,
                key=lambda p: (p[0] - _placer.x) * (p[0] - _placer.x) + (p[1] - _placer.y) * (p[1] - _placer.y),
            )
            dungeon.tiles[_sx, _sy] = tile_types.down_stairs
            dungeon.downstairs_location = (_sx, _sy)
            print(f"[GEN] Relocated stairs from {_down} to {(_sx, _sy)}")
        else:
            # Last-resort fallback: place at player tile to avoid missing stairs entirely.
            dungeon.tiles[_placer.x, _placer.y] = tile_types.down_stairs
            dungeon.downstairs_location = (_placer.x, _placer.y)
            print("[GEN] No valid stair locations found, placing at player spawn")

    print("[GEN] generate_dungeon complete")
    return dungeon


