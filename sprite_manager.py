"""Sprite manager: loads extra tiles from RP/extras.png into the tcod tileset.

How to add new overlay sprites:
  1. Open RP/extras.png in your image editor.
  2. Draw your sprite in a 10x10 pixel cell.
     The grid is 16 columns wide. Tiles are read left-to-right, top-to-bottom.
     Row 0, Col 0  = slot 0  -> codepoint 0xE000 -> tile_ids.EXTRAS[0]
     Row 0, Col 1  = slot 1  -> codepoint 0xE001 -> tile_ids.EXTRAS[1]
     ... and so on.
  3. Add a named constant to tile_ids.py:
       VINE   = chr(0xE000)
       BLOOD  = chr(0xE001)
  4. Use it anywhere: console.print(x, y, tile_ids.VINE, fg=(34,139,34))
"""
from __future__ import annotations
import os
import numpy as np

TILE_W = 32
TILE_H = 32
EXTRAS_COLS = 16  # Width of extras.png grid in tiles
EXTRAS_START_CP = 0xE000  # First Unicode Private Use Area codepoint

# --- Composite sprite state ---
COMPOSITE_START_CP = 0xEF00  # Reserved composite region (0xEF00–0xEFFF)
_composite_cache: dict = {}   # tuple(codepoints) -> assigned codepoint int
_composite_next: int = COMPOSITE_START_CP
_tileset = None               # Set by load_extras; used by compose/refresh

# --- Deferred set_tile queue (used during background gen to avoid GPU calls) ---
_deferred_mode: bool = False
_deferred_tiles: list = []       # List of (cp, pixels_uint8) to flush on main thread
_deferred_pixel_store: dict = {} # cp -> pixels_uint8: CPU-side store so get_tile works during deferred mode


def set_deferred_mode(enabled: bool) -> None:
    """Enable/disable deferred GPU tile uploads. Call set_deferred_mode(True) before
    running world gen on a background thread, then flush_deferred_tiles() afterwards
    on the main thread to safely apply all set_tile calls."""
    global _deferred_mode
    _deferred_mode = enabled
    # Do NOT clear _deferred_tiles here — flush_deferred_tiles() owns that.
    # When disabling, only drop the CPU-side lookup store (no longer needed).
    if not enabled:
        _deferred_pixel_store.clear()


def flush_deferred_tiles() -> None:
    """Apply all queued set_tile calls. Must be called from the main (SDL) thread."""
    global _deferred_tiles, _deferred_pixel_store
    if _tileset is None:
        _deferred_tiles.clear()
        _deferred_pixel_store.clear()
        return
    for cp, pixels in _deferred_tiles:
        _tileset.set_tile(cp, pixels)
    _deferred_tiles.clear()
    _deferred_pixel_store.clear()


def _get_tile(cp: int) -> np.ndarray:
    """Get tile pixels, checking CPU-side deferred store before the GPU tileset."""
    if _deferred_mode and cp in _deferred_pixel_store:
        return _deferred_pixel_store[cp].copy()
    return _tileset.get_tile(cp)


def _offset_overlay_tile(tile_pixels: np.ndarray, x_offset: int, y_offset: int) -> np.ndarray:
    """Shift an overlay tile by the given pixel offsets, filling empty space with transparency."""
    if x_offset == 0 and y_offset == 0:
        return tile_pixels

    height, width = tile_pixels.shape[:2]
    canvas = np.zeros_like(tile_pixels)

    src_x0 = max(0, -x_offset)
    src_x1 = min(width, width - x_offset)
    src_y0 = max(0, -y_offset)
    src_y1 = min(height, height - y_offset)

    dest_x0 = max(0, x_offset)
    dest_x1 = min(width, width + x_offset)
    dest_y0 = max(0, y_offset)
    dest_y1 = min(height, height + y_offset)

    copy_width = dest_x1 - dest_x0
    copy_height = dest_y1 - dest_y0
    if copy_width <= 0 or copy_height <= 0:
        return canvas

    canvas[dest_y0:dest_y1, dest_x0:dest_x1, :] = tile_pixels[src_y0:src_y1, src_x0:src_x1, :]
    return canvas


