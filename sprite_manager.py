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
        #print(f"[sprite_manager] Composing sprite from layers {[hex(c) for c in layer_codepoints]} with scale {overlay_scale} and offset ({x_offset}, {y_offset})")
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
        #print(f"[sprite_manager] Composed sprite 0x{cp:04X} from layers {[hex(c) for c in layer_codepoints]}")
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
