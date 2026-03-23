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

# Add more below as you draw them in extras.png:
# SLOT_4 = chr(0xE004)