def _crop_overlay_tile(tile_pixels: np.ndarray, x_crop: int, y_crop: int) -> np.ndarray:
    """Crop an overlay tile by the given pixel amounts on each side, filling empty space with transparency."""
    if x_crop == 0 and y_crop == 0:
        return tile_pixels

    height, width = tile_pixels.shape[:2]
    canvas = np.zeros_like(tile_pixels)

    # x_crop > 0 removes right columns, x_crop < 0 removes left columns.
    if x_crop >= 0:
        src_x0 = 0
        src_x1 = max(0, width - x_crop)
    else:
        src_x0 = min(width, -x_crop)
        src_x1 = width

    # y_crop > 0 removes bottom rows, y_crop < 0 removes top rows.
    if y_crop >= 0:
        src_y0 = 0
        src_y1 = max(0, height - y_crop)
    else:
        src_y0 = min(height, -y_crop)
        src_y1 = height

    dest_x0 = 0
    dest_x1 = src_x1 - src_x0
    dest_y0 = 0
    dest_y1 = src_y1 - src_y0

    copy_width = dest_x1 - dest_x0
    copy_height = dest_y1 - dest_y0
    if copy_width <= 0 or copy_height <= 0:
        return canvas

    canvas[dest_y0:dest_y1, dest_x0:dest_x1, :] = tile_pixels[src_y0:src_y1, src_x0:src_x1, :]
    return canvas

def _scale_overlay_tile(tile_pixels: np.ndarray, scale: float) -> np.ndarray:
    """Compress an overlay tile vertically and anchor it to the bottom of the cell."""
    if scale == 1.0:
        return tile_pixels

    height, width = tile_pixels.shape[:2]
    scaled_height = max(1, int(round(height * scale)))

    src_y = np.minimum((np.arange(scaled_height) / scale).astype(int), height - 1)
    resized = tile_pixels[src_y, :, :]

    canvas = np.zeros_like(tile_pixels)

    dest_y0 = height - scaled_height
    dest_y1 = dest_y0 + scaled_height
    src_y0 = 0

    if dest_y0 < 0:
        src_y0 = -dest_y0
        dest_y0 = 0

    dest_y1 = min(height, dest_y1)

    copy_height = dest_y1 - dest_y0
    if copy_height <= 0:
        return canvas

    canvas[dest_y0:dest_y1, :, :] = resized[
        src_y0:src_y0 + copy_height,
        :,
        :,
    ]
    return canvas


def load_extras(tileset, path: str = "RP/extras.png") -> int:
    """Load every tile from the extras sheet into the tileset.

    Returns the number of tiles registered.
    Silently skips if the file doesn't exist yet.
    """
    if not os.path.exists(path):
        return 0

    try:
        from PIL import Image
    except ImportError:
        print("[sprite_manager] Pillow not installed — extras sheet skipped.")
        return 0

    img = Image.open(path).convert("RGBA")
    img_w, img_h = img.size
    cols = img_w // TILE_W
    rows = img_h // TILE_H
    count = 0
    for row in range(rows):
        for col in range(cols):
            left   = col * TILE_W
            top    = row * TILE_H
            right  = left + TILE_W
            bottom = top  + TILE_H
            tile_pixels = np.array(img.crop((left, top, right, bottom)), dtype=np.uint8)
            cp = EXTRAS_START_CP + count
            tileset.set_tile(cp, tile_pixels)
            count += 1
    global _tileset
    _tileset = tileset  # store for use by compose_sprite / refresh_actor_sprite
    print(f"[sprite_manager] Loaded {count} extra tiles from '{path}' (0xE000 – 0x{EXTRAS_START_CP + count - 1:04X}).")
    return count


