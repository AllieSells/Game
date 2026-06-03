CAN_BE_MOSSY = {
    "horizontal",
    "t_down",
    "top_left",
    "top_right",
}
import sprite_manager

def icify_wall_tile(tile):
    # Merge allowable wall types with ice texture
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
        ice_cp = 0xE11E
        # compose_sprite returns a character
        if tile["direction"] == "horizontal":
            x_offset = 2
            ice_cp = 0xE11F
        elif tile["direction"] == "t_down":
            x_offset = 2
        elif tile["direction"] == "top_left":
            x_offset = 4
        elif tile["direction"] == "top_right":
            x_offset = 0
        # compose_sprite returns a character
        new_ch = sprite_manager.compose_sprite([base_cp, ice_cp], x_offset=x_offset, y_offset=0, layer_tints=[None, (225, 255, 255)])
        # Match the type of the original field
        if isinstance(ch, str):
            new_tile[variant]["ch"] = new_ch
        else:
            new_tile[variant]["ch"] = ord(new_ch)
    return new_tile

def icify_floor_tile(tile):
    """Composite an icy overlay onto a floor tile."""
    # Copy the tile to avoid mutating the original
    new_tile = tile.copy()
    ice_tint = (225, 255, 255)  # Light blue tint for ice
    
    for variant in ("dark", "light"):
        ch = tile[variant]["ch"]
        if isinstance(ch, str):
            base_cp = ord(ch)
        else:
            base_cp = int(ch)
        
        # Composite with ice overlay sprite (same as walls use)
        ice_cp = 0xE11E
        new_ch = sprite_manager.compose_sprite(
            [base_cp, base_cp], 
            x_offset=0, 
            y_offset=0, 
            layer_tints=[None, ice_tint]
        )
        
        # Match the type of the original field
        if isinstance(ch, str):
            new_tile[variant]["ch"] = new_ch
        else:
            new_tile[variant]["ch"] = ord(new_ch)
    
    # Update name to indicate it's icy
    original_name = str(tile["name"])
    if "Icy" not in original_name and "Ice" not in original_name:
        new_tile["name"] = f"Icy {original_name}"
    
    return new_tile

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

def random_statue():
    statues_cp = random.choice(range(0xE004, 0xE008))
    return new_tile(
        name="Statue",
        walkable=False,
        transparent=False,
        dark=(statues_cp, (60, 60, 60), (25, 25, 25)),
        light=(statues_cp, (255, 255, 255), (80, 80, 80)),
    )


def random_mossy_floor_tile():
    floor_cp = random.choice(range(0xE1E0, 0xE1E7))
    moss_cp = random.choice([0xE12C, 0xE12D, 0xE12E, 0xE12F])
    composed = ord(sprite_manager.compose_sprite([floor_cp, moss_cp]))
    return new_tile(
        name="Mossy Floor",
        walkable=True,
        transparent=True,
        dark=(composed, (255, 255, 255), (25, 25, 25)),
        light=(composed, (255, 255, 255), (80, 80, 80)),
    )

def random_icy_floor_tile():
    floor_cp = random.choice(range(0xE1E0, 0xE1E7))
    return new_tile(
        name="Icy Floor",
        walkable=True,
        transparent=True,
        dark=(floor_cp, (210, 255, 255), (20, 20, 20)),
        light=(floor_cp, (210, 255, 255), (60, 60, 60)),
    )


def random_floor_tile():
    char = random.choice(range(0xE1E0, 0xE1E7))  # 0xE1E0–0xE1E6 (7 variants, row 30 col 0-6)
    return new_tile(
        name="Floor",
        walkable=True,
        transparent=True,
        dark=(char, (255, 255, 255), (25, 25, 25)),
        light=(char, (255, 255, 255), (80, 80, 80)),
    )

floor = random_floor_tile()

