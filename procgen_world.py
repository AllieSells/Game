"""
procgen_world.py - Overworld map generation.
Separated from procgen.py so dungeon and world generation stay independent.
"""
from __future__ import annotations

import random
from collections import deque
from typing import TYPE_CHECKING, Tuple

import numpy as np
import tcod
import tcod.noise

import tile_types
from game_map import GameMap

import sprite_manager

if TYPE_CHECKING:
    from engine import Engine

import setup_game as _setup_game

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
    ELEV_SCALE        = 0.02   # base frequency (lower = larger continents)
    ELEV_OCT2_SCALE   = 2.5    # 2nd octave frequency multiplier
    ELEV_OCT2_WEIGHT  = 0.45   # blend weight of 2nd octave

    # Domain-warp radial falloff (replaces Chebyshev square falloff)
    WARP_SCALE        = 0.009   # warp noise frequency
    WARP_STRENGTH     = 0.60    # warp amplitude — only warps noise sampling, not falloff
    LAND_RADIUS       = 0.80    # unwarped falloff start; continent fills ~80% of half-map
    LAND_TRANSITION   = 0.22    # falloff width; edge midpoints (dist=1.0) always deep ocean
    LAND_FALLOFF_AMP  = 2.4     # ensures edges are crushed to deep ocean

    DEEP_OCEAN_THRESHOLD = -0.55   # elevation below this = deep ocean
    OCEAN_THRESHOLD      = -0.18   # elevation below this = shallow ocean

    BIOME_SCALE  = 0.13   # lower = larger forest/plains patches
    DESERT_SCALE = 0.11   # lower = larger desert patches

    # Independent biome thresholds (each on its own noise axis)
    FOREST_THRESHOLD = 0.20   # biome_noise above this → forest, else plains
    DESERT_THRESHOLD = 0.35   # desert_noise above this → desert (overrides plains, not forest)

    MOUNTAIN_RANGES = 350    # ~ 1 mountain tile per N land tiles
    MOUNTAIN_COAST_BUFFER = 0.4  # elevation above OCEAN_THRESHOLD required for mountains
    MOUNTAIN_CLUSTER_COUNT = 4  # number of high-elevation cluster centres to attract ranges
    MOUNTAIN_PLAINS_RADIUS = 5  # desert tiles within this Chebyshev radius become plains

    DUNGEON_DENSITY = 60   # ~1 dungeon entrance per N walkable tiles
    RIVER_COUNT = 8         # number of rivers to attempt to carve

    _placer = player_proxy if player_proxy is not None else engine.player

    seed = _setup_game._current_seed if _setup_game._current_seed is not None else random.randint(0, 2**31 - 1)

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
    desert_noise = tcod.noise.Noise(
        dimensions=2, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=seed + 57
    )
    warp_noise = tcod.noise.Noise(
        dimensions=2, algorithm=tcod.noise.Algorithm.SIMPLEX, seed=seed + 71
    )

    xs = np.arange(map_width,  dtype=np.float32)
    ys = np.arange(map_height, dtype=np.float32)
    grid = np.stack(np.meshgrid(xs, ys, indexing="ij"), axis=0)  # (2, W, H)

    # Domain warp: displace sample coordinates for organic coastline shape
    cx, cy = map_width / 2.0, map_height / 2.0
    warp_u = warp_noise.sample_mgrid(grid * WARP_SCALE)
    warp_v = warp_noise.sample_mgrid((grid + 47.3) * WARP_SCALE)
    warped_grid = np.stack([
        grid[0] + warp_u * (map_width  * 0.5 * WARP_STRENGTH),
        grid[1] + warp_v * (map_height * 0.5 * WARP_STRENGTH),
    ], axis=0)

    # Elevation sampled at warped coords → organic peninsula/bay shapes
    e  = elev_noise.sample_mgrid(warped_grid * ELEV_SCALE)
    e += elev_noise.sample_mgrid(warped_grid * ELEV_SCALE * ELEV_OCT2_SCALE) * ELEV_OCT2_WEIGHT
    e /= (1.0 + ELEV_OCT2_WEIGHT)

    # Falloff on UNWARPED distance → border is always ocean, independent of warp strength
    dx_n = (xs[:, None] - cx) / cx
    dy_n = (ys[None, :] - cy) / cy
    dist = np.sqrt(dx_n ** 2 + dy_n ** 2)
    t_fall = np.clip((dist - LAND_RADIUS) / LAND_TRANSITION, 0.0, 1.0)
    e -= t_fall * t_fall * (3.0 - 2.0 * t_fall) * LAND_FALLOFF_AMP

    # Biome noise (forest vs plains) and independent desert noise
    b = biome_noise.sample_mgrid(grid * BIOME_SCALE)
    d = desert_noise.sample_mgrid(grid * DESERT_SCALE)

    # ── Terrain assignment ─────────────────────────────────────────────────
    # Elevation → water vs land.  Land biomes are two independent axes:
    #   biome_noise (b) → forest vs plains
    #   desert_noise (d) → desert overlay on plains only (never overwrites forest)
    for x in range(map_width):
        for y in range(map_height):
            ev = float(e[x, y])
            if ev < DEEP_OCEAN_THRESHOLD:
                world.tiles[x, y] = tile_types.overworld_deep_ocean
            elif ev < OCEAN_THRESHOLD:
                world.tiles[x, y] = tile_types.overworld_ocean
            else:
                bv = float(b[x, y])
                dv = float(d[x, y])
                if bv > FOREST_THRESHOLD:
                    world.tiles[x, y] = tile_types.overworld_forest
                elif dv > DESERT_THRESHOLD:
                    world.tiles[x, y] = tile_types.overworld_desert
                else:
                    world.tiles[x, y] = tile_types.overworld_plains

    # ── Island pruning – keep only the largest connected landmass ──────────
    _visited = np.zeros((map_width, map_height), dtype=bool)
    _components: list = []
    for _sx in range(map_width):
        for _sy in range(map_height):
            if world.tiles[_sx, _sy]["walkable"] and not _visited[_sx, _sy]:
                _comp: list = []
                _q: deque = deque()
                _q.append((_sx, _sy))
                _visited[_sx, _sy] = True
                while _q:
                    _px, _py = _q.popleft()
                    _comp.append((_px, _py))
                    for _ddx, _ddy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                        _nx, _ny = _px + _ddx, _py + _ddy
                        if 0 <= _nx < map_width and 0 <= _ny < map_height:
                            if world.tiles[_nx, _ny]["walkable"] and not _visited[_nx, _ny]:
                                _visited[_nx, _ny] = True
                                _q.append((_nx, _ny))
                _components.append(_comp)
    if _components:
        _largest = max(_components, key=len)
        _keep = set(map(id, [_largest]))
        for _comp in _components:
            if id(_comp) not in _keep:
                for (_px, _py) in _comp:
                    world.tiles[_px, _py] = tile_types.overworld_ocean
    del _visited, _components

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

    # ── Plains buffer around mountains (clear desert within radius) ────────
    if mountain_tiles:
        for mx, my in list(mountain_tiles):
            for dx in range(-MOUNTAIN_PLAINS_RADIUS, MOUNTAIN_PLAINS_RADIUS + 1):
                for dy in range(-MOUNTAIN_PLAINS_RADIUS, MOUNTAIN_PLAINS_RADIUS + 1):
                    nx, ny = mx + dx, my + dy
                    if 0 <= nx < map_width and 0 <= ny < map_height:
                        if str(world.tiles[nx, ny]["name"]) == "Desert":
                            world.tiles[nx, ny] = tile_types.overworld_plains


    # ── River generation ──────────────────────────────────────────────────
    _river_tiles = _apply_rivers(world, e, RIVER_COUNT, random.Random(seed + 113))

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

    # ── Beach pass ────────────────────────────────────────────────────────
    _apply_beach(world, protected=_river_tiles)
    # ── River bank overlays (must run after beach so Beach tiles exist) ────
    _river_overlay_record: dict = {}
    # Grass overlays ON river tile where it borders grass-land (not sand).
    _apply_neighbor_overlay(world, _river_tiles,
        {"Plains", "Forest", "Mountain", "Foothill"}, _BEACH_GRASS_OVERLAYS,
        out_overlays=_river_overlay_record)
    # Sand overlays ON river tile where it borders beach or desert.
    _apply_neighbor_overlay(world, _river_tiles,
        {"Beach", "Desert"}, _RIVER_SAND_OVERLAYS,
        out_overlays=_river_overlay_record)
    # Sand overlays ON beach/desert tiles that border river (reverse direction).
    _sand_near_river = [
        (x, y)
        for x in range(map_width)
        for y in range(map_height)
        if str(world.tiles[x, y]["name"]) in ("Beach", "Desert")
        and any(
            0 <= x + dx < map_width and 0 <= y + dy < map_height
            and str(world.tiles[x + dx, y + dy]["name"]) == "River"
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
        )
    ]
    _apply_neighbor_overlay(world, _sand_near_river, {"River"}, _RIVER_SAND_OVERLAYS)
    # ── River animation map: ALL river tiles, overlaid frames pre-composed ─
    _WAVE_FRAMES = list(range(0xE160, 0xE168))
    world.river_anim = {}
    for (rx, ry) in _river_tiles:
        overlays = _river_overlay_record.get((rx, ry), [])
        if overlays:
            seq = tuple(
                ord(sprite_manager.compose_sprite([f] + overlays))
                for f in _WAVE_FRAMES
            )
        else:
            seq = tuple(_WAVE_FRAMES)
        world.river_anim[(rx, ry)] = seq
    # ── Desert edge grass overlay ──────────────────────────────────────────
    _desert_tiles = [
        (x, y)
        for x in range(map_width)
        for y in range(map_height)
        if str(world.tiles[x, y]["name"]) == "Desert"
    ]
    _apply_neighbor_overlay(world, _desert_tiles, {"Plains", "Forest"}, _BEACH_GRASS_OVERLAYS)
    # ── Forest autotile pass ───────────────────────────────────────────────
    _clean_forest_blobs(world)
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


