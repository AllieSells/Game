from typing import Tuple, Optional

import numpy as np
import random

import color

graphic_dt = np.dtype(
    [
        ("ch", np.int32),  
        ("fg", "3B"),      
        ("bg", "3B"),
    ]
)

tile_dt = np.dtype(
    [
        ("light_level", np.float32),  # 0.0 = fully dark, 1.0 = fully lit
        ("name", "U64"),
        ("walkable", np.bool_),
        ("transparent", np.bool_),
        ("dark", graphic_dt),  
        ("light", graphic_dt),
        ("interactable", np.bool_),
    ]
)

def new_tile(
        *,
        light_level: float = 0.0,
        name: str = "<error>",
        walkable: int,
        transparent: int,
        dark: Tuple[int, Tuple[int, int, int], Tuple[int, int, int]],
        light: Tuple[int, Tuple[int, int, int], Tuple[int, int, int]],
        interactable: bool = False


) -> np.ndarray:
    return np.array((light_level, name, walkable, transparent, dark, light, interactable), dtype=tile_dt)

SHROUD = np.array((ord(" "), (255, 255, 255), (10, 10, 10)), dtype=graphic_dt)

def random_floor_char() -> int:
    # Don't re-seed here as it can break generation flow
    return ord(random.choice([" ", " ", " ", " ", " ", " ", chr(0xE009), chr(0xE00A), chr(0xE00B), chr(0xE00C)]))


def fill_random_grasses() -> np.ndarray:
    # Generates a grass tile - don't re-seed to avoid breaking generation
    
    char = random_floor_char()

    grass_color = (random.randint(35, 40), random.randint(105, 110), random.randint(35, 40))
    dark_grass_color = (grass_color[0] // 2, grass_color[1] // 2, grass_color[2] // 2)
    grass_foreground_lit = grass_color[0]-5, grass_color[1]-5, grass_color[2]-5
    grass_foreground_dark = dark_grass_color[0]-5, dark_grass_color[1]-5, dark_grass_color[2]-5

    return new_tile(
        name="Grass",
        walkable=True,
        transparent=True,
        # Use the same character for both dark and light, but with different colors
        dark=(random_floor_char(), (grass_foreground_dark), (dark_grass_color)),
        light=(random_floor_char(), (grass_foreground_lit), (grass_color)),
    )


def random_floor_tile():
    """Generate a random floor tile with varied appearance."""
    # Don't re-seed to avoid breaking main generation flow
    
    # Use the existing random_floor_char function
    char = random_floor_char()
    
    return new_tile(
        name="Floor",
        walkable=True,
        transparent=True,
        # Use the random character for both dark and light
        # Dark grey fg
        dark=(char, ((40+random.randint(-10,-10)), (40+random.randint(-10,-10)), (40+random.randint(-10,-10))), (25, 25, 25)),
        light=(char, ((90+random.randint(-10, 10)), (90+random.randint(-10, 10)), (90+random.randint(-10, 10))), (80, 80, 80)),
    )


def random_wall_tile():
    """Generate a random wall tile by sampling a base tile (wall or mossy)
    and constructing a fresh tile with small variations applied. Building a
    new tile via `new_tile(...)` avoids subtle numpy structured-array
    assignment issues and ensures the returned tile is distinct.
    """
    # Don't re-seed to avoid breaking main generation flow
    
    # Chance to be mossy
    base = wall

    return wall


    


floor = new_tile(
    name="Floor",
    walkable=True,
    transparent=True,
    # Dark = much darker grey, Light = darker grey for lit floors
    dark=(ord(" "), (255, 255, 255), (25, 25, 25)),
    light=(ord(" "), (255, 255, 255), (80, 80, 80)),
)

wooden_floor = new_tile(
    name="Fungal Floor",
    walkable=True,
    transparent=True,
    # Yellowish brown
    dark=(ord(" "), (255, 255, 255), (89, 87, 78)),
    light=(ord(" "), (255, 255, 255), (158, 152, 128)),
)



cave_wall = new_tile(
    name="Cavern Wall",
    walkable=False,
    transparent=False,
    dark=(0xE135, (60, 60, 60), (15, 15, 15)),
    light =(0xE135, (color.sprite_sheet), (80,80,80)),
)
    
wall = new_tile(
    name="Stone Wall",
    walkable=False,
    transparent=False,
    # Use darker greys for wall glyph foreground so the wall glyph appears less bright
    dark=(0xE125, (60, 60, 60), (25, 25, 25)),
    # Make wall foreground/background a bit whiter when lit to increase contrast
    light=(0xE125, (color.sprite_sheet), (80,80,80)),
)

# Box drawing wall tile generator function
def create_wall_tile(character: str, base_tile=None):
    """Create a wall tile with the specified character using the stone wall as template."""
    if base_tile is None:
        base_tile = wall
    
    # Create a copy of the base tile with the new character
    return new_tile(
        name=base_tile["name"],
        walkable=base_tile["walkable"],
        transparent=base_tile["transparent"],
        dark=(ord(character), base_tile["dark"]["fg"], base_tile["dark"]["bg"]),
        light=(ord(character), base_tile["light"]["fg"], base_tile["light"]["bg"]),
        interactable=base_tile["interactable"],
    )

# Wall tile variants - generated on demand
def get_wall_horizontal(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE135))
    return create_wall_tile(chr(0xE125))