def compose_sprite(layer_codepoints: list[int], overlay_scale: float = 1.0, x_offset: int = 0, y_offset: int = 0, x_crop: int = 0, y_crop: int = 0, top_first_layer: bool = True, layer_tints: list | None = None) -> str:
    """Alpha-composite multiple tile layers into a new tileset slot.

    Blends codepoints bottom-up (first = base, last = top layer) by default.
    If top_first_layer=False, the first layer is treated as the top, and all following
    layers are composed behind it.

    layer_tints: optional list of (R,G,B) tuples (or None entries) to multiply
    into each layer's pixels before compositing.  None = no tint (white).

    Caches results so identical combos reuse the same slot.
    Returns the chr() of the resulting codepoint.

    Note: x_crop/y_crop apply to the first layer only.
    """
    try:
        global _composite_next, _tileset
        if _tileset is None:
            raise RuntimeError("[sprite_manager] compose_sprite called before load_extras set the tileset.")

        normalized_scale = max(0.05, float(overlay_scale))
        # Normalise tints for cache key: None → (255,255,255)
        norm_tints = None
        if layer_tints is not None:
            norm_tints = tuple(
                (255, 255, 255) if t is None else tuple(int(v) for v in t)
                for t in layer_tints
            )
        key = (tuple(layer_codepoints), round(normalized_scale, 4), x_offset, y_offset, x_crop, y_crop, top_first_layer, norm_tints)
        if key in _composite_cache:
            return chr(_composite_cache[key])

        def _apply_tint(pixels: np.ndarray, tint) -> np.ndarray:
            """Multiply RGB channels of pixel data by a (R,G,B) tint."""
            if tint is None or tint == (255, 255, 255):
                return pixels
            t = np.array([tint[0], tint[1], tint[2], 255], dtype=np.float32) / 255.0
            result = pixels.astype(np.float32)
            result[..., :3] *= t[:3]
            return result

        def _tint_for(idx: int):
            if norm_tints is None or idx >= len(norm_tints):
                return None
            return norm_tints[idx]

        # First layer (entity) is special: cropped and/or preserved as top if requested.
        first = _get_tile(layer_codepoints[0]).astype(np.float32).copy()
        first = _apply_tint(first, _tint_for(0))
        if x_crop != 0 or y_crop != 0:
            first = _crop_overlay_tile(first, x_crop, y_crop).astype(np.float32)

        if top_first_layer:
            base = first
            overlay_layers = layer_codepoints[1:]
        else:
            # Compose all background layers (the rest) first, then draw first on top.
            if len(layer_codepoints) > 1:
                base = _get_tile(layer_codepoints[1]).astype(np.float32).copy()
                for cp in layer_codepoints[2:]:
                    overlay_pixels = _get_tile(cp)
                    if normalized_scale != 1.0:
                        overlay_pixels = _scale_overlay_tile(overlay_pixels, normalized_scale)
                    if x_offset != 0 or y_offset != 0:
                        overlay_pixels = _offset_overlay_tile(overlay_pixels, x_offset, y_offset)
                    overlay = overlay_pixels.astype(np.float32)
                    alpha = overlay[..., 3:4] / 255.0
                    base[..., :3] = overlay[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
                    base[..., 3] = np.maximum(base[..., 3], overlay[..., 3])
            else:
                base = np.zeros_like(first)
            overlay_layers = []

        if top_first_layer:
            target_layers = overlay_layers
        else:
            # after building background from remaining layers, overlay first on top
            target_layers = [layer_codepoints[0]]

        if not top_first_layer:
            # if first is top, we already have background base; now overlay first last.
            overlay_layers = []
            for cp in [layer_codepoints[0]]:
                overlay_pixels = first
                # first already has crop and no transforms applied
                alpha = (overlay_pixels[..., 3:4] / 255.0)
                base[..., :3] = overlay_pixels[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
                base[..., 3] = np.maximum(base[..., 3], overlay_pixels[..., 3])
        else:
            for cp in overlay_layers:
                overlay_pixels = _get_tile(cp)
                overlay_pixels = _apply_tint(overlay_pixels, _tint_for(layer_codepoints.index(cp)))
                if normalized_scale != 1.0:
                    overlay_pixels = _scale_overlay_tile(overlay_pixels, normalized_scale)
                if x_offset != 0 or y_offset != 0:
                    overlay_pixels = _offset_overlay_tile(overlay_pixels, x_offset, y_offset)
                overlay = overlay_pixels.astype(np.float32)
                alpha = overlay[..., 3:4] / 255.0
                base[..., :3] = overlay[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
                base[..., 3] = np.maximum(base[..., 3], overlay[..., 3])

        result = base.astype(np.uint8)
        cp = _composite_next
        if _deferred_mode:
            _deferred_pixel_store[cp] = result
            _deferred_tiles.append((cp, result))
        else:
            _tileset.set_tile(cp, result)
        _composite_cache[key] = cp
        _composite_next += 1
        return chr(cp)
    except Exception as e:
        print(f"[sprite_manager] Error composing sprite from layers {[hex(c) for c in layer_codepoints]}: {e}")
        return chr(layer_codepoints[0])  # fallback to base layer if composition fails



def refresh_actor_sprite(actor) -> None:
    """Rebuild actor.char from base_char + sprite_layers of currently equipped items."""
    if not hasattr(actor, 'base_char'):
        return
    overlay_scale = getattr(actor, 'equipment_scale', 1.0)
    layers = [ord(actor.base_char)] + [
        item.equip_sprite_cp
        for item in list(getattr(actor.equipment, 'grasped_items', {}).values()) +
                     list(getattr(actor.equipment, 'equipped_items', {}).values()) +
                     list(getattr(actor.equipment, 'body_part_coverage', {}).values())
        if getattr(item, 'equip_sprite_cp', None) is not None
    ]
    # Deduplicate while preserving order
    seen: set = set()
    unique_layers = []
    for cp in layers:
        if cp not in seen:
            seen.add(cp)
            unique_layers.append(cp)

    if len(unique_layers) == 1:
        actor.char = actor.base_char
    else:
        actor.char = compose_sprite(unique_layers, overlay_scale=overlay_scale)


_WATER_FRAME_CPS = [0xE140, 0xE141, 0xE142, 0xE143, 0xE144]

# ---------------------------------------------------------------------------
# Dungeon water compositor
# ---------------------------------------------------------------------------
# Neighbor-mask bit assignments (cardinal directions).
_DW_N, _DW_E, _DW_S, _DW_W = 1, 2, 4, 8

# Tuning constants for 32×32 tiles.
# BLOB_R  – radius (pixels) of the semicircular water blob on each edge.
#           A circle of this radius is centred on the midpoint of the edge;
#           only the inward half is visible, giving a natural semicircle bite.
#           Adjacent edge blobs overlap at corners, naturally forming a larger
#           rounded blob — no triangle, no explicit arc formula needed.
# FEATHER – soft-blend width at the blob boundary (pixels).
_DW_BLOB_R  = 15   # ~47% of tile width; large enough to always cover the full edge
_DW_FEATHER = 4
# Floor sprite variants (kept for potential future use).
_DW_FLOOR_VARIANTS = list(range(0xE1E0, 0xE1E7))


def _dungeon_water_bite_mask(neighbor_mask: int) -> np.ndarray:
    """Return a (TILE_H, TILE_W) float32 array — 1.0 = water, 0.0 = floor.

    Each water-neighboring edge contributes a semicircle blob centred on the
    midpoint of that edge.  Adjacent blobs overlap via np.maximum, producing
    larger compound blobs at corners without any triangular narrowing.
    """
    W, H = TILE_W, TILE_H
    R       = float(_DW_BLOB_R)
    FEATHER = max(1.0, float(_DW_FEATHER))

    has_N = bool(neighbor_mask & _DW_N)
    has_E = bool(neighbor_mask & _DW_E)
    has_S = bool(neighbor_mask & _DW_S)
    has_W = bool(neighbor_mask & _DW_W)

    rows = np.arange(H, dtype=np.float32)
    cols = np.arange(W, dtype=np.float32)
    dist_N = rows[:, None]            # distance from top edge
    dist_S = (H - 1 - rows)[:, None] # distance from bottom edge
    dist_W = cols[None, :]            # distance from left edge
    dist_E = (W - 1 - cols)[None, :] # distance from right edge

    half_W = (W - 1) / 2.0
    half_H = (H - 1) / 2.0
    # Offset from the horizontal / vertical tile centre axis
    cols_c = cols[None, :] - half_W   # (1, W)
    rows_c = rows[:, None] - half_H   # (H, 1)

    water_alpha = np.zeros((H, W), dtype=np.float32)

    def _ramp(signed_dist: np.ndarray) -> np.ndarray:
        """signed_dist > 0 = inside blob; returns smooth [0,1] alpha."""
        return np.clip(signed_dist / FEATHER + 1.0, 0.0, 1.0)

    # Each bite is a circle of radius R centred on the midpoint of the edge
    # (row=0, col=half_W for North, etc.).  Only pixels inside the tile receive
    # non-zero alpha, so only the inward semicircle is ever visible.
    if has_N:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_N, cols_c)))
    if has_S:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_S, cols_c)))
    if has_W:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_W, rows_c)))
    if has_E:
        water_alpha = np.maximum(water_alpha, _ramp(R - np.hypot(dist_E, rows_c)))

    return water_alpha