wooden_floor = new_tile(
    name="Wooden Floor",
    walkable=True,
    transparent=True,
    # Yellowish brown
    dark=(0xE14A, (255, 255, 255), (20, 20, 20)),
    light=(0xE14A, (255, 255, 255), (102, 57, 49)),
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

func_light = new_tile(
    name="Functional Light",
    walkable=True,
    transparent=True,
    dark=(0xE18B, (255, 255, 255), (50, 50, 50)),
    light=(0xE18B, (255, 255, 255), (200, 200, 200)),
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
    # Different border for worldmap
    dark=(ord("▓"), (0, 0, 0), (0, 0, 0)),
    light=(ord("▓"), (0, 0, 0), (0, 0, 0)),
)


overworld_deep_ocean = new_tile(
    name="Deep Ocean",
    walkable=False,
    transparent=True,
    dark=(0xE140, (90, 90, 90), (10, 10, 10)),
    light=(0xE140, (255, 255, 255), (30, 110, 135)),
)


overworld_plains = new_tile(
    name="Plains",
    walkable=True,
    transparent=True,
    dark=(0xE150, (40, 90, 40), (20, 50, 20)),
    light=(0xE150, (255, 255, 255), (30, 80, 30)),
)

overworld_desert = new_tile(
    name="Desert",
    walkable=True,
    transparent=True,
    dark=(0xE15C, (160, 150, 100), (80, 70, 40)),
    light=(0xE15C, (255, 255, 255), (180, 160, 90)),
)

# ── Forest autotile – 9-tile 3×3 set ──────────────────────────────────────
# Fill in the correct codepoint for each of the 9 tiles below.
_F = dict(name="Forest", walkable=True, transparent=True)
_FG = ((30, 60, 30), (15, 30, 15))
_FL = ((255, 255, 255), (20, 50, 20))
def _ft(cp): return new_tile(**_F, dark=(cp, *_FG), light=(cp, *_FL))

overworld_forest_top_left        = _ft(0xE151)  # no N, has S+E
overworld_forest_top_center      = _ft(0xE152)  # no N, has S+E+W
overworld_forest_top_right       = _ft(0xE153)  # no N, has S+W
overworld_forest_mid_left        = _ft(0xE154)  # has N+S+E, no W
overworld_forest_mid_center      = _ft(0xE155)  # has all four cardinals
overworld_forest_center_no_nw    = _ft(0xE15A)  # all four cardinals, NW missing
overworld_forest_center_no_se    = _ft(0xE15B)  # all four cardinals, SE missing
overworld_forest_mid_right       = _ft(0xE156)  # has N+S+W, no E
overworld_forest_bot_left        = _ft(0xE157)  # has N+E, no S
overworld_forest_bot_center      = _ft(0xE158)  # has N+E+W, no S
overworld_forest_bot_right       = _ft(0xE159)  # has N+W, no S

# Marker tile for initial terrain assignment; replaced by the autotile pass.
overworld_forest = overworld_forest_mid_center

# LUT: all 9 valid cardinal combos (erosion guarantees only these occur).
_FOREST_AUTOTILE = {
    # (  N      S      E      W   )
    (False, True,  True,  False): overworld_forest_top_left,
    (False, True,  True,  True ): overworld_forest_top_center,
    (False, True,  False, True ): overworld_forest_top_right,
    (True,  True,  True,  False): overworld_forest_mid_left,
    (True,  True,  True,  True ): overworld_forest_mid_center,
    (True,  True,  False, True ): overworld_forest_mid_right,
    (True,  False, True,  False): overworld_forest_bot_left,
    (True,  False, True,  True ): overworld_forest_bot_center,
    (True,  False, False, True ): overworld_forest_bot_right,
}

def get_forest_tile(
    has_N: bool, has_NE: bool, has_E: bool, has_SE: bool,
    has_S: bool, has_SW: bool, has_W: bool, has_NW: bool,
) -> object:
    """Return the correct 9-tile autotile variant.
    Erosion guarantees only valid combos reach here.
    When all four cardinals are present, NW and SE diagonals select inner-corner variants."""
    if has_N and has_S and has_E and has_W:
        if not has_NW:
            return overworld_forest_center_no_nw
        if not has_SE:
            return overworld_forest_center_no_se
    return _FOREST_AUTOTILE[(has_N, has_S, has_E, has_W)]

overworld_ocean = new_tile(
    name="Ocean",
    walkable=False,
    transparent=True,
    dark=(0xE140, (90, 90, 90), (10, 10, 10)),
    light=(0xE140, (255, 255, 255), (30, 110, 135)),
)

overworld_river = new_tile(
    name="River",
    walkable=True,
    transparent=True,
    dark=(0xE140, (100, 110, 120), (20, 40, 60)),
    light=(0xE140, (255, 255, 255), (60, 170, 210)),
)

overworld_beach = new_tile(
    name="Beach",
    walkable=True,
    transparent=True,
    dark=(0xE15C, (160, 150, 100), (80, 70, 40)),
    light=(0xE15C, (255, 255, 255), (180, 160, 90)),
)

overworld_road = new_tile(
    name="Road",
    walkable=True,
    transparent=True,
    dark=(0xE15C, (100, 80, 55), (50, 38, 22)),
    light=(0xE15C, (180, 145, 95), (110, 85, 50)),
)

# Shore tiles sit at the water's edge; visually ocean but named "Shore"
# so the beach water animation can target them exactly.
overworld_shore = new_tile(
    name="Shore",
    walkable=False,
    transparent=True,
    dark=(0xE140, (90, 90, 90), (10, 10, 10)),
    light=(0xE140, (255, 255, 255), (30, 110, 135)),
)

# Grass-edge overlays composited onto beach tiles that touch land.
# Each sprite shows grass bleeding in from that cardinal direction.
_beach_grass_N = 0xE168
_beach_grass_S = 0xE169
_beach_grass_E = 0xE16B
_beach_grass_W = 0xE16A# Corner overlays (composited under cardinal overlays) for two adjacent grass cardinals.
_beach_grass_SW = 0xE16C
_beach_grass_SE = 0xE16D
_beach_grass_NE = 0xE16E
_beach_grass_NW = 0xE16F

# Sand-edge overlays composited onto beach/desert tiles that touch a river.
_river_sand_N = 0xE187
_river_sand_S = 0xE188
_river_sand_W = 0xE189
_river_sand_E = 0xE18A

# Dungeon water-edge overlays composited onto floor tiles that border a water pool.
_dungeon_water_S  = 0xE18B  # CP18B — water touching bottom
_dungeon_water_N  = 0xE18C  # CP18C — water touching top
_dungeon_water_W  = 0xE18D  # CP18D — water touching left
_dungeon_water_E  = 0xE18E  # CP18E — water touching right
# Corner overlays for floor tiles that only touch water diagonally (outer pool corners).
# CP1E0–CP1E3 immediately follow the beach-water animation range (0xE190–0xE1DF).
_dungeon_water_SW = 0xE1E0  # CP1E0 — water to south-west
_dungeon_water_SE = 0xE1E1  # CP1E1 — water to south-east
_dungeon_water_NW = 0xE1E2  # CP1E2 — water to north-west
_dungeon_water_NE = 0xE1E3  # CP1E3 — water to north-east


tutorial_house = new_tile(
    name="Home",
    walkable=True,
    transparent=True,
    dark=(0xE14F, (100, 60, 20), (30, 15, 5)),
    light=(0xE14F, (225, 255, 255), (60, 30, 10))
)

overworld_dungeon = new_tile(
    name="Dungeon Entrance",
    walkable=True,
    transparent=True,
    dark=(0xE14D, (100, 60, 20), (30, 15, 5)),
    light=(0xE14D, (225, 255, 255), (60, 30, 10)),
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


window = new_tile(
    name="Window",
    walkable=False,
    transparent=False,
    dark=(0xE14C, (60, 60, 60), (15, 15, 15)),
    light=(0xE14C, (255, 255, 255), (0, 0, 0)),
    interactable=False # For now
)

locked_door = new_tile(
    name="Locked Door",
    walkable=False,
    transparent=False,
    dark=(0xE14B, (60, 60, 60), (15, 15, 15)),
    light=(0xE14B, (255, 255, 255), (0, 0, 0)),
    interactable=True
)

dungeon_exit = new_tile(
    name="Dungeon Exit",
    walkable=True,
    transparent=False,
    dark=(0xE14E, (60, 60, 60), (15, 15, 15)),
    light=(0xE14E, (255, 255, 255), (0, 0, 0)),
    interactable=False
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


# Mountain tiles
mountain_isolated = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(ord('^'), (150, 155, 165), (22, 25, 32)),
    light=(ord('^'), (255, 255, 225), (75, 82, 97)),
)

# Two-stage mountain: core + directional slope chains.
# ASCII placeholders — swap the codepoints for sprites later.
mountain_peak = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE170, (150, 155, 165), (22, 25, 32)),
    light=(0xE170, (255, 255, 255), (75, 82, 97)),
)

