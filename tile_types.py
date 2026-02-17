from typing import Tuple, Optional

import numpy as np
import random

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
    return ord(random.choice([" ", " ", " ", " ", " ", " ", ".", ",", "`"]))


def fill_random_grasses() -> np.ndarray:
    # Generates a grass tile
    char = random_floor_char()

    return new_tile(
        name="Grass",
        walkable=True,
        transparent=True,
        # Use the same character for both dark and light, but with different colors
        dark=(char, (50, 100, 50), (10, 10, 10)),
        light=(char, (100, 200, 100), (30, 30, 30)),
    )


def random_floor_tile():
    """Generate a random floor tile with varied appearance."""
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
    # Chance to be mossy
    if random.random() < 0.05:
        base = mossy_wall
    else:
        base = wall

    # Extract base values as plain Python ints/tuples
    base_name = str(base["name"])
    base_walkable = bool(base["walkable"])
    base_transparent = bool(base["transparent"])

    base_dark_ch = int(base["dark"]["ch"])
    base_dark_fg = tuple(int(x) for x in base["dark"]["fg"])
    base_dark_bg = tuple(int(x) for x in base["dark"]["bg"])

    base_light_ch = int(base["light"]["ch"])
    base_light_fg = tuple(int(x) for x in base["light"]["fg"])
    base_light_bg = tuple(int(x) for x in base["light"]["bg"])

    # Small random variation helper with clamping
    def vary_channel(base_tuple, delta):
        return (
            max(0, min(255, base_tuple[0] + 0)),
            max(0, min(255, base_tuple[1] + 0)),
            max(0, min(255, base_tuple[2] + 0))
        )

    dark_fg = vary_channel(base_dark_fg, 8)
    dark_bg = vary_channel(base_dark_bg, 6)
    light_fg = vary_channel(base_light_fg, 8)
    light_bg = vary_channel(base_light_bg, 6)

    glyph = base_dark_ch

    return new_tile(
        name=base_name,
        walkable=base_walkable,
        transparent=base_transparent,
        dark=(glyph, dark_fg, dark_bg),
        light=(glyph, light_fg, light_bg),
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



mossy_wall = new_tile(
    name="<green>Lichenous Wall</green>",
    walkable=False,
    transparent=False,
    dark=(ord("▓"), (60, 60, 60), (15, 15, 15)),
    light=(ord("▓"), (100, 200, 100), (60, 60, 60)),
)
    
wall = new_tile(
    name="Stone Wall",
    walkable=False,
    transparent=False,
    # Use darker greys for wall glyph foreground so the wall glyph appears less bright
    dark=(ord(" "), (60, 60, 60), (15, 15, 15)),
    # Make wall foreground/background a bit whiter when lit to increase contrast
    light=(ord(" "), (200, 200, 200), (60, 60, 60)),
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
def get_wall_horizontal():
    return create_wall_tile("═")

def get_wall_vertical():
    return create_wall_tile("║")

def get_wall_top_left():
    return create_wall_tile("╚")

def get_wall_top_right():
    return create_wall_tile("╝")

def get_wall_bottom_left():
    return create_wall_tile("╔")

def get_wall_bottom_right():
    return create_wall_tile("╗")

def get_wall_cross():
    return create_wall_tile("╬")

def get_wall_t_up():
    return create_wall_tile("╦")

def get_wall_t_down():
    return create_wall_tile("╩")

def get_wall_t_left():
    return create_wall_tile("╠")

def get_wall_t_right():
    return create_wall_tile("╣")

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
    dark=(ord(">"), (100, 100, 100), (25, 25, 25)),
    light=(ord(">"), (255, 255, 255), (50, 50, 50)),
)

up_stairs = new_tile(
    name="<purple>Up Stairs</purple>",
    walkable=True,
    transparent=True,
    dark=(ord("<"), (100, 100, 100), (25, 25, 25)),
    light=(ord("<"), (255, 255, 255), (50, 50, 50)),
)
closed_door = new_tile(
    name="Door",
    walkable=False,
    transparent=False,
    dark=(ord("•"), (60, 60, 60), (15, 15, 15)),
    light=(ord("•"), (255, 212, 0), (89, 52, 28)),
    interactable=True
)
open_door = new_tile(
    name="Open Door",
    walkable=True,
    transparent=True,
    dark=(ord("/"), (60, 60, 60), (15, 15, 15)),
    light=(ord("/"), (255, 212, 0), (89, 52, 28)),
    interactable=True
)