def compose_dungeon_water(floor_cp: int, water_cp: int, neighbor_mask: int) -> str:
    """Composite animated water biting into a floor tile.

    neighbor_mask encodes which cardinal directions HAVE water neighbors.
    Water pixels are alpha-blended over floor pixels in the bite region.
    Returns chr() of the resulting cached codepoint.
    """
    global _composite_next, _tileset
    if _tileset is None:
        return chr(floor_cp)

    key = ('_dw', floor_cp, water_cp, neighbor_mask)
    if key in _composite_cache:
        return chr(_composite_cache[key])

    floor_pixels = _get_tile(floor_cp).astype(np.uint8)
    water_pixels = _get_tile(water_cp).astype(np.uint8)

    if neighbor_mask == 0:
        # No water neighbors — return the plain floor tile.
        result = floor_pixels.copy()
    else:
        # water_alpha [0,1]: 1.0 = full water, 0.0 = full floor.
        # Soft feathered boundary makes animation appear to wash against the shore.
        water_alpha = _dungeon_water_bite_mask(neighbor_mask)  # (H, W) float32
        floor_f = floor_pixels.astype(np.float32)
        water_f = water_pixels.astype(np.float32)
        a = water_alpha[:, :, np.newaxis]                      # broadcast over RGBA
        result = np.clip(floor_f * (1.0 - a) + water_f * a, 0, 255).astype(np.uint8)

    cp = _composite_next
    if _deferred_mode:
        _deferred_pixel_store[cp] = result
        _deferred_tiles.append((cp, result))
    else:
        _tileset.set_tile(cp, result)
    _composite_cache[key] = cp
    _composite_next += 1
    return chr(cp)