mountain_ridge = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE171, (150, 155, 165), (22, 25, 32)),
    light=(0xE171, (255, 255, 255), (75, 82, 97)),
)

mountain_slope_e = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE173, (150, 155, 165), (22, 25, 32)),
    light=(0xE173, (255, 255, 255), (75, 82, 97)),
)

mountain_slope_w = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE172, (150, 155, 165), (22, 25, 32)),
    light=(0xE172, (255, 255, 255), (75, 82, 97)),
)

mountain_large_slope_w = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE174, (150, 155, 165), (22, 25, 32)),
    light=(0xE174, (255, 255, 255), (75, 82, 97)),
)

mountain_large_slope_e = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE175, (150, 155, 165), (22, 25, 32)),
    light=(0xE175, (255, 255, 255), (75, 82, 97)),
)

mountain_ridge_curve_w = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE176, (150, 155, 165), (22, 25, 32)),
    light=(0xE176, (255, 255, 255), (75, 82, 97)),
)

mountain_ridge_curve_e = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE178, (150, 155, 165), (22, 25, 32)),
    light=(0xE178, (255, 255, 255), (75, 82, 97)),
)

mountain_ridge_curve_w_merge = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE17D, (150, 155, 165), (22, 25, 32)),
    light=(0xE17D, (255, 255, 255), (75, 82, 97)),
)