_BEACH_RADIUS = 2
_OCEAN_NAMES  = {"Ocean", "Deep Ocean"}
_RIVER_NAMES  = {"River"}

# Directional grass overlays used for both beach→land and river-bank edges.
_BEACH_GRASS_OVERLAYS = {
    'N':  tile_types._beach_grass_N,
    'S':  tile_types._beach_grass_S,
    'E':  tile_types._beach_grass_E,
    'W':  tile_types._beach_grass_W,
    'NE': tile_types._beach_grass_NE,
    'NW': tile_types._beach_grass_NW,
    'SE': tile_types._beach_grass_SE,
    'SW': tile_types._beach_grass_SW,
}

# Sand-edge overlays for river tiles that border beach (cardinals only).
_RIVER_SAND_OVERLAYS = {
    'N': tile_types._river_sand_N,
    'S': tile_types._river_sand_S,
    'W': tile_types._river_sand_W,
    'E': tile_types._river_sand_E,
}




def _apply_neighbor_overlay(world, candidates, neighbor_names, overlay_sprites, out_overlays=None) -> None:
    """Composite directional edge overlays onto `candidates` where they border `neighbor_names` tiles.

    overlay_sprites: dict mapping direction keys 'N','S','E','W','NE','NW','SE','SW'
                     to integer sprite codepoints.  Missing keys are simply skipped.
    Base codepoints are read from the current tile at each candidate position.
    out_overlays: optional dict; if provided, records {(x,y): [overlay_cps]} for every
                  tile that received at least one overlay (appends on repeated calls).
    """
    W, H = world.width, world.height
    for x, y in candidates:
        has_N = 0 <= y - 1 < H and str(world.tiles[x,     y - 1]["name"]) in neighbor_names
        has_S = 0 <= y + 1 < H and str(world.tiles[x,     y + 1]["name"]) in neighbor_names
        has_E = 0 <= x + 1 < W and str(world.tiles[x + 1, y    ]["name"]) in neighbor_names
        has_W = 0 <= x - 1 < W and str(world.tiles[x - 1, y    ]["name"]) in neighbor_names

        overlays = []
        corner_N = corner_S = corner_E = corner_W = False
        if has_S and has_W and 'SW' in overlay_sprites:
            overlays.append(overlay_sprites['SW']); corner_S = corner_W = True
        if has_S and has_E and 'SE' in overlay_sprites:
            overlays.append(overlay_sprites['SE']); corner_S = corner_E = True
        if has_N and has_E and 'NE' in overlay_sprites:
            overlays.append(overlay_sprites['NE']); corner_N = corner_E = True
        if has_N and has_W and 'NW' in overlay_sprites:
            overlays.append(overlay_sprites['NW']); corner_N = corner_W = True
        if has_N and not corner_N and 'N' in overlay_sprites:
            overlays.append(overlay_sprites['N'])
        if has_S and not corner_S and 'S' in overlay_sprites:
            overlays.append(overlay_sprites['S'])
        if has_E and not corner_E and 'E' in overlay_sprites:
            overlays.append(overlay_sprites['E'])
        if has_W and not corner_W and 'W' in overlay_sprites:
            overlays.append(overlay_sprites['W'])
        if not overlays:
            continue
        base_dark  = int(world.tiles[x, y]["dark"]["ch"])
        base_light = int(world.tiles[x, y]["light"]["ch"])
        result = world.tiles[x, y].copy()
        result["dark"]["ch"]  = ord(sprite_manager.compose_sprite([base_dark]  + overlays))
        result["light"]["ch"] = ord(sprite_manager.compose_sprite([base_light] + overlays))
        world.tiles[x, y] = result
        if out_overlays is not None:
            if (x, y) in out_overlays:
                out_overlays[(x, y)].extend(overlays)
            else:
                out_overlays[(x, y)] = list(overlays)