def build_dungeon_water_anim(game_map) -> None:
    """Pre-compose animated water-bite frames for floor tiles that border water.

    For each walkable non-water tile adjacent to at least one water tile,
    compose 5 frames (one per water animation frame) where the water sprite
    bites into the floor tile from the water-neighboring edges.

    Central water tiles are left alone — GlobalWaterAnimation handles them.
    This means the composited edge blends use the exact same water sprites as
    the centre, so there is no seam.

    Stores game_map.dungeon_water_anim = {(x, y): (cp0, cp1, cp2, cp3, cp4)}.
    Safe to call inside deferred mode (background gen thread).
    """
    W, H = game_map.width, game_map.height
    tiles = game_map.tiles
    anim_map: dict = {}

    for x in range(W):
        for y in range(H):
            tile = tiles[x, y]
            # Only process walkable non-water floor tiles.
            if str(tile["name"]) == "Water" or not tile["walkable"]:
                continue

            # Neighbor mask: bit set for each cardinal direction that HAS water.
            nmask = 0
            if y > 0 and str(tiles[x, y - 1]["name"]) == "Water":
                nmask |= _DW_N
            if x < W - 1 and str(tiles[x + 1, y]["name"]) == "Water":
                nmask |= _DW_E
            if y < H - 1 and str(tiles[x, y + 1]["name"]) == "Water":
                nmask |= _DW_S
            if x > 0 and str(tiles[x - 1, y]["name"]) == "Water":
                nmask |= _DW_W

            if nmask == 0:
                continue  # no water neighbors, skip

            # Use the tile's own light codepoint as the floor base.
            floor_cp = int(tile["light"]["ch"])

            frames = tuple(
                ord(compose_dungeon_water(floor_cp, wcp, nmask))
                for wcp in _WATER_FRAME_CPS
            )
            anim_map[(x, y)] = frames

    game_map.dungeon_water_anim = anim_map
    print(f"[sprite_manager] Built dungeon water anim for {len(anim_map)} floor-edge tiles.")


