from typing import Tuple

import numpy as np

graphic_dt = np.dtype(
    [
        ("ch", np.int32),  
        ("fg", "3B"),      
        ("bg", "3B"),
    ]
)

tile_dt = np.dtype(
    [
        ("walkable", np.bool_),
        ("transparent", np.bool_),
        ("dark", graphic_dt),  
        ("light", graphic_dt),
    ]
)

def new_tile(
        *,
        walkable: int,
        transparent: int,
        dark: Tuple[int, Tuple[int, int, int], Tuple[int, int, int]],
        light: Tuple[int, Tuple[int, int, int], Tuple[int, int, int]],


) -> np.ndarray:
    return np.array((walkable, transparent, dark, light), dtype=tile_dt)

SHROUD = np.array((ord(" "), (255, 255, 255), (10, 10, 10)), dtype=graphic_dt)

floor = new_tile(
    walkable=True,
    transparent=True,
    # Dark = much darker grey, Light = darker grey for lit floors
    dark=(ord(" "), (255, 255, 255), (25, 25, 25)),
    light=(ord(" "), (255, 255, 255), (80, 80, 80)),
)
wall = new_tile(
    walkable=False,
    transparent=False,
    # Use darker greys for wall glyph foreground so the wall glyph appears less bright
    dark=(ord("░"), (60, 60, 60), (15, 15, 15)),
    # Make wall foreground/background a bit whiter when lit to increase contrast
    light=(ord("░"), (200, 200, 200), (60, 60, 60)),
)
down_stairs = new_tile(
    walkable=True,
    transparent=True,
    dark=(ord(">"), (0, 0, 100), (50, 50, 150)),
    light=(ord(">"), (255, 255, 255), (200, 180, 50)),
)
closed_door = new_tile(
    walkable=False,
    transparent=False,
    dark=(ord("+"), (255, 255, 0), (50, 20, 0)),
    light=(ord("+"), (255, 255, 0), (200, 180, 50)),
)
open_door = new_tile(
    walkable=True,
    transparent=True,
    dark=(ord("/"), (255, 255, 0), (50, 20, 0)),
    light=(ord("/"), (255, 255, 0), (200, 180, 50)),
)