def _apply_rivers(world, elev, num_rivers: int, rng: random.Random) -> None:
    """Carve rivers from mountain-adjacent sources downhill to coast/ocean.

    Each river is a greedy downhill walk on the elevation grid `elev`.
    The resulting path is written as River tiles, then directional grass
    overlays are composited onto every walkable neighbor tile.

    Parameters
    ----------
    world       : GameMap being built
    elev        : numpy array shape (W, H) of elevation values used for generation
    num_rivers  : how many rivers to attempt
    rng         : seeded Random instance for reproducibility
    """
    W, H = world.width, world.height
    _LAND_WALKABLE = {"Plains", "Forest", "Desert", "Beach"}
    _WATER_NAMES   = {"Ocean", "Deep Ocean", "Shore", "River"}

    def _is_mountain(x, y):
        if x < 0 or x >= W or y < 0 or y >= H:
            return False
        return str(world.tiles[x, y]["name"]) == "Mountain"

    def _is_walkable_land(x, y):
        if x < 0 or x >= W or y < 0 or y >= H:
            return False
        return str(world.tiles[x, y]["name"]) in _LAND_WALKABLE

    def _is_water(x, y):
        if x < 0 or x >= W or y < 0 or y >= H:
            return True  # treat OOB as water/edge
        return str(world.tiles[x, y]["name"]) in _WATER_NAMES

    # Collect mountain-adjacent walkable land tiles as river source candidates
    sources = []
    for x in range(W):
        for y in range(H):
            if not _is_walkable_land(x, y):
                continue
            if any(_is_mountain(x + dx, y + dy)
                   for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))):
                sources.append((x, y))

    if not sources:
        return

    all_river_tiles: set = set()

    for _ in range(num_rivers):
        if not sources:
            break
        sx, sy = rng.choice(sources)
        sources.remove((sx, sy))

        path = []
        cx, cy = sx, sy
        visited = {(cx, cy)}
        MAX_STEPS = max(W, H) * 3

        for _step in range(MAX_STEPS):
            path.append((cx, cy))
            if _is_water(cx, cy + 1) or _is_water(cx - 1, cy) or _is_water(cx + 1, cy) or _is_water(cx, cy - 1):
                # Reached coast — done
                break
            # Greedy downhill: pick lowest-elevation cardinal neighbor that
            # is walkable land and not already in this path
            nbrs = []
            for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if (nx, ny) not in visited and _is_walkable_land(nx, ny):
                    nbrs.append((float(elev[nx, ny]), nx, ny))
                elif (nx, ny) not in visited and _is_water(nx, ny):
                    path.append((nx, ny))
                    break
            else:
                if not nbrs:
                    break  # stuck — abandon this river
                # 10% chance to pick 2nd-lowest to add gentle bends
                nbrs.sort()
                if len(nbrs) >= 2 and rng.random() < 0.10:
                    _, cx, cy = nbrs[1]
                else:
                    _, cx, cy = nbrs[0]
                visited.add((cx, cy))
                continue
            break  # reached water via the inner break

        if len(path) < 3:
            continue  # too short — skip

        for rx, ry in path:
            if str(world.tiles[rx, ry]["name"]) not in _WATER_NAMES:
                world.tiles[rx, ry] = tile_types.overworld_river
                all_river_tiles.add((rx, ry))

    return all_river_tiles