def get_wall_vertical(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE138))
    return create_wall_tile(chr(0xE128))

def get_wall_top_left(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE130))
    return create_wall_tile(chr(0xE120))

def get_wall_top_right(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE13A))
    return create_wall_tile(chr(0xE12A))

def get_wall_bottom_left(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE131))
    return create_wall_tile(chr(0xE121))

def get_wall_bottom_right(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE139))
    return create_wall_tile(chr(0xE129))

def get_wall_cross(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE136))
    return create_wall_tile(chr(0xE126))

def get_wall_t_up(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE133))
    return create_wall_tile(chr(0xE123))

def get_wall_t_down(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE132))
    return create_wall_tile(chr(0xE122))

def get_wall_t_left(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE134))
    return create_wall_tile(chr(0xE124))

def get_wall_t_right(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE137))
    return create_wall_tile(chr(0xE127))

debug_wall = new_tile(
    name="Stone Wall",
    walkable=False,
    transparent=False,
    # Use darker greys for wall glyph foreground so the wall glyph appears less bright
    dark=(ord(" "), (60, 60, 60), (15, 15, 15)),
    # Make wall foreground/background a bit whiter when lit to increase contrast
    light=(ord(" "), (255, 10, 10), (255, 60, 60)),
)

world_border = new_tile(
    name="World Border",
    walkable=False,
    transparent=False,
    # Use a distinctive character and darker colors for world border
    dark=(ord("▓"), (255, 0, 0), (0, 0, 0)),
    light=(ord("▓"), (255, 0, 0), (255, 0, 0)),
)

down_stairs = new_tile(
    name="<purple>Down Stairs</purple>",
    walkable=True,
    transparent=True,
    dark=((0xE00D), (100, 100, 100), (25, 25, 25)),
    light=((0xE00D), (255, 255, 255), (50, 50, 50)),
)

up_stairs = new_tile(
    name="<purple>Up Stairs</purple>",
    walkable=True,
    transparent=True,
    dark=((0xE00E), (100, 100, 100), (25, 25, 25)),
    light=((0xE00E), (255, 255, 255), (50, 50, 50)),
)
closed_door = new_tile(
    name="Door",
    walkable=False,
    transparent=False,
    dark=(0xE000, (60, 60, 60), (15, 15, 15)),
    light=(0xE000, (255, 255, 255), (0, 0, 0)),
    interactable=True
)
open_door = new_tile(
    name="Open Door",
    walkable=True,
    transparent=True,
    dark=(0xE001, (60, 60, 60), (15, 15, 15)),
    light=(0xE001, (255, 255, 255), (0, 0, 0)),
    interactable=True
)