mountain_ridge_curve_e_merge = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE17A, (150, 155, 165), (22, 25, 32)),
    light=(0xE17A, (255, 255, 255), (75, 82, 97)),
)

mountain_straight_valley = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE17E, (150, 155, 165), (22, 25, 32)),
    light=(0xE17E, (255, 255, 255), (75, 82, 97)),
)

mountain_slope_end_s = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE177, (150, 155, 165), (22, 25, 32)),
    light=(0xE177, (255, 255, 255), (75, 82, 97)),
)

mountain_peak_isolated = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE179, (150, 155, 165), (22, 25, 32)),
    light=(0xE179, (255, 255, 255), (75, 82, 97)),
)


mountain_slope_flat_end_e = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE17B, (150, 155, 165), (22, 25, 32)),
    light=(0xE17B, (255, 255, 255), (75, 82, 97)),
)

mountain_slope_flat_end_w = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE17C, (150, 155, 165), (22, 25, 32)),
    light=(0xE17C, (255, 255, 255), (75, 82, 97)),
)

mountain_corner_slope_end_w = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE17F, (150, 155, 165), (22, 25, 32)),
    light=(0xE17F, (255, 255, 255), (75, 82, 97)),
)

mountain_corner_slope_end_e = new_tile(
    name = "Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE180, (150, 155, 165), (22, 25, 32)),
    light=(0xE180, (255, 255, 255), (75, 82, 97)),
)

mountain_end = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE181, (150, 155, 165), (22, 25, 32)),
    light=(0xE181, (255, 255, 255), (75, 82, 97)),
)

mountain_subpeak_base = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE182, (150, 155, 165), (22, 25, 32)),
    light=(0xE182, (255, 255, 255), (75, 82, 97)),
)

mountain_subpeak_cap = new_tile(
    name="Mountain",
    walkable=False,
    transparent=True,
    dark=(0xE183, (150, 155, 165), (22, 25, 32)),
    light=(0xE183, (255, 255, 255), (75, 82, 97)),
)

mountain_foothill = new_tile(
    name="Foothill",
    walkable=True,
    transparent=True,
    dark=(0xE184, (150, 155, 165), (22, 25, 32)),
    light=(0xE184, (255, 255, 255), (75, 82, 97)),
)

mountain_foothill_L = new_tile(
    name="Foothill",
    walkable=True,
    transparent=True,
    dark=(0xE185, (150, 155, 165), (22, 25, 32)),
    light=(0xE185, (255, 255, 255), (75, 82, 97)),
)

mountain_foothill_R = new_tile(
    name="Foothill",
    walkable=True,
    transparent=True,
    dark=(0xE186, (150, 155, 165), (22, 25, 32)),
    light=(0xE186, (255, 255, 255), (75, 82, 97)),
)

