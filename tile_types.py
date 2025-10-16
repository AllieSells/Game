from typing import Tuple

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
        ("lit", np.bool_),
        ("name", "U16"),
        ("walkable", np.bool_),
        ("transparent", np.bool_),
        ("dark", graphic_dt),  
        ("light", graphic_dt),
        ("interactable", np.bool_),
    ]
)

def new_tile(
        *,
        lit: bool = False,
        name: str = "<error>",
        walkable: int,
        transparent: int,
        dark: Tuple[int, Tuple[int, int, int], Tuple[int, int, int]],
        light: Tuple[int, Tuple[int, int, int], Tuple[int, int, int]],
        interactable: bool = False


) -> np.ndarray:
    return np.array((lit, name, walkable, transparent, dark, light, interactable), dtype=tile_dt)

SHROUD = np.array((ord(" "), (255, 255, 255), (10, 10, 10)), dtype=graphic_dt)

def random_floor_char() -> int:
    return ord(random.choice([" ", " ", " ", " ", " ", " ", ".", ",", "`"]))

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
    
wall = new_tile(
    name="Stone Wall",
    walkable=False,
    transparent=False,
    # Use darker greys for wall glyph foreground so the wall glyph appears less bright
    dark=(ord("░"), (60, 60, 60), (15, 15, 15)),
    # Make wall foreground/background a bit whiter when lit to increase contrast
    light=(ord("░"), (200, 200, 200), (60, 60, 60)),
)
down_stairs = new_tile(
    name="Down Stairs",
    walkable=True,
    transparent=True,
    dark=(ord(">"), (0, 0, 100), (50, 50, 150)),
    light=(ord(">"), (255, 255, 255), (200, 180, 50)),
)
closed_door = new_tile(
    name="Closed Door",
    walkable=False,
    transparent=False,
    dark=(ord("+"), (60, 60, 60), (15, 15, 15)),
    light=(ord("+"), (255, 212, 0), (89, 52, 28)),
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
