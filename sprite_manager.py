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


def compose_sprite(layer_codepoints: list[int], overlay_scale: float = 1.0) -> str:
    """Alpha-composite multiple tile layers into a new tileset slot.

    Blends codepoints bottom-up (first = base, last = top layer).
    Caches results so identical combos reuse the same slot.
    Returns the chr() of the resulting codepoint.
    """
    global _composite_next, _tileset
    if _tileset is None:
        raise RuntimeError("[sprite_manager] compose_sprite called before load_extras set the tileset.")

    normalized_scale = max(0.05, float(overlay_scale))
    key = (tuple(layer_codepoints), round(normalized_scale, 4))
    if key in _composite_cache:
        return chr(_composite_cache[key])

    base = _tileset.get_tile(layer_codepoints[0]).astype(np.float32).copy()
    for cp in layer_codepoints[1:]:
        overlay_pixels = _tileset.get_tile(cp)
        if normalized_scale != 1.0:
            overlay_pixels = _scale_overlay_tile(overlay_pixels, normalized_scale)
        overlay = overlay_pixels.astype(np.float32)
        alpha = overlay[..., 3:4] / 255.0
        base[..., :3] = overlay[..., :3] * alpha + base[..., :3] * (1.0 - alpha)
        base[..., 3] = np.maximum(base[..., 3], overlay[..., 3])

    result = base.astype(np.uint8)
    cp = _composite_next
    _tileset.set_tile(cp, result)
    _composite_cache[key] = cp
    _composite_next += 1
    print(f"[sprite_manager] Composed sprite 0x{cp:04X} from layers {[hex(c) for c in layer_codepoints]}")
    return chr(cp)


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