def _apply_beach(world, protected=None) -> None:
    """Replace land tiles within _BEACH_RADIUS of ocean with beach.
    
    protected: optional set of (x,y) positions that must not be overwritten.
    """
    W, H = world.width, world.height

    def _is_ocean(x, y):
        if x < 0 or x >= W or y < 0 or y >= H:
            return False
        return str(world.tiles[x, y]["name"]) in _OCEAN_NAMES

    beach_candidates = set()
    for x in range(W):
        for y in range(H):
            if not world.tiles[x, y]["walkable"]:
                continue
            name = str(world.tiles[x, y]["name"])
            if name in _OCEAN_NAMES or name == "River":
                continue
            # Flood outward from ocean within radius using Chebyshev distance
            for dx in range(-_BEACH_RADIUS, _BEACH_RADIUS + 1):
                for dy in range(-_BEACH_RADIUS, _BEACH_RADIUS + 1):
                    if _is_ocean(x + dx, y + dy):
                        beach_candidates.add((x, y))
                        break
                else:
                    continue
                break

    for x, y in beach_candidates:
        if protected and (x, y) in protected:
            continue
        world.tiles[x, y] = tile_types.overworld_beach

    # Remove beach blobs that are not cardinally connected to any land tile.
    # Flood-fill each connected beach component; if none of its tiles touch land
    # (cardinally), convert the whole component back to ocean.
    _LAND_NAMES = {"Plains", "Forest", "Mountain", "Foothill", "Grassland", "Tundra", "Desert", "River"}
    def _is_land(nx, ny):
        if nx < 0 or nx >= W or ny < 0 or ny >= H:
            return False
        return str(world.tiles[nx, ny]["name"]) in _LAND_NAMES

    beach_set = set(beach_candidates)
    visited = set()
    for start in list(beach_set):
        if start in visited:
            continue
        # BFS over cardinally-connected beach tiles
        component = []
        queue = [start]
        visited.add(start)
        touches_land = False
        while queue:
            cx, cy = queue.pop()
            component.append((cx, cy))
            for dx, dy in ((0,-1),(0,1),(1,0),(-1,0)):
                nx2, ny2 = cx+dx, cy+dy
                if _is_land(nx2, ny2):
                    touches_land = True
                if (nx2, ny2) in beach_set and (nx2, ny2) not in visited:
                    visited.add((nx2, ny2))
                    queue.append((nx2, ny2))
        if not touches_land:
            for tx, ty in component:
                world.tiles[tx, ty] = tile_types.overworld_ocean
                beach_set.discard((tx, ty))
    beach_candidates = beach_set

    # Composite grass overlays onto beach tiles that border land.
    _GRASS_NAMES = {"Plains", "Forest", "Mountain", "Foothill"}
    _apply_neighbor_overlay(world, beach_candidates, _GRASS_NAMES, _BEACH_GRASS_OVERLAYS)

    # Build per-tile water animation sequences for beach tiles that border ocean.
    # SE = ocean S + ocean E (solid beach N+W).  SW = ocean S + ocean W, etc.
    # Cardinals = exactly one cardinal ocean neighbor.
    from animations import GlobalBeachWaterAnimation as _BWA
    rng = random.Random(getattr(world, "seed", 0) + 7)
    anim_map: dict = {}

    def _ocean(nx, ny):
        return 0 <= nx < W and 0 <= ny < H and str(world.tiles[nx, ny]["name"]) in _OCEAN_NAMES

    for x, y in beach_candidates:
        on = _ocean(x,   y-1)
        os = _ocean(x,   y+1)
        oe = _ocean(x+1, y  )
        ow = _ocean(x-1, y  )
        if os and oe:
            anim_map[(x, y)] = _BWA.FRAMES_SE
        elif os and ow:
            anim_map[(x, y)] = _BWA.FRAMES_SW
        elif on and oe:
            anim_map[(x, y)] = _BWA.FRAMES_NE
        elif on and ow:
            anim_map[(x, y)] = _BWA.FRAMES_NW
        elif on:
            anim_map[(x, y)] = _BWA.FRAMES_N
        elif os:
            anim_map[(x, y)] = _BWA.FRAMES_S
        elif oe:
            anim_map[(x, y)] = _BWA.FRAMES_E if rng.random() < 0.5 else _BWA.FRAMES_E2
        elif ow:
            anim_map[(x, y)] = _BWA.FRAMES_W if rng.random() < 0.5 else _BWA.FRAMES_W2
        else:
            # No cardinal ocean neighbor: tile became beach via Chebyshev diagonal.
            # Fill concave-corner gaps with the matching diagonal corner sprite.
            if   _ocean(x-1, y-1): anim_map[(x, y)] = _BWA.FRAMES_NW
            elif _ocean(x+1, y-1): anim_map[(x, y)] = _BWA.FRAMES_NE
            elif _ocean(x-1, y+1): anim_map[(x, y)] = _BWA.FRAMES_SW
            elif _ocean(x+1, y+1): anim_map[(x, y)] = _BWA.FRAMES_SE

    # Cull animated tiles that don't touch a solid Beach tile cardinally.
    # "Solid" means a beach_candidate that is NOT itself in anim_map.
    # Other anim_map tiles don't count — they're all Shore, not solid backing.
    shore_set = set(anim_map.keys())
    solid_beach = set(beach_candidates) - shore_set

    to_remove = [
        (x, y) for (x, y) in anim_map
        if not any((x+dx, y+dy) in solid_beach for dx, dy in ((0,-1),(0,1),(1,0),(-1,0)))
    ]
    for (x, y) in to_remove:
        world.tiles[x, y] = tile_types.overworld_ocean
        del anim_map[(x, y)]

    # Convert every remaining animated tile to the dedicated Shore tile type.
    # Shore is visually ocean but named "Shore" so the animation targets it exactly.
    for (x, y) in anim_map:
        world.tiles[x, y] = tile_types.overworld_shore

    world.beach_water_anim = anim_map


