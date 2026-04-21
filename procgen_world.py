"""
procgen_world.py - Overworld map generation.
Separated from procgen.py so dungeon and world generation stay independent.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Tuple

import numpy as np
import tcod
import tcod.noise

import tile_types
from game_map import GameMap

import sprite_manager

if TYPE_CHECKING:
    from engine import Engine

from setup_game import _current_seed

def generate_world(
        map_width: int,
        map_height: int,
        engine: "Engine",
        noise_vals: Tuple,
        player_proxy=None,
) -> GameMap:
    """Worldmap generator - a continent floating in deep ocean.

    All generation constants are at the top of this function.
    Edit them freely to change the look of the world.
    """
    # ── Elevation (land vs water) ──────────────────────────────────────────
    ELEV_SCALE        = 0.06   # base frequency (lower = larger continents)
    ELEV_OCT2_SCALE   = 2.5    # 2nd octave frequency multiplier
    ELEV_OCT2_WEIGHT  = 0.45   # blend weight of 2nd octave
    CONTINENT_FALLOFF = 2.8    # higher = smaller landmass

    DEEP_OCEAN_THRESHOLD = -0.65   # elevation below this = deep ocean
    OCEAN_THRESHOLD      = -0.30   # elevation below this = shallow ocean

    BIOME_SCALE = 0.2   # lower = larger biome patches

    # Land biome bands: evaluated low-to-high on biome_noise value.
    # To add a new land biome, insert a (threshold, tile) tuple here.
    LAND_BANDS = [
        ( 0.10, tile_types.overworld_plains),
    ]
    DEFAULT_LAND_TILE = tile_types.overworld_forest

    MOUNTAIN_RANGES = 600    # ~ 1 mountain tile per N land tiles
    MOUNTAIN_COAST_BUFFER = 0.4  # elevation above OCEAN_THRESHOLD required for mountains
    MOUNTAIN_CLUSTER_COUNT = 4  # number of high-elevation cluster centres to attract ranges

    DUNGEON_DENSITY = 60   # ~1 dungeon entrance per N walkable tiles

    _placer = player_proxy if player_proxy is not None else engine.player

    seed = _current_seed if _current_seed is not None else 12345

    world = GameMap(
        engine, map_width, map_height, entities=[_placer],
        type="overworld", name="Overworld", sunlit=True, biome="overworld",
    )

    # ── Noise grids ────────────────────────────────────────────────────────
    elev_noise = tcod.noise.Noise(
        dimensions=2, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=seed + 10
    )
    biome_noise = tcod.noise.Noise(
        dimensions=2, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=seed + 33
    )

    xs = np.arange(map_width,  dtype=np.float32)
    ys = np.arange(map_height, dtype=np.float32)
    grid = np.stack(np.meshgrid(xs, ys, indexing="ij"), axis=0)  # (2, W, H)

    # Elevation: two-octave simplex + continent falloff
    e  = elev_noise.sample_mgrid(grid * ELEV_SCALE)
    e += elev_noise.sample_mgrid(grid * ELEV_SCALE * ELEV_OCT2_SCALE) * ELEV_OCT2_WEIGHT
    e /= (1.0 + ELEV_OCT2_WEIGHT)
    cx, cy = map_width / 2.0, map_height / 2.0
    dist_x = np.abs(xs - cx) / cx
    dist_y = np.abs(ys - cy) / cy
    e -= np.maximum(dist_x[:, None], dist_y[None, :]) ** CONTINENT_FALLOFF

    # Biome: single-octave simplex, no falloff — purely spatial, seed-independent of elevation
    b = biome_noise.sample_mgrid(grid * BIOME_SCALE)

    # ── Terrain assignment ─────────────────────────────────────────────────
    # Elevation determines land vs water; biome noise determines land tile type.
    for x in range(map_width):
        for y in range(map_height):
            ev = float(e[x, y])
            if ev < DEEP_OCEAN_THRESHOLD:
                world.tiles[x, y] = tile_types.overworld_deep_ocean
            elif ev < OCEAN_THRESHOLD:
                world.tiles[x, y] = tile_types.overworld_ocean
            else:
                bv = float(b[x, y])
                tile = DEFAULT_LAND_TILE
                for threshold, t in LAND_BANDS:
                    if bv < threshold:
                        tile = t
                        break
                world.tiles[x, y] = tile

    # ── Mountain generation ─────────────────────────────────────────────────
    land_coords = [(lx, ly) for lx in range(map_width) for ly in range(map_height)
                   if world.tiles[lx, ly]["walkable"]]
    num_mountains = max(1, len(land_coords) // MOUNTAIN_RANGES)
    rng = random.Random(seed + 99)

    # Collect elevation-eligible candidates (must sit well above sea level)
    eligible = [
        (lx, ly, float(e[lx, ly]))
        for lx, ly in land_coords
        if float(e[lx, ly]) >= OCEAN_THRESHOLD + MOUNTAIN_COAST_BUFFER
    ]

    if eligible:
        min_ev = min(ev for _, _, ev in eligible)
        max_ev = max(ev for _, _, ev in eligible)
        ev_span = max(max_ev - min_ev, 1e-6)

        # Pick cluster centres from the highest-elevation tiles
        top_n = max(MOUNTAIN_CLUSTER_COUNT, len(eligible) // 10)
        top_tiles = sorted(eligible, key=lambda t: t[2], reverse=True)[:top_n]
        centers = [
            (lx, ly) for lx, ly, _ in
            rng.sample(top_tiles, min(MOUNTAIN_CLUSTER_COUNT, len(top_tiles)))
        ]

        cand_xy = [(lx, ly) for lx, ly, _ in eligible]
        cand_w  = [
            ((ev - min_ev) / ev_span)
            * (1.0 / (1.0 + min(abs(lx - pcx) + abs(ly - pcy) for pcx, pcy in centers) * 0.15))
            for lx, ly, ev in eligible
        ]

        # Weighted sample (with replacement), deduplicate, sort back-to-front
        k = min(num_mountains * 8, len(cand_xy))
        raw_picks = rng.choices(range(len(cand_xy)), weights=cand_w, k=k)
        seen_i: set = set()
        pool: list = []
        for i in raw_picks:
            if i not in seen_i:
                seen_i.add(i)
                pool.append(cand_xy[i])

        pool.sort(key=lambda c: c[1])   # back-to-front for correct tile layering

        mountain_tiles: set = set()
        placed = 0
        for mx, my in pool:
            if placed >= num_mountains:
                break
            new_tiles = generate_range(world, mx, my, mountain_tiles)
            if new_tiles:
                mountain_tiles |= new_tiles
                placed += 1


    # ── Dungeon entrances ──────────────────────────────────────────────────
    rng = random.Random(seed)
    world.dungeon_entrances: dict[tuple, int] = {}
    candidates = [
        (x, y)
        for x in range(map_width)
        for y in range(map_height)
        if world.tiles[x, y]["walkable"]
        and str(world.tiles[x, y]["name"]) not in ("Ocean", "Deep Ocean")
    ]
    num_entrances = max(1, len(candidates) // DUNGEON_DENSITY)
    chosen = rng.sample(candidates, min(num_entrances, len(candidates)))
    for (x, y) in chosen:
        world.tiles[x, y] = tile_types.overworld_dungeon
        world.dungeon_entrances[(x, y)] = rng.randint(0, 2**31 - 1)

    # ── Spawn player near map centre on first walkable non-ocean tile ──────
    spawn_x, spawn_y = int(cx), int(cy)
    for r in range(max(map_width, map_height)):
        found = False
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if abs(dx) != r and abs(dy) != r:
                    continue
                nx, ny = int(cx) + dx, int(cy) + dy
                if not (0 <= nx < map_width and 0 <= ny < map_height):
                    continue
                name = str(world.tiles[nx, ny]["name"])
                if name in ("Plains", "Forest"):
                    spawn_x, spawn_y = nx, ny
                    found = True
                    break
            if found:
                break
        if found:
            break

    _placer.place(spawn_x, spawn_y, world)

    # ── Forest autotile pass ───────────────────────────────────────────────
    _apply_forest_autotile(world)

    return world


def _is_land(world, x, y):
    """Return True if (x, y) is in-bounds, walkable, and not ocean."""
    if x < 0 or x >= world.width or y < 0 or y >= world.height:
        return False
    tile = world.tiles[x, y]
    if not tile["walkable"]:
        return False
    name = str(tile["name"])
    return name not in ("Ocean", "Deep Ocean")


def _is_ocean_or_oob(world, x, y):
    """Return True if (x, y) is out of bounds or an ocean tile.

    Used for the ridge coast-proximity check so that previously placed
    mountain tiles (walkable=False) don't falsely terminate a new ridge.
    """
    if x < 0 or x >= world.width or y < 0 or y >= world.height:
        return True
    name = str(world.tiles[x, y]["name"])
    return name in ("Ocean", "Deep Ocean")


def _apply_forest_autotile(world) -> None:
    """Replace every Forest tile with the correct 3x3 autotile variant,
    composited over the plains biome sprite underneath.

    Adjacency rule:
      Row  – top: no N neighbor; mid: N+S neighbors; bot: no S neighbor
      Col  – center: has E neighbor; right: W but no E; left: neither E nor W
    """
    W, H = world.width, world.height
    # Collect forest positions first so adjacency reads are against the
    # original placement, not partially-updated results.
    forest_positions = [
        (x, y)
        for x in range(W)
        for y in range(H)
        if str(world.tiles[x, y]["name"]) == "Forest"
    ]

    plains_dark  = int(tile_types.overworld_plains["dark"]["ch"])
    plains_light = int(tile_types.overworld_plains["light"]["ch"])

    def _is_forest(x, y):
        if x < 0 or x >= W or y < 0 or y >= H:
            return False
        return str(world.tiles[x, y]["name"]) == "Forest"

    for x, y in forest_positions:
        has_N  = _is_forest(x,     y - 1)
        has_NE = _is_forest(x + 1, y - 1)
        has_E  = _is_forest(x + 1, y    )
        has_SE = _is_forest(x + 1, y + 1)
        has_S  = _is_forest(x,     y + 1)
        has_SW = _is_forest(x - 1, y + 1)
        has_W  = _is_forest(x - 1, y    )
        has_NW = _is_forest(x - 1, y - 1)
        variant = tile_types.get_forest_tile(
            has_N, has_NE, has_E, has_SE,
            has_S, has_SW, has_W, has_NW,
        )
        # N+S-only tile whose S neighbour is strip_n (has N only, no S/E/W)
        if has_N and has_S and not has_E and not has_W:
            if not _is_forest(x, y + 2) and not _is_forest(x + 1, y + 1) and not _is_forest(x - 1, y + 1):
                variant = tile_types.overworld_forest_ns_above_strip_n
        # S+E-only tile whose S neighbour is strip_n (has N only, no S/E/W)
        if has_S and has_E and not has_N and not has_W:
            if not _is_forest(x, y + 2) and not _is_forest(x + 1, y + 1) and not _is_forest(x - 1, y + 1):
                variant = tile_types.overworld_forest_ns_above_strip_n
        # S-only tile whose S neighbour is mid_right (N+S+W, no E) → 0xE16B
        if has_S and not has_N and not has_E and not has_W:
            if _is_forest(x, y + 2) and _is_forest(x - 1, y + 1) and not _is_forest(x + 1, y + 1):
                variant = tile_types.overworld_forest_ns_above_strip_n
        # N-only tile whose N neighbour is mid_right (N+S+W, no E) → 0xE16B
        if has_N and not has_S and not has_E and not has_W:
            if _is_forest(x, y - 2) and _is_forest(x - 1, y - 1) and not _is_forest(x + 1, y - 1):
                variant = tile_types.overworld_forest_ns_above_strip_n
        result = variant.copy()
        result["dark"]["ch"]  = ord(sprite_manager.compose_sprite(
            [plains_dark,  int(variant["dark"]["ch"])]
        ))
        result["light"]["ch"] = ord(sprite_manager.compose_sprite(
            [plains_light, int(variant["light"]["ch"])]
        ))
        world.tiles[x, y] = result


# Tile names that mountains composite cleanly against.
# Any other biome is replaced with plains before compositing.
_MOUNTAIN_MERGE_ALLOWED = {"Plains"}


def _mountain_on_biome(world, mx, my, mountain_tile, biome_cache):
    """Composite a mountain tile on top of the biome tile at (mx, my).

    Uses biome_cache to remember the original biome codepoint so that
    re-placements (e.g. subpeak overwriting flat_end) still composite
    against the original biome, not a previously composed mountain.

    If the underlying tile is not in _MOUNTAIN_MERGE_ALLOWED (e.g. Forest)
    it is first replaced with overworld_plains so the merge looks correct.
    """
    if (mx, my) not in biome_cache:
        # Normalise to a merge-friendly tile if needed.
        tile_name = str(world.tiles[mx, my]["name"])
        if tile_name not in _MOUNTAIN_MERGE_ALLOWED:
            world.tiles[mx, my] = tile_types.overworld_plains
        biome_cache[(mx, my)] = (
            int(world.tiles[mx, my]["dark"]["ch"]),
            int(world.tiles[mx, my]["light"]["ch"]),
        )
    biome_dark, biome_light = biome_cache[(mx, my)]
    result = mountain_tile.copy()
    result["dark"]["ch"] = ord(sprite_manager.compose_sprite(
        [biome_dark, int(mountain_tile["dark"]["ch"])]
    ))
    result["light"]["ch"] = ord(sprite_manager.compose_sprite(
        [biome_light, int(mountain_tile["light"]["ch"])]
    ))
    world.tiles[mx, my] = result


def generate_range(world, x, y, mountain_tiles=None):
    """Place a single mountain ridge, avoiding overlap with existing mountain tiles.

    Returns the set of tile positions placed, or an empty set if the ridge
    would overlap mountain_tiles.  Caller should union the result into its
    global mountain_tiles tracker.
    """
    if mountain_tiles is None:
        mountain_tiles = set()

    length = random.randint(4, 10)
    segments = []
    merges = []
    cx = x
    preferred_dir = random.choice([-1, 1])

    for i in range(length):
        ty = y + i
        if not _is_land(world, cx, ty):
            break
        # Stop only if near ocean/OOB — don't stop for neighbouring mountain tiles
        if any(_is_ocean_or_oob(world, cx + dx, ty + dy)
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            break
        if i == 0:
            segments.append((cx, ty, 'peak'))
        elif i == 1:
            segments.append((cx, ty, 'ridge'))
        else:
            curv_dir = random.choices(
                [preferred_dir, -preferred_dir, 0],
                weights=[0.75, 0.25, 0.25],
            )[0]
            if curv_dir == 1:
                new_cx = cx + 1
                if _is_land(world, new_cx, ty):
                    segments.append((cx, ty, 'ridge_curve_e'))
                    merges.append((new_cx, ty, 'ridge_curve_e_merge'))
                    cx = new_cx
                else:
                    segments.append((cx, ty, 'ridge'))
            elif curv_dir == -1:
                new_cx = cx - 1
                if _is_land(world, new_cx, ty):
                    segments.append((cx, ty, 'ridge_curve_w'))
                    merges.append((new_cx, ty, 'ridge_curve_w_merge'))
                    cx = new_cx
                else:
                    segments.append((cx, ty, 'ridge'))
            else:
                segments.append((cx, ty, 'ridge'))

    if not segments:
        return set()

    # Cleanup: straighten last curve, prune orphan merges, add end cap
    last_x, last_y, last_key = segments[-1]
    if last_key in ('ridge_curve_e', 'ridge_curve_w'):
        segments[-1] = (last_x, last_y, 'ridge')
    final_y = segments[-1][1]
    merges = [(mx, my, mk) for mx, my, mk in merges if my != final_y]
    end_x, end_y = segments[-1][0], segments[-1][1] + 1
    if _is_land(world, end_x, end_y) and (end_x, end_y) not in {(rx, ry) for rx, ry, _ in segments}:
        segments.append((end_x, end_y, 'end'))

    # ── Overlap check ─────────────────────────────────────────────────────
    # Reject the range if its spine or immediate slope columns (±1) would
    # touch any tile already occupied by another range.  End-cap tiles are
    # excluded — touching ends is acceptable.
    for rx, ry, key in segments + merges:
        if key == 'end':
            continue
        if (rx, ry) in mountain_tiles or (rx - 1, ry) in mountain_tiles or (rx + 1, ry) in mountain_tiles:
            return set()

    # ── Placement ─────────────────────────────────────────────────────────
    placed_tiles: set = set()
    biome_cache: dict = {}

    ridge_set = (
        {(rx, ry) for rx, ry, _ in segments} |
        {(rx, ry) for rx, ry, _ in merges}
    )

    tile_map = {
        'peak':                tile_types.mountain_peak,
        'ridge':               tile_types.mountain_ridge,
        'ridge_curve_e':       tile_types.mountain_ridge_curve_e,
        'ridge_curve_w':       tile_types.mountain_ridge_curve_w,
        'ridge_curve_e_merge': tile_types.mountain_ridge_curve_e_merge,
        'ridge_curve_w_merge': tile_types.mountain_ridge_curve_w_merge,
        'end':                 tile_types.mountain_end,
    }

    for rx, ry, key in segments + merges:
        _mountain_on_biome(world, rx, ry, tile_map[key], biome_cache)
        placed_tiles.add((rx, ry))

    # Corner pieces flanking the end cap; skip if occupied by another range
    for ex, ey, _ in [(rx, ry, key) for rx, ry, key in segments if key == 'end']:
        if _is_land(world, ex - 1, ey) and (ex - 1, ey) not in ridge_set and (ex - 1, ey) not in mountain_tiles:
            _mountain_on_biome(world, ex - 1, ey, tile_types.mountain_corner_slope_end_w, biome_cache)
            placed_tiles.add((ex - 1, ey))
            ridge_set.add((ex - 1, ey))
        if _is_land(world, ex + 1, ey) and (ex + 1, ey) not in ridge_set and (ex + 1, ey) not in mountain_tiles:
            _mountain_on_biome(world, ex + 1, ey, tile_types.mountain_corner_slope_end_e, biome_cache)
            placed_tiles.add((ex + 1, ey))
            ridge_set.add((ex + 1, ey))

    # all_mountain: this ridge's tiles + globally placed tiles (prevents slopes
    # from this range overwriting tiles from previously placed ranges)
    all_mountain = set(ridge_set) | mountain_tiles

    # --- Western side fill ---
    ridge_positions = {(rx, ry) for rx, ry, key in segments[1:] + merges if key != 'end'}
    peak_positions  = {(rx, ry) for rx, ry, key in segments if key == 'peak'}
    end_positions   = {(rx, ry) for rx, ry, key in segments if key == 'end'}

    for px, py in peak_positions:
        bw_x, bw_y = px - 1, py + 1
        if (bw_x, bw_y) not in all_mountain and _is_land(world, bw_x, bw_y):
            _mountain_on_biome(world, bw_x, bw_y, tile_types.mountain_slope_w, biome_cache)
            placed_tiles.add((bw_x, bw_y))
            all_mountain.add((bw_x, bw_y))

    west_border = set()
    west_flat_ends = set()
    for rx, ry in ridge_positions:
        wx = rx - 1
        if (wx, ry) in all_mountain or not _is_land(world, wx, ry):
            continue
        has_ridge_above = (rx, ry - 1) in ridge_positions or (rx, ry - 1) in peak_positions
        has_ridge_below = (rx, ry + 1) in ridge_positions or (rx, ry + 1) in end_positions
        if not has_ridge_above and has_ridge_below:
            _mountain_on_biome(world, wx, ry, tile_types.mountain_slope_w, biome_cache)
        elif has_ridge_above and not has_ridge_below:
            _mountain_on_biome(world, wx, ry, tile_types.mountain_corner_slope_end_w, biome_cache)
        else:
            _mountain_on_biome(world, wx, ry, tile_types.mountain_slope_flat_end_w, biome_cache)
            west_flat_ends.add((wx, ry))
        west_border.add((wx, ry))
        placed_tiles.add((wx, ry))

    all_mountain |= west_border

    # Western subpeaks
    for wx, wy in list(west_flat_ends):
        if random.random() > 0.25:
            continue
        cap_x, cap_y = wx, wy - 1
        ext_x = wx - 1
        if (cap_x, cap_y) in all_mountain or not _is_land(world, cap_x, cap_y):
            continue
        if (ext_x, wy) in all_mountain or not _is_land(world, ext_x, wy):
            continue
        _mountain_on_biome(world, wx, wy, tile_types.mountain_subpeak_base, biome_cache)
        _mountain_on_biome(world, cap_x, cap_y, tile_types.mountain_subpeak_cap, biome_cache)
        placed_tiles.update([(wx, wy), (cap_x, cap_y)])
        all_mountain.add((cap_x, cap_y))
        _mountain_on_biome(world, ext_x, wy, tile_types.mountain_slope_flat_end_w, biome_cache)
        placed_tiles.add((ext_x, wy))
        all_mountain.add((ext_x, wy))
        bex, bey = ext_x, wy + 1
        if _is_land(world, bex, bey) and (bex, bey) not in all_mountain:
            _mountain_on_biome(world, bex, bey, tile_types.mountain_corner_slope_end_w, biome_cache)
            placed_tiles.add((bex, bey))
            all_mountain.add((bex, bey))

    # --- Eastern side fill ---
    for px, py in peak_positions:
        be_x, be_y = px + 1, py + 1
        if (be_x, be_y) not in all_mountain and _is_land(world, be_x, be_y):
            _mountain_on_biome(world, be_x, be_y, tile_types.mountain_slope_e, biome_cache)
            placed_tiles.add((be_x, be_y))
            all_mountain.add((be_x, be_y))

    east_border = set()
    for rx, ry in ridge_positions:
        ex = rx + 1
        if (ex, ry) in all_mountain or not _is_land(world, ex, ry):
            continue
        has_ridge_above = (rx, ry - 1) in ridge_positions or (rx, ry - 1) in peak_positions
        has_ridge_below = (rx, ry + 1) in ridge_positions or (rx, ry + 1) in end_positions
        if not has_ridge_above and has_ridge_below:
            _mountain_on_biome(world, ex, ry, tile_types.mountain_slope_e, biome_cache)
        elif has_ridge_above and not has_ridge_below:
            _mountain_on_biome(world, ex, ry, tile_types.mountain_corner_slope_end_e, biome_cache)
        else:
            _mountain_on_biome(world, ex, ry, tile_types.mountain_slope_flat_end_e, biome_cache)
        east_border.add((ex, ry))
        placed_tiles.add((ex, ry))

    all_mountain |= east_border

    # --- Foothills (southern base scatter) ---
    # Build south_base only from THIS range's placed_tiles so previous ranges
    # don't pollute the candidate rows.  For each x-column, find the
    # southernmost tile placed by this call and scatter foothills one row below.
    south_base: dict = {}
    for fhx, fhy in placed_tiles:
        if fhx not in south_base or fhy > south_base[fhx]:
            south_base[fhx] = fhy

    foothill_placed: set = set()   # track within this loop to handle L/R pairs

    for fhx in sorted(south_base):
        fhy = south_base[fhx] + 1
        # Skip if already filled by mountain or foothill, out of bounds, or not open land
        if (fhx, fhy) in all_mountain or (fhx, fhy) in foothill_placed:
            continue
        if not (0 <= fhx < world.width and 0 <= fhy < world.height):
            continue
        tile_name = str(world.tiles[fhx, fhy]["name"])
        if tile_name in ("Ocean", "Deep Ocean", "Mountain", "Foothill"):
            continue

        roll = random.random()
        fh_rx = fhx + 1

        # ~30% chance: try L/R pair first
        if roll < 0.30:
            right_ok = (
                (fh_rx, fhy) not in all_mountain
                and (fh_rx, fhy) not in foothill_placed
                and 0 <= fh_rx < world.width
                and str(world.tiles[fh_rx, fhy]["name"]) not in ("Ocean", "Deep Ocean", "Mountain", "Foothill")
                and south_base.get(fh_rx, -999) + 1 == fhy
            )
            if right_ok:
                _mountain_on_biome(world, fhx,   fhy, tile_types.mountain_foothill_L, biome_cache)
                _mountain_on_biome(world, fh_rx, fhy, tile_types.mountain_foothill_R, biome_cache)
                placed_tiles.update([(fhx, fhy), (fh_rx, fhy)])
                foothill_placed.update([(fhx, fhy), (fh_rx, fhy)])
                continue
            # Pair blocked — fall through to single

        # ~45% chance: single foothill (covers original 30% + fallthrough from pair)
        if roll < 0.75:
            _mountain_on_biome(world, fhx, fhy, tile_types.mountain_foothill, biome_cache)
            placed_tiles.add((fhx, fhy))
            foothill_placed.add((fhx, fhy))
        # else: empty gap (~25%)

    return placed_tiles