def apply_neighbor_overlay(
    tilemap,
    candidates,
    neighbor_names,
    overlay_sprites: dict,
    overlay_tint_light=None,
    overlay_tint_dark=None,
    out_overlays=None,
) -> None:
    """Composite directional edge overlays onto tiles in *candidates* where they
    border tiles whose names are in *neighbor_names*.

    overlay_sprites maps direction string keys → integer codepoints.  Recognised keys:

      Cardinal  : 'N', 'S', 'E', 'W'
        Applied when that cardinal neighbour is in neighbor_names.

      Inner corners : 'NW', 'NE', 'SW', 'SE'
        Applied when BOTH adjacent cardinals are present; those two cardinals are
        then suppressed (the corner sprite covers them).

      Outer corners : 'NW_outer', 'NE_outer', 'SW_outer', 'SE_outer'
        Applied when ONLY the diagonal is present (convex corner nub); neither
        adjacent cardinal may match.

    Missing keys in overlay_sprites are simply skipped.

    overlay_tint_light / overlay_tint_dark : optional (R, G, B) tuples to
      multiply into every overlay pixel when compositing the light / dark state.
      None means no tint (white pass-through).

    out_overlays : optional dict {(x, y): [codepoints]}; if provided, every
      codepoint applied at each position is recorded here (appended on repeat
      calls to the same position).
    """
    W = tilemap.width
    H = tilemap.height
    for x, y in candidates:
        has_N  = 0 <= y - 1 < H and str(tilemap.tiles[x,     y - 1]["name"]) in neighbor_names
        has_S  = 0 <= y + 1 < H and str(tilemap.tiles[x,     y + 1]["name"]) in neighbor_names
        has_E  = 0 <= x + 1 < W and str(tilemap.tiles[x + 1, y    ]["name"]) in neighbor_names
        has_W  = 0 <= x - 1 < W and str(tilemap.tiles[x - 1, y    ]["name"]) in neighbor_names
        has_NE = 0 <= x + 1 < W and 0 <= y - 1 < H and str(tilemap.tiles[x + 1, y - 1]["name"]) in neighbor_names
        has_NW = 0 <= x - 1 < W and 0 <= y - 1 < H and str(tilemap.tiles[x - 1, y - 1]["name"]) in neighbor_names
        has_SE = 0 <= x + 1 < W and 0 <= y + 1 < H and str(tilemap.tiles[x + 1, y + 1]["name"]) in neighbor_names
        has_SW = 0 <= x - 1 < W and 0 <= y + 1 < H and str(tilemap.tiles[x - 1, y + 1]["name"]) in neighbor_names

        overlays: list[int] = []
        corner_N = corner_S = corner_E = corner_W = False

        # Inner corners: both adjacent cardinals present → one combined sprite
        if has_S and has_W and "SW" in overlay_sprites:
            overlays.append(overlay_sprites["SW"])
            corner_S = corner_W = True
        if has_S and has_E and "SE" in overlay_sprites:
            overlays.append(overlay_sprites["SE"])
            corner_S = corner_E = True
        if has_N and has_E and "NE" in overlay_sprites:
            overlays.append(overlay_sprites["NE"])
            corner_N = corner_E = True
        if has_N and has_W and "NW" in overlay_sprites:
            overlays.append(overlay_sprites["NW"])
            corner_N = corner_W = True

        # Cardinal edges (not already handled by an inner corner)
        if has_N and not corner_N and "N" in overlay_sprites:
            overlays.append(overlay_sprites["N"])
        if has_S and not corner_S and "S" in overlay_sprites:
            overlays.append(overlay_sprites["S"])
        if has_E and not corner_E and "E" in overlay_sprites:
            overlays.append(overlay_sprites["E"])
        if has_W and not corner_W and "W" in overlay_sprites:
            overlays.append(overlay_sprites["W"])

        # Outer corners: only diagonal present, neither adjacent cardinal
        if has_SW and not has_S and not has_W and "SW_outer" in overlay_sprites:
            overlays.append(overlay_sprites["SW_outer"])
        if has_SE and not has_S and not has_E and "SE_outer" in overlay_sprites:
            overlays.append(overlay_sprites["SE_outer"])
        if has_NW and not has_N and not has_W and "NW_outer" in overlay_sprites:
            overlays.append(overlay_sprites["NW_outer"])
        if has_NE and not has_N and not has_E and "NE_outer" in overlay_sprites:
            overlays.append(overlay_sprites["NE_outer"])

        if not overlays:
            continue

        base_dark  = int(tilemap.tiles[x, y]["dark"]["ch"])
        base_light = int(tilemap.tiles[x, y]["light"]["ch"])
        tints_light = ([None] + [overlay_tint_light] * len(overlays)) if overlay_tint_light is not None else None
        tints_dark  = ([None] + [overlay_tint_dark]  * len(overlays)) if overlay_tint_dark  is not None else None
        result = tilemap.tiles[x, y].copy()
        result["dark"]["ch"]  = ord(compose_sprite([base_dark]  + overlays, layer_tints=tints_dark))
        result["light"]["ch"] = ord(compose_sprite([base_light] + overlays, layer_tints=tints_light))
        tilemap.tiles[x, y] = result
        if out_overlays is not None:
            if (x, y) in out_overlays:
                out_overlays[(x, y)].extend(overlays)
            else:
                out_overlays[(x, y)] = list(overlays)


# ---------------------------------------------------------------------------
# Portrait compositor
# ---------------------------------------------------------------------------

_PORTRAIT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "portrait_cache")
_PORTRAIT_PARTS_DIR = os.path.join(os.path.dirname(__file__), "components", "portrait_parts")
# Bump this string to invalidate all cached portraits (e.g. after changing tints or layers)
_PORTRAIT_CACHE_VERSION = "v2"

_VILLAGER_SPRITE_CODEPOINTS: dict = {
    "male": 0xE03C,
    "female": 0xE03D,
    "short": 0xE060,
    "long": 0xE061,
    "beard": 0xE062,
    "cap": 0xE063,
    "hood": 0xE064,
    "tunic": 0xE065,
    "trousers": 0xE066,
    "robe": 0xE067,
    "shoes": 0xE068,
}


# Hair-color → (R, G, B) multiply tint
_HAIR_TINTS: dict = {
    "black":  (30,  20,  20),
    "brown":  (80,  50,  30),
    "blonde": (220, 190, 100),
    "red":    (180, 60,  30),
    "gray":   (150, 150, 150),
    "grey":   (150, 150, 150),
    "white":  (230, 225, 215),
}

# Clothing color word → (R, G, B) multiply tint
_CLOTH_TINTS: dict = {
    "white":  (240, 240, 240),
    "black":  (40,  40,  40),
    "brown":  (100, 65,  35),
    "gray":   (140, 140, 140),
    "grey":   (140, 140, 140),
    "blue":   (50,  80,  180),
    "red":    (180, 40,  40),
    "green":  (40,  140, 50),
    "yellow": (220, 200, 50),
    "purple": (120, 50,  170),
    "linen":  (210, 195, 155),
    "thread": (180, 170, 140),
    "cloth":  (160, 155, 140),
    "leather":(120, 85,  50),
    "silk":   (200, 185, 215),
    "velvet": (100, 60,  120),
    "felt":   (90,  85,  80),
    "torn":   (110, 100, 90),
    "dirty":  (90,  80,  60),
    "worn":   (100, 90,  70),
    "ragged": (100, 90,  70),
    "broken": (100, 80,  50),
    "frayed": (110, 95,  70),
    "gold":   (210, 170, 40),
    "silver": (190, 195, 200),
    "simple": (155, 145, 130),
}

