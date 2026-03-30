CAN_BE_MOSSY = {
    "horizontal",
    "t_down",
    "top_left",
    "top_right",
}
import sprite_manager
def mossify_wall_tile(tile):
    # Merge allowable wall types with moss texture
    if tile["direction"] not in CAN_BE_MOSSY:
        return tile
    # Copy the tile to avoid mutating the original
    new_tile = tile.copy()
    for variant in ("dark", "light"):
        ch = tile[variant]["ch"]
        if isinstance(ch, str):
            base_cp = ord(ch)
        else:
            base_cp = int(ch)
        moss_cp = 0xE12B
        # compose_sprite returns a character
        if tile["direction"] == "horizontal":
            x_offset = 2
        elif tile["direction"] == "t_down":
            x_offset = 2
        elif tile["direction"] == "top_left":
            x_offset = 4
        elif tile["direction"] == "top_right":
            x_offset = 0
        new_ch = sprite_manager.compose_sprite([base_cp, moss_cp], x_offset=x_offset, y_offset=0)
        # Match the type of the original field
        if isinstance(ch, str):
            new_tile[variant]["ch"] = new_ch
        else:
            new_tile[variant]["ch"] = ord(new_ch)
    return new_tile
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
        ("type", "U16"),
        ("direction", "U16"),

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
        interactable: bool = False,
        type: Optional[str] = None,
        direction: Optional[str] = None


) -> np.ndarray:
    return np.array((light_level, name, walkable, transparent, dark, light, interactable, type, direction), dtype=tile_dt, )

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




    
moss_floor = new_tile(
    name="Mossy Floor",
    walkable=True,
    transparent=True,
    dark=(0xE12C, (40, 40, 40), (25, 25, 25)),
    light=(0xE12C, (255, 255, 255), (80, 80, 80)),
)

def random_mossy_floor_tile():
    char = random.choice([0xE12C, 0xE12D, 0xE12E, 0xE12F])
    color_mod = random.randint(-10, 10)
    return new_tile(
        name="Mossy Floor",
        walkable=True,
        transparent=True,
        dark=(char, (40 + color_mod, 40 + color_mod, 40 + color_mod), (25, 25, 25)),
        light=(char, (245 + color_mod, 245 + color_mod, 245 + color_mod), (80, 80, 80)),
    )


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
    type = "cave"
)
    
wall = new_tile(
    name="Stone Wall",
    walkable=False,
    transparent=False,
    # Use darker greys for wall glyph foreground so the wall glyph appears less bright
    dark=(0xE125, (60, 60, 60), (25, 25, 25)),
    # Make wall foreground/background a bit whiter when lit to increase contrast
    light=(0xE125, (color.sprite_sheet), (80,80,80)),
    type = "dungeon"
)

foliage = new_tile(
    name="Foliage",
    walkable=True,
    transparent=True,
    dark=(0xE13C, (30, 30, 30), (25, 25, 25)),
    light=(0xE13C, (255, 255, 255), (80, 80, 80)),
)


water = new_tile(
    name="Water",
    walkable=True,
    transparent=True,
    dark=(0xE140, (0, 0, 0), (10, 10, 10)),
    light=(0xE140, (255, 255, 255), (30, 110, 135)),
)


def generate_foliage_tile():
    char = random.choice([0xE13C, 0xE13D, 0xE13E, 0xE13F])
    red = 150
    blue = 150
    green = 255
    rb_color_mod = random.randint(0, 100)
    g_color_mod = random.randint(0, 100)

    return new_tile(
        name="Foliage",
        walkable=True,
        transparent=True,
        dark=(char, (30, 30, 30), (25, 25, 25)),
        light=(char, (red-rb_color_mod, green-g_color_mod, blue-rb_color_mod), (80, 80, 80)),
    )

# Box drawing wall tile generator function
def create_wall_tile(character: str, base_tile=None, direction: Optional[str] = None):
    """Create a wall tile with the specified character using the stone wall as template, and store directionality."""
    if base_tile is None:
        base_tile = wall
    tile = new_tile(
        name=base_tile["name"],
        walkable=base_tile["walkable"],
        transparent=base_tile["transparent"],
        dark=(ord(character), base_tile["dark"]["fg"], base_tile["dark"]["bg"]),
        light=(ord(character), base_tile["light"]["fg"], base_tile["light"]["bg"]),
        interactable=base_tile["interactable"],
        type = base_tile["type"],
        direction=direction
    )
    return tile

# Wall tile variants - generated on demand
def get_wall_horizontal(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE135), direction="horizontal")
    return create_wall_tile(chr(0xE125), direction="horizontal")

def get_wall_vertical(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE138), direction="vertical")
    return create_wall_tile(chr(0xE128), direction="vertical")

def get_wall_top_left(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE130), direction="top_left")
    return create_wall_tile(chr(0xE120), direction="top_left")

def get_wall_top_right(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE13A), direction="top_right")
    return create_wall_tile(chr(0xE12A), direction="top_right")

def get_wall_bottom_left(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE131), direction="bottom_left")
    return create_wall_tile(chr(0xE121), direction="bottom_left")

def get_wall_bottom_right(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE139), direction="bottom_right")
    return create_wall_tile(chr(0xE129), direction="bottom_right")

def get_wall_cross(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE136), direction="cross")
    return create_wall_tile(chr(0xE126), direction="cross")

def get_wall_t_up(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE133), direction="t_up")
    return create_wall_tile(chr(0xE123), direction="t_up")

def get_wall_t_down(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE132), direction="t_down")
    return create_wall_tile(chr(0xE122), direction="t_down")

def get_wall_t_left(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE134), direction="t_left")
    return create_wall_tile(chr(0xE124), direction="t_left")

def get_wall_t_right(type: Optional[str] = None):
    if type == "cave":
        return create_wall_tile(chr(0xE137), direction="t_right")
    return create_wall_tile(chr(0xE127), direction="t_right")

debug_wall = new_tile(
    name="Stone Wall",
    walkable=False,
    transparent=False,
    # Use darker greys for wall glyph foreground so the wall glyph appears less bright
    dark=(ord(" "), (60, 60, 60), (15, 15, 15)),
    # Make wall foreground/background a bit whiter when lit to increase contrast
    light=(ord(" "), (255, 10, 10), (255, 60, 60)),
    type="dungeon"
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