# The 9 cardinal combos that map exactly to one of the 3x3 autotile sprites.
_FOREST_VALID_COMBOS = {
    (False, True,  True,  False),  # S+E   → top_left
    (False, True,  True,  True ),  # S+E+W → top_center
    (False, True,  False, True ),  # S+W   → top_right
    (True,  True,  True,  False),  # N+S+E → mid_left
    (True,  True,  True,  True ),  # all 4 → mid_center
    (True,  True,  False, True ),  # N+S+W → mid_right
    (True,  False, True,  False),  # N+E   → bot_left
    (True,  False, True,  True ),  # N+E+W → bot_center
    (True,  False, False, True ),  # N+W   → bot_right
}


def _clean_forest_blobs(world) -> None:
    """Erode forest tiles that don't fit the 3x3 autotile grid.
    Iterates until stable: any tile whose cardinal-neighbor pattern isn't
    one of the 9 valid combos is converted to plains."""
    W, H = world.width, world.height

    def _is_forest(x, y):
        if x < 0 or x >= W or y < 0 or y >= H:
            return False
        return str(world.tiles[x, y]["name"]) == "Forest"

    changed = True
    while changed:
        changed = False
        for x in range(W):
            for y in range(H):
                if not _is_forest(x, y):
                    continue
                combo = (
                    _is_forest(x,     y - 1),  # N
                    _is_forest(x,     y + 1),  # S
                    _is_forest(x + 1, y    ),  # E
                    _is_forest(x - 1, y    ),  # W
                )
                if combo not in _FOREST_VALID_COMBOS:
                    world.tiles[x, y] = tile_types.overworld_plains
                    changed = True


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

# Pre-composite overlays for mountain bases.
# Structure: { base_biome_name: (neighbor_names_set, overlay_sprites_dict) }
# Empty by default — mountains are always surrounded by plains (see MOUNTAIN_PLAINS_RADIUS).
_MOUNTAIN_BIOME_PRE_OVERLAYS: dict = {}


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
            tile_name = "Plains"
        # Apply any pre-composite neighbor overlays (e.g. sand edge on plains→desert border)
        if tile_name in _MOUNTAIN_BIOME_PRE_OVERLAYS:
            neighbor_names, overlay_sprites = _MOUNTAIN_BIOME_PRE_OVERLAYS[tile_name]
            _apply_neighbor_overlay(world, [(mx, my)], neighbor_names, overlay_sprites)
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