# Skin-tone → base sub-folder key
_SKIN_TO_BASE: dict = {
    "very pale":  "white",
    "pale":       "white",
    "fair":       "white",
    "light olive":"brown",
    "tan":        "brown",
    "brown":      "brown",
    "dark":       "black",
    "very dark":  "black",
}


def _tint_pil(img, tint_rgb: tuple):
    """Return a tinted copy of a PIL RGBA image (multiply each RGB channel)."""
    arr = np.array(img, dtype=np.float32)
    for c, t in enumerate(tint_rgb[:3]):
        arr[..., c] = arr[..., c] * (t / 255.0)
    from PIL import Image as _PILImage
    return _PILImage.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")


def _extract_cloth_tint(description: str) -> tuple | None:
    """Return the tint for the first recognised word in a clothing slot string."""
    if not description:
        return None
    for word in description.lower().split():
        if word in _CLOTH_TINTS:
            return _CLOTH_TINTS[word]
    return None


def compose_portrait(actor) -> str | None:
    """Build a composited 32×32 portrait PNG for *actor* from portrait_parts layers.

    Reads actor.knowledge for skin_tone, gender, hair_color, hair_style,
    facial_hair, torso, head and accessories slots.

    Results are cached on disk in portrait_cache/<hash>.png.
    Sets actor._portrait_path and returns the path, or None on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        print("[sprite_manager] Pillow not installed — portrait skipped.")
        return None

    know = getattr(actor, "knowledge", {})
    composite_sprite_layers = []
    composite_sprite_tints = []

    # ── Base layer ────────────────────────────────────────────────────────────
    skin       = know.get("skin_tone", "fair")
    gender     = know.get("gender", "Male")
    base_key   = _SKIN_TO_BASE.get(skin, "white")
    gender_key = "female" if gender == "Female" else "male"
    base_path  = os.path.join(_PORTRAIT_PARTS_DIR, "base", f"{base_key}_{gender_key}.png")
    if not os.path.isfile(base_path):
        base_path = os.path.join(_PORTRAIT_PARTS_DIR, "base", "white_male.png")
    if not os.path.isfile(base_path):
        return None

    # ── Cache key ─────────────────────────────────────────────────────────────
    import hashlib, json as _json
    _cache_fields = ["skin_tone", "gender", "hair_color", "hair_style",
                     "facial_hair", "torso", "legs", "feet", "head", "accessories"]
    cache_data  = {k: know.get(k) for k in _cache_fields}
    cache_data["_v"] = _PORTRAIT_CACHE_VERSION
    cache_hash  = hashlib.md5(_json.dumps(cache_data, sort_keys=True).encode()).hexdigest()[:12]
    os.makedirs(_PORTRAIT_CACHE_DIR, exist_ok=True)
    out_path = os.path.join(_PORTRAIT_CACHE_DIR, f"{cache_hash}.png")

    if os.path.isfile(out_path):
        actor._portrait_path = out_path
        return out_path

    # ── Build composite ───────────────────────────────────────────────────────
    _log = [f"base={base_key}_{gender_key}"]
    canvas = Image.open(base_path).convert("RGBA")

    # Get skin tone tint from base layer, to apply to clothing layers for better integration.
    if skin in _SKIN_TO_BASE:
        # Sample tint from the base skin layer (assuming it's a solid color).
        r, g, b, _ = canvas.getpixel((TILE_W // 2, TILE_H // 2))
        skin_tint = (r, g, b)

    if gender.lower() == "male":
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["male"])
        composite_sprite_tints.append(skin_tint)
    else:
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["female"])
        composite_sprite_tints.append(skin_tint)
        
    def _overlay(rel_path: str, tint=None) -> None:
        nonlocal canvas
        full = os.path.join(_PORTRAIT_PARTS_DIR, rel_path)
        if not os.path.isfile(full):
            _log.append(f"MISSING:{rel_path}")
            return
        layer = Image.open(full).convert("RGBA")
        if tint:
            layer = _tint_pil(layer, tint)
        merged = canvas.copy()
        merged.alpha_composite(layer)
        canvas = merged
        _log.append(f"{rel_path} tint={tint}")

    hair_color = know.get("hair_color")
    hair_tint  = _HAIR_TINTS.get(hair_color) if hair_color else None
    hair_style = know.get("hair_style", "short")

    # Torso clothing layer (below hair)
    torso_desc  = know.get("torso") or ""
    torso_lower = torso_desc.lower()
    torso_tint  = _extract_cloth_tint(torso_desc)
    if "robe" in torso_lower:
        _overlay("robe/robe.png", torso_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["robe"])
        composite_sprite_tints.append(torso_tint)
    elif any(w in torso_lower for w in ("tunic", "shirt", "jerkin")):
        _overlay(f"tunic/{gender_key}.png", torso_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["tunic"])
        composite_sprite_tints.append(torso_tint)

    # Hair
    if hair_tint and hair_color not in ("bald", "hairless"):
        # Switch for style comp
        match hair_style.lower():
            case "long":
                _overlay("hair/long.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["long"])
                composite_sprite_tints.append(hair_tint)

            case "curly":
                _overlay("hair/curly.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["long"])
                composite_sprite_tints.append(hair_tint)

            case "short":
                _overlay("hair/short.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["short"])
                composite_sprite_tints.append(hair_tint)

            case "straight":
                _overlay("hair/straight.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["short"])
                composite_sprite_tints.append(hair_tint)

            case "wavy":
                _overlay("hair/wavy.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["long"])
                composite_sprite_tints.append(hair_tint)

            case _:
                # Pass on no match, BALD!
                pass

    # Facial hair / beard
    facial_hair = know.get("facial_hair")
    if facial_hair and hair_tint:
        match facial_hair.lower():
            case "bearded":
                _overlay("facial_hair/beard.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["beard"])
                composite_sprite_tints.append(hair_tint)
            case "mustached":
                _overlay("facial_hair/mustache.png", hair_tint)
            case "goateed":
                _overlay("facial_hair/goatee.png", hair_tint)
                composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["beard"])
                composite_sprite_tints.append(hair_tint)
            case "stubbled":
                _overlay("facial_hair/stubble.png", hair_tint)
            case _:
                pass
            
    # Head gear  (on top of hair)
    head_desc  = know.get("head") or ""
    head_lower = head_desc.lower()
    head_tint  = _extract_cloth_tint(head_desc)
    if "hood" in head_lower:
        _overlay("hood/hood.png", head_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["hood"])
        composite_sprite_tints.append(head_tint)

    elif "cap" in head_lower:
        _overlay("cap/cap.png", head_tint)
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["cap"])
        composite_sprite_tints.append(head_tint)

    elif "hat" in head_lower:
        _overlay("cone_hat/cone_hat.png", head_tint)

    feet_desc = know.get("feet") or ""
    feet_lower = feet_desc.lower()
    feet_tint = _extract_cloth_tint(feet_desc)
    if "shoes" in feet_lower:
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["shoes"])
        composite_sprite_tints.append(feet_tint)
    
    legs_desc = know.get("legs") or ""
    legs_lower = legs_desc.lower()
    legs_tint = _extract_cloth_tint(legs_desc)
    if "trousers" in legs_lower or "pants" in legs_lower:
        composite_sprite_layers.append(_VILLAGER_SPRITE_CODEPOINTS["trousers"])
        composite_sprite_tints.append(legs_tint)


    # Accessories — necklace
    acc_desc  = know.get("accessories") or ""
    acc_tint  = _extract_cloth_tint(acc_desc)
    if "necklace" in acc_desc.lower():
        _overlay("necklace/necklace.png", acc_tint)

    canvas.save(out_path, "PNG")
    print(f"[portrait] {getattr(actor, 'name', '?')} → {cache_hash}.png | layers: {', '.join(_log)}")
    actor._portrait_path = out_path

    actor.char = compose_sprite(composite_sprite_layers, layer_tints=composite_sprite_tints)

    return out_path


def save_composites_sheet(path: str = "RP/composites.png") -> None:
    """Write all cached composite tiles to a PNG grid for visual inspection."""
    if not _composite_cache or _tileset is None:
        print("[sprite_manager] No composites to save.")
        return
    try:
        from PIL import Image
    except ImportError:
        print("[sprite_manager] Pillow not installed — cannot save composites sheet.")
        return
    cols = 16
    count = len(_composite_cache)
    rows = (count + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * TILE_W, rows * TILE_H), (0, 0, 0, 0))
    for i, cp in enumerate(_composite_cache.values()):
        pixels = _tileset.get_tile(cp)
        tile_img = Image.fromarray(pixels, "RGBA")
        col = i % cols
        row = i // cols
        sheet.paste(tile_img, (col * TILE_W, row * TILE_H))
    sheet.save(path)
    print(f"[sprite_manager] Saved {count} composite tile(s) to '{path}'.")
