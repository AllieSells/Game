"""Named constants for extra tileset sprites loaded from RP/extras.png.

Each constant is the chr() of the codepoint registered by sprite_manager.
Slots map to positions in extras.png reading left-to-right, top-to-bottom,
16 columns per row, 10x10 pixels per tile.

Slot 0  = row 0, col 0  -> 0xE000
Slot 1  = row 0, col 1  -> 0xE001
Slot 16 = row 1, col 0  -> 0xE010
...

Usage:
    import tile_ids
    console.print(x, y, tile_ids.VINE, fg=(34, 139, 34))
"""

# --- Slot 0: row 0, col 0 ---
VINE   = chr(0xE000)  # Green vine overlay on walls

# --- Slot 1: row 0, col 1 ---
BLOOD  = chr(0xE001)  # Blood stain on floor

# --- Slot 2: row 0, col 2 ---
MOSS   = chr(0xE002)  # Mossy patch

# --- Slot 3: row 0, col 3 ---
COBWEB = chr(0xE003)  # Cobweb corner

# --- Puddle autotile: row 32, cols 0-8 (slots 512-520, 0xE200-0xE208) ---
# 9-tile autotile set — select based on which cardinal neighbors also have liquid.
# Layout: top-left, top-middle, top-right / middle-left, center, middle-right / bottom-left, bottom-middle, bottom-right
PUDDLE_TL = chr(0xE200)  # Top-left corner     (no top, no left neighbor)
PUDDLE_TM = chr(0xE201)  # Top-middle edge     (no top neighbor)
PUDDLE_TR = chr(0xE202)  # Top-right corner    (no top, no right neighbor)
PUDDLE_ML = chr(0xE203)  # Middle-left edge    (no left neighbor)
PUDDLE_MM = chr(0xE204)  # Center / interior   (all 4 neighbors present)
PUDDLE_MR = chr(0xE205)  # Middle-right edge   (no right neighbor)
PUDDLE_BL = chr(0xE206)  # Bottom-left corner  (no bottom, no left neighbor)
PUDDLE_BM = chr(0xE207)  # Bottom-middle edge  (no bottom neighbor)
PUDDLE_BR = chr(0xE208)  # Bottom-right corner (no bottom, no right neighbor)

# --- Animated targeting cursor: row 15, cols 6 & 7 ---
# Row 15, col 6: slot = 15*16 + 6 = 246 -> 0xE0F6
# Row 15, col 7: slot = 15*16 + 7 = 247 -> 0xE0F7
CURSOR_0 = chr(0xE0F6)  # Cursor frame 0
CURSOR_1 = chr(0xE0F7)  # Cursor frame 1

# --- Cooking heat indicator: row 15, col 8 ---
# Row 15, col 8: slot = 15*16 + 8 = 248 -> 0xE0F8
HEAT_FLAME = chr(0xE0F8)  # Heat/flame sprite for cooking UI
