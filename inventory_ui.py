"""inventory_ui.py – Combined inventory + equipment grid.

Rendered to a dedicated 40×25 console that main.py blits at FULL-WINDOW scale
via inv_console_renderer, giving (window_w/40) × (window_h/25) px characters
— 32×32 px at the default 1280×800 window, vs the 16×16 px UI layer.

Layout (40 wide × 25 tall console)
────────────────────────────────────
 Col 0      : left border
 Cols 1–19  : inventory grid (6 cols × 3 wide = 18) + 1-col spacer
 Col 20     : vertical divider
 Cols 21–38 : equipment slots panel (18 wide)
 Col 39     : right border
 Row 0      : outer top border (title embedded)
 Row 1      : [tab] [tab] [tab] [│ Equipment header]
 Row 2      : horizontal separator
 Rows 3–20 : 6×6 grid of 3×3 item cells  │  slot list rows
 Row 21     : horizontal separator (full width)
 Rows 22–23: selected-item info strip
 Row 24     : outer bottom border

Mouse mapping (event.tile is in 80×50 UI space):
  inv_x = event.tile.x // 2    (0–39)
  inv_y = event.tile.y // 2    (0–24)
"""

from __future__ import annotations

from typing import Optional, List, Tuple, TYPE_CHECKING

import tcod
import tcod.event
import color
import sounds
import actions

from input_handlers import PopupEventHandler, ItemContextMenu, CONFIRM_KEYS
from equipment_types import EquipmentType

if TYPE_CHECKING:
    from engine import Engine
    from entity import Item


# ─────────────────────────────────────────────────────────────────────────────
# Layout — 60×36 chrome console blitted at (10,7) into 80×50; 5×9 grid
# console GPU-rendered at 3× over the item area → 48×48 px item tiles.
# ─────────────────────────────────────────────────────────────────────────────
_C_W = 60   # chrome panel width
_C_H = 36   # chrome panel height

# Where the panel sits on the 80×50 main console (centred)
_INV_BLIT_X: int = (80 - _C_W) // 2   # = 10
_INV_BLIT_Y: int = (50 - _C_H) // 2   # = 7

# Inventory grid — separate 5×9 console rendered at 3× (48×48 px per item)
_GRID_SCALE   = 3    # GPU scale factor (integer)
_GRID_COL_ORI = 1    # panel col where grid starts
_GRID_ROW_ORI = 3    # panel row where grid starts (0=frame, 1=tabs, 2=sep)
_GRID_COLS    = 7    # grid columns  (7 × 3 = 21 panel cols)
_GRID_ROWS    = 9    # grid rows     (9 × 3 = 27 panel rows, fills rows 3–29)

# Divider at col 1 + 7×3 = 22; equipment panel starts at 23
_DIV_X       = 22   # vertical divider column in chrome panel
_EQ_X        = 23   # left edge of equipment panel (body diagram area)

# Equipment body diagram — GPU-rendered at 3× in its own eq_grid_console (12×9 cells).
# 12 cols × 3 = 36 tiles wide; 9 rows × 3 = 27 tiles tall → same height as the inv grid.
_EQ_GRID_COLS  = 11
_EQ_GRID_ROWS  = 9
# Origin in 80×50 tile coords (no centering — fills the full grid-row band)
_EQ_GRID_ORI_X: int = _INV_BLIT_X + _EQ_X                   # = 33
_EQ_GRID_ORI_Y: int = _INV_BLIT_Y + _GRID_ROW_ORI            # = 10
# Slot grid positions (col, row) in eq_grid — viewer's POV.
# 12 wide × 9 tall grid; slots arranged as a body silhouette:
#   row 0 : Head
#   row 1 : R.Arm  Torso  L.Arm
#   row 3 : R.Hand        L.Hand   Back
#   row 6 : R.Leg         L.Leg
#   row 8 : R.Foot        L.Foot
_EQ_SLOT_GRID_POS: List[Tuple[int, int]] = [
    (7, 3),  # 0: R.Hand  — R4 col 7
    (3, 3),  # 1: L.Hand  — R4 col 3
    (5, 0),  # 2: Head    — R1 col 5
    (5, 2),  # 3: Torso   — R3 col 5
    (4, 1),  # 4: L.Arm   — R2 col 4  (flanking head, shoulder position)
    (6, 1),  # 5: R.Arm   — R2 col 6  (flanking head, shoulder position)
    (4, 5),  # 6: L.Leg   — R6 col 4
    (6, 5),  # 7: R.Leg   — R6 col 6
    (4, 7),  # 8: L.Foot  — R8 col 4
    (6, 7),  # 9: R.Foot  — R8 col 6
    (2, 6),  # 10: Back   — R7 col 2
]
_EQ_GRID_HIT: dict = {pos: i for i, pos in enumerate(_EQ_SLOT_GRID_POS)}

# Maps each EQ slot index to the corresponding BodyPartType for damage display.
# Import deferred to avoid circular dependency — used inside _fill_eq_grid_console.
_EQ_SLOT_BODY_PART_NAME = [
    "RIGHT_HAND",  # 0: R.Hand
    "LEFT_HAND",   # 1: L.Hand
    "HEAD",        # 2: Head
    "TORSO",       # 3: Torso
    "LEFT_ARM",    # 4: L.Arm
    "RIGHT_ARM",   # 5: R.Arm
    "LEFT_LEG",    # 6: L.Leg
    "RIGHT_LEG",   # 7: R.Leg
    "LEFT_FOOT",   # 8: L.Foot
    "RIGHT_FOOT",  # 9: R.Foot
    "TORSO",       # 10: Back (shares torso body part)
]

# Info strip (grid rows 3–29 = 27 rows, separator at 30, info at 31)
_INFO_SEP_Y = 30    # separator row above info strip
_INFO_Y     = 31    # first info content row
#  rows 31-34 = info lines; row 35 = bottom frame edge

# Persistent alt damage-view toggle — retained across inventory opens.
_ALT_DAMAGE_VIEW: bool = False

# ── Colour palette ───────────────────────────────────────────────────────────
# Background layers
_BG           = (25, 18, 12)   # outer background — above BLEND >16 threshold so chrome is opaque
_PANEL_BG     = (22, 15, 10)   # panel interior
_CELL_EMPTY   = (42, 30, 16)   # empty cell interior (visible warm dark)
_CELL_FILLED  = (65, 48, 24)   # occupied cell interior (lighter brown)
_CELL_SEL     = (115, 86, 28)  # selected cell interior (bright amber)
_CELL_DRAG    = (20, 14,  6)   # source cell while dragging

# Borders & structure
_BORDER_DIM   = (120, 90, 40)  # normal grid border
_BORDER_BRIGHT= (220,170, 60)  # bright selected-cell border
_DIV_FG       = (100, 78, 35)  # divider colour

# Text
_TITLE_FG     = (255, 220, 80)  # title / headers
_TAB_ACT_FG   = (255, 220, 80)
_TAB_ACT_BG   = (60,  44, 14)
_TAB_INA_FG   = (130, 100, 50)
_TAB_INA_BG   = (22,  15, 10)
_SLOT_LABEL   = (180, 140, 70)  # equipment slot names
_SLOT_EMPTY_V = ( 60,  48, 22)  # placeholder text for empty slot
_HINT_FG      = ( 80,  62, 30)  # bottom hint text
_INFO_NAME    = (230, 200, 110) # item name in info strip
_INFO_STAT    = (170, 145,  90) # stat text in info strip


# Equipment slots: (label, list of EquipmentType that can fill the slot)
_EQ_SLOTS: List[Tuple[str, List[EquipmentType]]] = [
    ("R.Hand", [EquipmentType.WEAPON, EquipmentType.SHIELD,
                EquipmentType.RANGED, EquipmentType.PROJECTILE]),
    ("L.Hand", [EquipmentType.WEAPON, EquipmentType.SHIELD,
                EquipmentType.RANGED, EquipmentType.PROJECTILE]),
    ("Head",   [EquipmentType.HELMET]),
    ("Torso",  [EquipmentType.ARMOR]),
    ("L.Arm",  [EquipmentType.GAUNTLETS]),
    ("R.Arm",  [EquipmentType.GAUNTLETS]),
    ("L.Leg",  [EquipmentType.LEGGINGS]),
    ("R.Leg",  [EquipmentType.LEGGINGS]),
    ("L.Foot", [EquipmentType.BOOTS]),
    ("R.Foot", [EquipmentType.BOOTS]),
    ("Back",   [EquipmentType.BACKPACK]),
]


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


class InventoryGridUI(PopupEventHandler):
    """Combined inventory grid + equipment panel with 2× GPU-scaled item tiles."""

    # Uses targeted 2× GPU grid overlay, not a full-window scaled console.
    _is_scaled_inventory = False

    def __init__(self, engine: "Engine") -> None:
        super().__init__(engine)

        engine.context_hints = [
            ("RClick", "Options"),
            ("Drag",   "Organise"),
            ("Esc",    "Close"),
        ]

        # Chrome panel (borders, tabs, eq, info): blitted at (_INV_BLIT_X, _INV_BLIT_Y).
        self._inv_console = tcod.console.Console(_C_W, _C_H, order="F")
        # Item grid (7×9): GPU-rendered at 3× by main.py → 48×48 px per item.
        self._grid_console = tcod.console.Console(_GRID_COLS, _GRID_ROWS, order="F")
        # Quantity label overlay: same area as grid at 1× scale (21×27 tiles).
        # ADD-rendered after the grid so "x3" labels glow over the item sprites.
        self._qty_console = tcod.console.Console(_GRID_COLS * _GRID_SCALE, _GRID_ROWS * _GRID_SCALE, order="F")
        # Equipment body diagram (12×5): GPU-rendered at 3× → 48×48 px per slot.
        self._eq_grid_console = tcod.console.Console(_EQ_GRID_COLS, _EQ_GRID_ROWS, order="F")
        # Enchantment label overlay for the equipment body diagram — same pixel area
        # as _eq_grid_console but at 1× (33×27 tiles), ADD-rendered so each slot
        # has a 3×3 tile block for text labels.
        self._eq_qty_console = tcod.console.Console(_EQ_GRID_COLS * _GRID_SCALE, _EQ_GRID_ROWS * _GRID_SCALE, order="F")
        # Drag ghost: 1×1 console GPU-rendered at 3× (48×48 px) at cursor position.
        self._drag_console = tcod.console.Console(1, 1, order="F")

        # Category tabs (short names — all four fit: All+Eq+Use+Misc = 15 chars)
        self._categories = [
            ("All",  lambda i: True),
            ("Eq",   lambda i: getattr(i, "equippable", None) is not None),
            ("Use",  lambda i: getattr(i, "consumable", None) is not None),
            ("Misc", lambda i: getattr(i, "equippable", None) is None
                               and getattr(i, "consumable", None) is None),
        ]
        self._category = 0

        # Selection state
        self._sel_inv: int = 0   # flat index into filtered groups; -1 = none
        self._sel_eq:  int = -1  # index into _EQ_SLOTS; -1 = none

        # Scroll (inventory overflows when > _GRID_COLS*_GRID_ROWS slots)
        self._scroll = 0          # page offset (rows)

        # Drag state
        self._drag_item:     Optional["Item"] = None
        self._drag_src_type: Optional[str]    = None   # 'inv' | 'eq'
        self._drag_src_idx:  Optional[int]    = None
        self._drag_tile:     Tuple[int, int]  = (0, 0) # last known 80×50 tile coord
        self._drag_pixel:    Tuple[int, int]  = (0, 0) # sub-tile pixel coord

        # Tab-hit-test regions (rebuilt each render)
        self._tab_regions: List[Tuple[int, int, int]] = []  # [(x0, x1, cat_i), ...]

        # Panel bounds for GPU-direct copy (covers only the panel, game visible outside).
        self._set_popup_bounds(_INV_BLIT_X, _INV_BLIT_Y, _C_W, _C_H)

    # ─────────────────────────────────────────────────────────────────────────
    # Coordinate helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_inv(tx: int, ty: int) -> Tuple[int, int]:
        """Map an 80×50 event tile coord to the 60×36 panel space."""
        return tx - _INV_BLIT_X, ty - _INV_BLIT_Y

    def _hit_inv_cell(self, tx: int, ty: int) -> Optional[Tuple[int, int]]:
        """Return (col, row) grid cell, or None.
        Each slot occupies _GRID_SCALE×_GRID_SCALE panel tiles."""
        ix, iy = self._to_inv(tx, ty)
        col = (ix - _GRID_COL_ORI) // _GRID_SCALE
        row = (iy - _GRID_ROW_ORI) // _GRID_SCALE
        if 0 <= col < _GRID_COLS and 0 <= row < _GRID_ROWS:
            return col, row
        return None

    def _cell_to_idx(self, col: int, row: int) -> int:
        """Grid (col, row) → flat inventory index in the current filtered list."""
        return (self._scroll + row) * _GRID_COLS + col

    @property
    def _drag_dest_tiles(self) -> Tuple[int, int, int, int]:
        """Drag ghost position in 80×50 tile units, centred on the mouse cursor."""
        tx, ty = self._drag_tile
        # Centre the 3×3 sprite on the cursor
        dx = tx - _GRID_SCALE // 2
        dy = ty - _GRID_SCALE // 2
        dx = _clamp(dx, 0, 80 - _GRID_SCALE)
        dy = _clamp(dy, 0, 50 - _GRID_SCALE)
        return (dx, dy, _GRID_SCALE, _GRID_SCALE)

    @property
    def _drag_dest_pixels(self) -> Tuple[int, int, int, int]:
        """Drag ghost pixel rect, centred on the actual pixel cursor position."""
        px, py = self._drag_pixel
        size   = _GRID_SCALE * 16  # 3 tiles × 16 px/tile = 48 px
        return (px - size // 2, py - size // 2, size, size)

    def _fill_drag_console(self) -> None:
        """Write the dragged item glyph into the 1×1 drag console.
        Black bg + ADD blend in main.py = transparent bg, glyph only."""
        if self._drag_item is None:
            return
        item_ch  = getattr(self._drag_item, "char", "?")
        item_col = getattr(self._drag_item, "color", (200, 180, 100))
        self._drag_console.print(0, 0, item_ch, fg=item_col, bg=(0, 0, 0))

    @property
    def _grid_dest_tiles(self) -> Tuple[int, int, int, int]:
        """Grid overlay position in 80×50 tile units: (tx, ty, tw, th).
        main.py multiplies by base_tile_w/h to get pixel dest for GPU copy."""
        return (
            _INV_BLIT_X + _GRID_COL_ORI,          # 11
            _INV_BLIT_Y + _GRID_ROW_ORI,          # 10
            _GRID_COLS * _GRID_SCALE,              # 15 (3 panel tiles per col)
            _GRID_ROWS * _GRID_SCALE,              # 27 (3 panel tiles per row)
        )

    def _hit_eq_slot(self, tx: int, ty: int) -> Optional[int]:
        """Return equipment slot index from body diagram hit-test, or None."""
        col = (tx - _EQ_GRID_ORI_X) // _GRID_SCALE
        row = (ty - _EQ_GRID_ORI_Y) // _GRID_SCALE
        if 0 <= col < _EQ_GRID_COLS and 0 <= row < _EQ_GRID_ROWS:
            return _EQ_GRID_HIT.get((col, row))
        return None

    def _hit_category_tab(self, tx: int, ty: int) -> Optional[int]:
        """Return category index if click lands on a tab, else None."""
        _, iy = self._to_inv(tx, ty)
        if iy != 1:
            return None
        ix, _ = self._to_inv(tx, ty)
        for x0, x1, cat_i in self._tab_regions:
            if x0 <= ix < x1:
                return cat_i
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Data helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_filtered(self):
        """Return filtered display-group list for current category.
        Equipped items are excluded — they show in the body diagram only."""
        eq = self.engine.player.equipment
        groups = self.engine.player.inventory.get_display_groups()
        fn = self._categories[self._category][1]
        return [g for g in groups if fn(g["item"]) and not eq.item_is_equipped(g["item"])]

    def _get_slot_item(self, slot_idx: int) -> Optional["Item"]:
        """Return the item at *slot_idx* if it passes the current category filter
        and is not equipped, otherwise return None."""
        inv = self.engine.player.inventory
        if slot_idx < 0 or slot_idx >= len(inv.item_slots):
            return None
        rep = inv.item_slots[slot_idx]
        if rep is None:
            return None
        fn = self._categories[self._category][1]
        if not fn(rep):
            return None
        if self.engine.player.equipment.item_is_equipped(rep):
            return None
        return rep

    def _get_eq_item(self, slot_i: int) -> Optional["Item"]:
        """Get the item equipped in _EQ_SLOTS[slot_i], or None.
        Logic mirrors EquipmentSlot.get_equipped_item in equipment_ui.py."""
        slot_label, eq_types = _EQ_SLOTS[slot_i]
        eq = self.engine.player.equipment

        hand_map = {"R.Hand": "right hand", "L.Hand": "left hand"}

        for et in eq_types:
            if et in (EquipmentType.WEAPON, EquipmentType.SHIELD,
                      EquipmentType.RANGED, EquipmentType.PROJECTILE):
                # Hand slots: look up the specific hand, never shared between hands.
                if slot_label in hand_map:
                    hand_name = hand_map[slot_label]
                    # grasped_items (legacy)
                    item = eq.grasped_items.get(hand_name)
                    if item and getattr(item, "equippable", None) and item.equippable.equipment_type == et:
                        return item
                    # body_part_coverage (new system — equip_item writes here)
                    item = eq.body_part_coverage.get(hand_name)
                    if item and getattr(item, "equippable", None) and item.equippable.equipment_type == et:
                        return item
                else:
                    # Non-hand ranged/projectile slots: check all grasped then coverage
                    for item in eq.grasped_items.values():
                        if item and getattr(item, "equippable", None) and item.equippable.equipment_type == et:
                            return item
                    for item in eq.body_part_coverage.values():
                        if item and getattr(item, "equippable", None) and item.equippable.equipment_type == et:
                            return item
            else:
                # Armour slots: check equipped_items first, then body_part_coverage.
                item = eq.equipped_items.get(et) or eq.equipped_items.get(et.name)
                if item:
                    return item
                for item in eq.body_part_coverage.values():
                    if item and getattr(item, "equippable", None) and item.equippable.equipment_type == et:
                        return item
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Rendering
    # ─────────────────────────────────────────────────────────────────────────

    def on_render(self, console: tcod.Console) -> None:
        """Render chrome panel into console; fill grid console for GPU 3× overlay."""
        super().on_render(console)

        self._grid_console.clear()
        self._fill_grid_console()

        self._qty_console.clear()
        self._fill_qty_console()

        self._eq_grid_console.clear()
        self._fill_eq_grid_console()

        self._eq_qty_console.clear()
        self._fill_eq_qty_console()

        if self._drag_item is not None:
            self._drag_console.clear()
            self._fill_drag_console()

        c = self._inv_console
        c.clear()
        self._render_to_console(c)
        c.blit(console, _INV_BLIT_X, _INV_BLIT_Y)

    def _render_to_console(self, c: tcod.Console) -> None:
        """Fill _inv_console with the full inventory+equipment UI."""
        W, H = _C_W, _C_H
        bf = _BORDER_DIM

        # ── Solid background + outer frame ───────────────────────────────────────
        c.tiles_rgb["bg"][:, :] = _BG
        c.tiles_rgb["fg"][:, :] = _BG
        c.tiles_rgb["ch"][:, :] = ord(" ")
        c.draw_frame(0, 0, W, H, fg=bf, bg=_BG)

        # ── Title bar (row 0 inside frame = row 0, cols 1..W-2) ──────────────────
        c.print(1, 0, " Inventory ", fg=_TITLE_FG, bg=_BG)
        _eq_title = " Equipment "
        c.print(_EQ_X + (_C_W - _EQ_X - len(_eq_title)) // 2, 0, _eq_title, fg=_TITLE_FG, bg=_BG)

        # Weight readout in the upper-right of the equipment panel
        _inv_wt  = self.engine.player.inventory
        _cur_w   = _inv_wt.current_weight
        _max_w   = _inv_wt.max_weight
        _over    = _cur_w > _max_w
        _wt_fg   = (220, 60, 40) if _over else (140, 110, 55)
        _wt_str  = f"{_cur_w:.1f}/{_max_w:.0f}kg "
        c.print(W - 1 - len(_wt_str), 0, _wt_str, fg=_wt_fg, bg=_BG)

        # ── Category tabs (row 1, left panel only) ───────────────────────────
        self._tab_regions = []
        tab_x = 1
        for i, (name, _) in enumerate(self._categories):
            label = name   # no padding; short names fit the 15-col left panel
            is_active = i == self._category
            c.print(tab_x, 1, label,
                    fg=_TAB_ACT_FG if is_active else _TAB_INA_FG,
                    bg=_TAB_ACT_BG if is_active else _PANEL_BG)
            self._tab_regions.append((tab_x, tab_x + len(label), i))
            tab_x += len(label) + 1

        # ── Vertical divider (stops at info-strip separator) ────────────────
        c.print(_DIV_X, 0, "┬", fg=bf, bg=_BG)
        for y in range(1, _INFO_SEP_Y):
            c.print(_DIV_X, y, "│", fg=bf, bg=_BG)

        # ── Horizontal separator at row 2 (below tabs, left panel only) ─────────
        for x in range(1, _DIV_X):
            c.print(x, 2, "─", fg=bf, bg=_BG)
        c.print(0,      2, "├", fg=bf, bg=_BG)
        c.print(_DIV_X, 2, "┤", fg=bf, bg=_BG)

        # ── Separator above info strip ────────────────────────────────────────
        for x in range(1, W - 1):
            c.print(x, _INFO_SEP_Y, "─", fg=bf, bg=_BG)
        c.print(0,       _INFO_SEP_Y, "├", fg=bf, bg=_BG)
        c.print(_DIV_X,  _INFO_SEP_Y, "┴", fg=bf, bg=_BG)
        c.print(W - 1,   _INFO_SEP_Y, "┤", fg=bf, bg=_BG)

        # ── Scroll indicators (scroll already clamped by _fill_grid_console) ──────
        inv    = self.engine.player.inventory
        self._resync_inv_slots()
        n_slots  = len(inv.item_slots)
        _max_s   = max(0, -(-n_slots // _GRID_COLS) - _GRID_ROWS)
        if self._scroll > 0:
            c.print(_DIV_X, _GRID_ROW_ORI, "↑", fg=_BORDER_BRIGHT, bg=_BG)
        if self._scroll < _max_s:
            c.print(_DIV_X, _INFO_SEP_Y - 1, "↓", fg=_BORDER_BRIGHT, bg=_BG)

        # ── Carry-weight bar (below inventory grid, above info sep) ──────────
        cur_w  = inv.current_weight
        max_w  = inv.max_weight
        ratio  = min(1.0, cur_w / max_w) if max_w > 0 else 0.0
        bar_w  = _DIV_X - 2          # cols 1.._DIV_X-1
        filled = int(ratio * bar_w)
        over   = ratio >= 1.0
        bar_fg = (220, 60, 40) if over else (180, 140, 60)
        bar_str = ("█" * filled) + ("░" * (bar_w - filled))
        c.print(1, _INFO_SEP_Y - 2, bar_str[:bar_w], fg=bar_fg, bg=_BG)
        left_lbl  = "Weight"
        right_lbl = f"{cur_w:.1f} / {max_w:.0f} kg"
        # right-align the values within the bar width
        gap = bar_w - len(left_lbl) - len(right_lbl)
        wt_line = left_lbl + (" " * max(1, gap)) + right_lbl
        c.print(1, _INFO_SEP_Y - 3, wt_line[:bar_w], fg=bar_fg, bg=_BG)

        # ── Punch transparent holes for context-menu BLEND path ──────────────
        # Inventory grid hole
        _hx1 = _GRID_COL_ORI
        _hx2 = _GRID_COL_ORI + _GRID_COLS * _GRID_SCALE
        _hy1 = _GRID_ROW_ORI
        _hy2 = _GRID_ROW_ORI + _GRID_ROWS * _GRID_SCALE
        c.tiles_rgb["bg"][_hx1:_hx2, _hy1:_hy2] = 0
        c.tiles_rgb["fg"][_hx1:_hx2, _hy1:_hy2] = 0
        c.tiles_rgb["ch"][_hx1:_hx2, _hy1:_hy2] = ord(" ")
        # Equipment body diagram hole (right panel, rows 5–19 in chrome)
        _ehx1 = _EQ_X
        _ehx2 = _EQ_X + _EQ_GRID_COLS * _GRID_SCALE   # = 59 (stops before right border)
        _ehy1 = _EQ_GRID_ORI_Y - _INV_BLIT_Y           # = 5 (chrome row)
        _ehy2 = _ehy1 + _EQ_GRID_ROWS * _GRID_SCALE    # = 20
        c.tiles_rgb["bg"][_ehx1:_ehx2, _ehy1:_ehy2] = 0
        c.tiles_rgb["fg"][_ehx1:_ehx2, _ehy1:_ehy2] = 0
        c.tiles_rgb["ch"][_ehx1:_ehx2, _ehy1:_ehy2] = ord(" ")

        # ── Content panels ────────────────────────────────────────────────────
        self._draw_info_strip(c)

    def _fill_grid_console(self) -> None:
        """Fill self._grid_console with item glyphs using slot-based positioning."""
        gc  = self._grid_console
        inv = self.engine.player.inventory
        self._resync_inv_slots()

        n_slots    = len(inv.item_slots)
        total_rows = max(1, -(-n_slots // _GRID_COLS))
        max_scroll = max(0, total_rows - _GRID_ROWS)
        self._scroll = _clamp(self._scroll, 0, max_scroll)

        for row in range(_GRID_ROWS):
            for col in range(_GRID_COLS):
                slot_idx    = (self._scroll + row) * _GRID_COLS + col
                item        = self._get_slot_item(slot_idx)
                is_filled   = item is not None
                is_sel      = (slot_idx == self._sel_inv)
                is_drag_src = (self._drag_src_type == "inv" and self._drag_src_idx == slot_idx)

                cell_bg = (_CELL_DRAG   if is_drag_src
                           else _CELL_SEL    if is_sel
                           else _CELL_FILLED if is_filled
                           else _CELL_EMPTY)

                if is_filled:
                    item_ch   = getattr(item, "char", "?")
                    item_col  = getattr(item, "color", (200, 180, 100))
                    rar_col   = getattr(item, "rarity_color", cell_bg)
                    tinted_bg = tuple(min(255, int(b * 75 // 100 + r * 25 // 100))
                                      for b, r in zip(cell_bg, rar_col))
                    if is_drag_src:
                        item_col = tuple(max(0, v - 80) for v in item_col)
                    gc.print(col, row, item_ch, fg=item_col, bg=tinted_bg)
                else:
                    gc.print(col, row, "·", fg=_SLOT_EMPTY_V, bg=cell_bg)

        # (scroll indicators are drawn in _render_to_console after this runs)

    @property
    def _qty_grid_dest_tiles(self) -> Tuple[int, int, int, int]:
        """Quantity overlay position — same area as grid but at 1× (no GPU scaling)."""
        gdt = self._grid_dest_tiles
        return (gdt[0], gdt[1], gdt[2], gdt[3])

    def _fill_qty_console(self) -> None:
        """Write stack-count labels into the quantity overlay console.

        The console is the same pixel area as the item grid but rendered at 1×
        so each inventory cell (3×3 tiles here) holds a readable text label.
        Black bg is transparent under ADD blend.
        """
        gc  = self._qty_console
        inv = self.engine.player.inventory

        # Build a fast item→quantity map from the display groups.
        qty_map: dict = {}
        for g in inv.get_display_groups():
            qty_map[id(g['item'])] = g['quantity']

        gc.tiles_rgb['bg'][:, :] = 0
        gc.tiles_rgb['fg'][:, :] = 0
        gc.tiles_rgb['ch'][:, :] = ord(' ')

        for row in range(_GRID_ROWS):
            for col in range(_GRID_COLS):
                slot_idx = (self._scroll + row) * _GRID_COLS + col
                item     = self._get_slot_item(slot_idx)
                if item is None:
                    continue
                px = col * _GRID_SCALE
                py = row * _GRID_SCALE
                # Stack count — top-left, gold
                qty = qty_map.get(id(item), 1)
                if qty > 1:
                    gc.print(px, py, f"x{qty}", fg=(255, 230, 120), bg=(0, 0, 0))
                # Enchantment level — bottom-right, cyan
                enc = getattr(item, 'enchantment_level', 0)
                if enc and enc > 0:
                    import roman as _roman
                    enc_label = f"+{_roman.toRoman(enc)}".rjust(_GRID_SCALE)
                    gc.print(px, py + _GRID_SCALE - 1, enc_label,
                             fg=(120, 200, 255), bg=(0, 0, 0))

    @property
    def _eq_grid_dest_tiles(self) -> Tuple[int, int, int, int]:
        """Equipment body grid position in 80×50 tile units for GPU copy."""
        return (_EQ_GRID_ORI_X, _EQ_GRID_ORI_Y,
                _EQ_GRID_COLS * _GRID_SCALE, _EQ_GRID_ROWS * _GRID_SCALE)

    def _fill_eq_qty_console(self) -> None:
        """Write enchantment labels onto the equipment body diagram overlay.

        Same pixel area as _eq_grid_console but at 1× so each 3×3 tile block
        corresponds to one body slot. ADD blend — black bg is transparent.
        """
        gc  = self._eq_qty_console
        gc.tiles_rgb['bg'][:, :] = 0
        gc.tiles_rgb['fg'][:, :] = 0
        gc.tiles_rgb['ch'][:, :] = ord(' ')
        for i in range(len(_EQ_SLOTS)):
            item = self._get_eq_item(i)
            if item is None:
                continue
            enc = getattr(item, 'enchantment_level', 0)
            if not enc or enc <= 0:
                continue
            import roman as _roman
            col, row  = _EQ_SLOT_GRID_POS[i]
            px        = col * _GRID_SCALE
            py        = row * _GRID_SCALE
            enc_label = f"+{_roman.toRoman(enc)}".rjust(_GRID_SCALE)
            gc.print(px, py + _GRID_SCALE - 1, enc_label,
                     fg=(120, 200, 255), bg=(0, 0, 0))

    def _fill_eq_grid_console(self) -> None:
        """Fill _eq_grid_console (12×5) with body-diagram slot icons at 3× scale.

        Rendered with ADD blend in main.py:
          - Non-slot cells have bg=(0,0,0) → add 0 → body PNG shows through.
          - Slot cells have coloured bg    → additive glow over the PNG.
        """
        gc = self._eq_grid_console
        # ALL cells start as pure black (transparent under ADD blend)
        gc.tiles_rgb["bg"][:, :] = (0, 0, 0)
        gc.tiles_rgb["fg"][:, :] = (0, 0, 0)
        gc.tiles_rgb["ch"][:, :] = ord(" ")

        # Build damage map from player body parts (0.0 = healthy, 1.0 = destroyed)
        _bp_damage: dict = {}
        try:
            from components.body_parts import BodyPartType as _BPT
            bp_comp = getattr(getattr(self.engine.player, 'body_parts', None), 'body_parts', None)
            if bp_comp:
                for _bpt, _bp in bp_comp.items():
                    _bp_damage[_bpt.name] = _bp.damage_level_float
        except Exception:
            pass

        # Draw slot cells on top
        for i, (label, _) in enumerate(_EQ_SLOTS):
            col, row    = _EQ_SLOT_GRID_POS[i]
            item        = self._get_eq_item(i)
            is_sel      = (i == self._sel_eq)
            is_drag_src = (self._drag_src_type == "eq" and self._drag_src_idx == i)

            if is_sel:
                cell_bg = _CELL_SEL
            elif is_drag_src:
                cell_bg = _CELL_DRAG
            elif item is not None:
                rar_col = getattr(item, "rarity_color", _CELL_FILLED)
                cell_bg = tuple(min(255, b * 75 // 100 + r * 25 // 100)
                                for b, r in zip(_CELL_FILLED, rar_col))
            else:
                cell_bg = _CELL_EMPTY

            if item and not is_drag_src:
                glyph     = getattr(item, "char", "?")
                glyph_col = getattr(item, "color", (200, 180, 100))
                gc.print(col, row, glyph, fg=glyph_col, bg=cell_bg)
            else:
                dot_col = (20, 14, 6) if is_drag_src else _SLOT_EMPTY_V
                gc.print(col, row, "·", fg=dot_col, bg=cell_bg)

    def _draw_info_strip(self, c: tcod.Console) -> None:
        """Show selected item name + stats/hints in the bottom strip."""
        item: Optional["Item"] = None
        slot_label: Optional[str] = None
        if 0 <= self._sel_inv:
            item = self._get_slot_item(self._sel_inv)
        elif 0 <= self._sel_eq < len(_EQ_SLOTS):
            slot_label = _EQ_SLOTS[self._sel_eq][0]
            item = self._get_eq_item(self._sel_eq)

        if item is None:
            if slot_label is not None:
                # Show empty slot info + body part damage
                c.print(2, _INFO_Y, f"[{slot_label}]: empty",
                        fg=_SLOT_EMPTY_V, bg=_BG)
                _dmg_text, _dmg_col = self._get_slot_damage_info(self._sel_eq)
                if _dmg_text:
                    c.print(2, _INFO_Y + 1, _dmg_text, fg=_dmg_col, bg=_BG)
                else:
                    c.print(2, _INFO_Y + 1, "Drag an item here to equip it",
                            fg=_HINT_FG, bg=_BG)
            else:
                c.print(2, _INFO_Y + 1,
                        "RClick: context  |  Esc: close",
                        fg=_HINT_FG, bg=_BG)
            return

        # Name (prefix with slot label when viewing from equipment diagram)
        prefix = f"[{slot_label}] " if slot_label else ""
        name = (prefix + item.name)[:(_C_W - 4)]
        c.print(2, _INFO_Y, name,
                fg=getattr(item, "rarity_color", (220, 190, 120)), bg=_BG)

        # One-line stat summary
        parts: list[str] = []
        item_w = getattr(item, 'weight', None)
        if isinstance(item_w, (int, float)) and item_w > 0:
            parts.append(f"{item_w:.2g}kg")
        if getattr(item, "equippable", None):
            eq = item.equippable
            if getattr(eq, "power_bonus",   0): parts.append(f"Pwr:{eq.power_bonus:+}")
            if getattr(eq, "defense_bonus", 0): parts.append(f"Def:{eq.defense_bonus:+}")
            is_e = self.engine.player.equipment.item_is_equipped(item)
            parts.append("Equipped" if is_e else "Not Equipped")
        elif getattr(item, "consumable", None):
            parts.append("Consumable — Enter/RClick to use")
        else:
            parts.append("Miscellaneous")

        stat_str = "  ".join(parts)[:(_C_W - 4)]
        c.print(2, _INFO_Y + 1, stat_str, fg=_INFO_STAT, bg=_BG)

        # Body-part damage (only shown for equipment slots)
        if slot_label is not None:
            _dmg_text, _dmg_col = self._get_slot_damage_info(self._sel_eq)
            if _dmg_text:
                c.print(2, _INFO_Y + 2, _dmg_text, fg=_dmg_col, bg=_BG)

    def _get_slot_damage_info(self, slot_i: int):
        """Return (text, colour) for body-part damage at eq slot index, or ('', None)."""
        if slot_i < 0 or slot_i >= len(_EQ_SLOT_BODY_PART_NAME):
            return '', None
        part_name = _EQ_SLOT_BODY_PART_NAME[slot_i]
        try:
            bp_comp = getattr(getattr(self.engine.player, 'body_parts', None), 'body_parts', None)
            if not bp_comp:
                return '', None
            from components.body_parts import BodyPartType as _BPT
            bpt = _BPT[part_name]
            bp  = bp_comp.get(bpt)
            if bp is None:
                return '', None
            dmg_text  = bp.damage_level_text   # 'healthy' / 'damaged' / ... / 'destroyed'
            dmg_ratio = bp.current_hp / bp.max_hp if bp.max_hp > 0 else 0.0
            if dmg_text == 'healthy':
                return f"{part_name.replace('_',' ').title()}: healthy", (80, 160, 80)
            colour = (
                (220, 200, 60)  if dmg_ratio > 0.75 else
                (220, 140, 40)  if dmg_ratio > 0.50 else
                (200,  80, 20)  if dmg_ratio > 0.25 else
                (190,  30, 20)
            )
            return f"● {part_name.replace('_',' ').title()}: {dmg_text}", colour
        except Exception:
            return '', None

    # ─────────────────────────────────────────────────────────────────────────
    # Event handlers
    # ─────────────────────────────────────────────────────────────────────────

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        super().ev_mousemotion(event)
        tx, ty = int(event.tile.x), int(event.tile.y)
        self._drag_tile  = (tx, ty)
        self._drag_pixel = (int(event.pixel.x), int(event.pixel.y))

        # Update hover selection
        cell = self._hit_inv_cell(tx, ty)
        if cell is not None:
            col, row = cell
            slot_idx = self._cell_to_idx(col, row)
            item     = self._get_slot_item(slot_idx)
            if item is not None:
                if slot_idx != self._sel_inv:
                    self._sel_inv = slot_idx
                    self._sel_eq  = -1
                    sounds.play_ui_move_sound()
            else:
                self._sel_inv = -1
            return

        slot_i = self._hit_eq_slot(tx, ty)
        if slot_i is not None:
            if slot_i != self._sel_eq:
                self._sel_eq  = slot_i
                self._sel_inv = -1
                sounds.play_ui_move_sound()
            return

        # Mouse is not over any interactive cell — clear highlight
        self._sel_inv = -1
        self._sel_eq  = -1

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[object]:
        tx, ty = int(event.tile.x), int(event.tile.y)
        ks    = tcod.event.get_keyboard_state()
        shift = bool(ks[225] or ks[229])  # SDL_SCANCODE_LSHIFT=225, RSHIFT=229

        # ── Category tab ──────────────────────────────────────────────────────
        tab = self._hit_category_tab(tx, ty)
        if tab is not None and event.button == tcod.event.BUTTON_LEFT:
            if tab != self._category:
                self._category = tab
                self._sel_inv  = 0
                self._scroll   = 0
            return None

        # ── Inventory grid cell ───────────────────────────────────────────────
        cell = self._hit_inv_cell(tx, ty)
        if cell is not None:
            col, row = cell
            slot_idx = self._cell_to_idx(col, row)
            item     = self._get_slot_item(slot_idx)
            if item is not None:
                if event.button == tcod.event.BUTTON_RIGHT:
                    return ItemContextMenu(self, item, tx, ty)
                if event.button == tcod.event.BUTTON_LEFT:
                    self._sel_inv = slot_idx
                    self._sel_eq  = -1
                    if shift and getattr(item, "equippable", None):
                        self._shift_equip_item(item)
                    else:
                        self.engine.mouse_held = True
                        self._drag_item     = item
                        self._drag_src_type = "inv"
                        self._drag_src_idx  = slot_idx
                        self._drag_tile     = (tx, ty)
                        if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                            try:
                                item.pickup_sound()
                            except Exception:
                                pass
            return None

        # ── Equipment slot ────────────────────────────────────────────────────
        slot_i = self._hit_eq_slot(tx, ty)
        if slot_i is not None:
            item = self._get_eq_item(slot_i)
            if event.button == tcod.event.BUTTON_RIGHT and item:
                return ItemContextMenu(self, item, tx, ty)
            if event.button == tcod.event.BUTTON_LEFT:
                self._sel_eq  = slot_i
                self._sel_inv = -1
                if shift and item:
                    self._unequip_to_first_slot(item)
                elif item:
                    self.engine.mouse_held = True
                    self._drag_item     = item
                    self._drag_src_type = "eq"
                    self._drag_src_idx  = slot_i
                    self._drag_tile     = (tx, ty)
                    if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                        try:
                            item.pickup_sound()
                        except Exception:
                            pass
            return None

        # ── Click outside logical inventory canvas → close ────────────────────
        ix, iy = self._to_inv(tx, ty)
        if not (0 <= ix < _C_W and 0 <= iy < _C_H):
            return self.on_exit()

        return None

    def ev_mousebuttonup(self, event: tcod.event.MouseButtonUp) -> Optional[object]:
        if event.button != tcod.event.BUTTON_LEFT or self._drag_item is None:
            return None
        tx, ty = int(event.tile.x), int(event.tile.y)
        self._complete_drag(tx, ty)
        return None

    def _complete_drag(self, tx: int, ty: int) -> None:
        """Resolve a drag-and-drop operation."""
        item      = self._drag_item
        src_type  = self._drag_src_type
        src_idx   = self._drag_src_idx

        # Always clear drag state first
        self._drag_item     = None
        self._drag_src_type = None
        self._drag_src_idx  = None

        if item is None:
            return

        # Play drop sound when releasing the drag.
        if hasattr(item, "drop_sound") and item.drop_sound is not None:
            try:
                item.drop_sound()
            except Exception:
                pass

        drop_cell  = self._hit_inv_cell(tx, ty)
        drop_eq    = self._hit_eq_slot(tx, ty)

        if drop_cell is not None:
            col, row = drop_cell
            dst_slot = self._cell_to_idx(col, row)

            if src_type == "inv" and dst_slot != src_idx:
                self._swap_inv_slots(src_idx, dst_slot)
            elif src_type == "eq":
                # Unequip item → it re-appears in its existing inventory slot.
                # Then swap it to wherever the player dropped it.
                try:
                    self.engine.player.equipment.unequip_item(item, add_message=True)
                except Exception:
                    pass
                inv = self.engine.player.inventory
                self._resync_inv_slots()
                # Find where the item landed after resync (slot 0), then move it to dst_slot
                while len(inv.item_slots) <= dst_slot:
                    inv.item_slots.append(None)
                for i, s in enumerate(inv.item_slots):
                    if s is item and i != dst_slot:
                        inv.item_slots[dst_slot], inv.item_slots[i] = inv.item_slots[i], inv.item_slots[dst_slot]
                        break

        elif drop_eq is not None:
            slot_label, eq_types = _EQ_SLOTS[drop_eq]
            if getattr(item, "equippable", None) and item.equippable.equipment_type in eq_types:
                # Map slot name to preferred hand for weapon/shield slots.
                _hand_pref = {"R.Hand": "right", "L.Hand": "left"}.get(slot_label)
                try:
                    eq = self.engine.player.equipment
                    if _hand_pref is not None:
                        # Direct equip with forced hand (drag-to-slot is never a toggle).
                        if eq.is_item_equipped(item):
                            eq.unequip_item(item, add_message=True)
                        eq.equip_item(item, add_message=True, preferred_hand=_hand_pref)
                    else:
                        actions.EquipAction(self.engine.player, item).perform()
                except Exception as exc:
                    self.engine.message_log.add_message(str(exc), color.impossible)
                else:
                    self._clear_from_item_slots(item)  # free slot; re-assigned on unequip

        else:
            # Released outside any valid drop target — drop to ground if outside UI border.
            ix, iy = self._to_inv(tx, ty)
            if not (0 <= ix < _C_W and 0 <= iy < _C_H):
                try:
                    actions.DropItem(self.engine.player, item).perform()
                except Exception as exc:
                    self.engine.message_log.add_message(str(exc), color.impossible)

    def _clear_from_item_slots(self, item: "Item") -> None:
        """Null out this item's slot entry.  _resync_inv_slots handles placement."""
        inv = self.engine.player.inventory
        if not hasattr(inv, "item_slots"):
            return
        for i, s in enumerate(inv.item_slots):
            if s is item:
                inv.item_slots[i] = None
                return

    def _resync_inv_slots(self) -> None:
        """Keep item_slots consistent: equipped items invisible, drag positions
        preserved, new items placed at first free slot from 0.

        Phase 1 — clear/upgrade stale entries:
          - Entry is still valid & un-equipped → keep it.
          - Entry is stale but a same-type group exists (stack consumed) →
            replace in-place so the stack stays in its slot.
          - Entry is completely stale → null out.
        Phase 2 — items not yet assigned a slot fill the first available None.
        """
        inv = self.engine.player.inventory
        eq  = self.engine.player.equipment

        if not hasattr(inv, 'item_slots') or inv.item_slots is None:
            inv.item_slots = []

        groups = inv.get_display_groups()
        valid_unequipped = {id(g['item']): g for g in groups
                            if not eq.item_is_equipped(g['item'])}

        # Phase 1
        slotted: set = set()
        for i, s in enumerate(inv.item_slots):
            if s is None:
                continue
            if id(s) in valid_unequipped:
                slotted.add(id(s))
            else:
                # Stale entry — try in-place replacement with same display type
                stale_key = inv._get_item_display_key(s)
                replacement = None
                for gid, g in valid_unequipped.items():
                    if gid not in slotted and inv._get_item_display_key(g['item']) == stale_key:
                        replacement = g['item']
                        break
                if replacement is not None:
                    inv.item_slots[i] = replacement
                    slotted.add(id(replacement))
                else:
                    inv.item_slots[i] = None

        # Phase 2: place unslotted items at first free slot from 0
        for gid, g in valid_unequipped.items():
            rep = g['item']
            if id(rep) in slotted:
                continue
            placed = False
            for i in range(len(inv.item_slots)):
                if inv.item_slots[i] is None:
                    inv.item_slots[i] = rep
                    slotted.add(id(rep))
                    placed = True
                    break
            if not placed:
                inv.item_slots.append(rep)
                slotted.add(id(rep))

    def _shift_equip_item(self, item: "Item") -> None:
        """Equip item into the next available compatible slot.
        Hand items prefer an empty hand; other types go straight to equip_item."""
        eq = self.engine.player.equipment
        is_hand = "hand" in getattr(item.equippable, "required_tags", set())
        try:
            if is_hand:
                right_free = (eq.body_part_coverage.get("right hand") is None and
                              eq.grasped_items.get("right hand") is None)
                left_free  = (eq.body_part_coverage.get("left hand") is None and
                              eq.grasped_items.get("left hand") is None)
                if right_free:
                    pref = "right"
                elif left_free:
                    pref = "left"
                else:
                    pref = "right"  # displace right-hand item
                eq.equip_item(item, add_message=True, preferred_hand=pref)
            else:
                eq.equip_item(item, add_message=True)
        except Exception as exc:
            self.engine.message_log.add_message(str(exc), color.impossible)
            return
        # Free the slot — sync_slots will fill it if the item re-enters inventory
        self._clear_from_item_slots(item)

    def _unequip_to_first_slot(self, item: "Item") -> None:
        """Unequip item; sync_slots places it at first free slot (from 0) next frame."""
        try:
            self.engine.player.equipment.unequip_item(item, add_message=True)
        except Exception as exc:
            self.engine.message_log.add_message(str(exc), color.impossible)
            return
        # Clear so sync_slots treats it as a newly-entered item
        self._clear_from_item_slots(item)

    def _swap_inv_slots(self, src_slot: int, dst_slot: int) -> None:
        """Swap two slot positions in inventory.item_slots.
        Extends the list if dst_slot is beyond the current length."""
        if src_slot == dst_slot or src_slot < 0 or dst_slot < 0:
            return
        slots = self.engine.player.inventory.item_slots
        if src_slot >= len(slots):
            return  # source doesn't exist — nothing to move
        # Grow the list with None entries so dst_slot is reachable
        while len(slots) <= dst_slot:
            slots.append(None)
        slots[src_slot], slots[dst_slot] = slots[dst_slot], slots[src_slot]

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[object]:
        global _ALT_DAMAGE_VIEW
        key = event.sym

        # Alt toggles the damage-view overlay (persistent across inventory opens)
        if key in (tcod.event.KeySym.LALT, tcod.event.KeySym.RALT):
            _ALT_DAMAGE_VIEW = not _ALT_DAMAGE_VIEW
            return None

        if key == tcod.event.K_ESCAPE:
            return self.on_exit()

        n_slots = len(self.engine.player.inventory.item_slots)

        if key == tcod.event.K_UP:
            if self._sel_inv >= 0:
                self._sel_inv = max(0, self._sel_inv - _GRID_COLS)
            elif self._sel_eq >= 0:
                self._sel_eq = max(0, self._sel_eq - 1)
            return None

        if key == tcod.event.K_DOWN:
            if self._sel_inv >= 0:
                self._sel_inv = min(n_slots - 1, self._sel_inv + _GRID_COLS)
            elif self._sel_eq >= 0:
                self._sel_eq = min(len(_EQ_SLOTS) - 1, self._sel_eq + 1)
            return None

        if key == tcod.event.K_LEFT:
            if self._sel_inv >= 0:
                self._sel_inv = max(0, self._sel_inv - 1)
            return None

        if key == tcod.event.K_RIGHT:
            if self._sel_inv >= 0:
                self._sel_inv = min(n_slots - 1, self._sel_inv + 1)
            return None

        if key in CONFIRM_KEYS:
            return self._activate_selected()

        # Tab → close the inventory UI
        if key == tcod.event.K_TAB:
            return self.on_exit()

        # Page scroll
        if key == tcod.event.K_PAGEDOWN:
            self._scroll += 1
            return None
        if key == tcod.event.K_PAGEUP:
            self._scroll = max(0, self._scroll - 1)
            return None

        # Number keys 1-4 for quick tab switch
        if tcod.event.KeySym.N1 <= key <= tcod.event.KeySym.N4:
            tab_i = key - tcod.event.KeySym.N1
            if tab_i < len(self._categories):
                self._category = tab_i
                self._sel_inv  = 0
                self._scroll   = 0
            return None

        return None

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[object]:
        if event.y < 0:
            self._scroll += 1
        elif event.y > 0:
            self._scroll = max(0, self._scroll - 1)
        return None

    def _activate_selected(self) -> Optional[object]:
        """Enter/Space action on the selected item."""
        if self._sel_inv >= 0:
            item = self._get_slot_item(self._sel_inv)
            if item is not None:
                if getattr(item, "consumable", None):
                    aoh = item.consumable.get_action(self.engine.player)
                    if aoh:
                        if hasattr(aoh, "perform"):
                            try:
                                aoh.perform()
                            except Exception as exc:
                                self.engine.message_log.add_message(str(exc), color.impossible)
                            return None
                        return aoh
                elif getattr(item, "equippable", None):
                    try:
                        actions.EquipAction(self.engine.player, item).perform()
                    except Exception as exc:
                        self.engine.message_log.add_message(str(exc), color.impossible)
                    self._clear_from_item_slots(item)  # free slot regardless of equip/unequip
                    return None

        elif self._sel_eq >= 0:
            item = self._get_eq_item(self._sel_eq)
            if item and getattr(item, "equippable", None):
                try:
                    self.engine.player.equipment.unequip_item(item, add_message=True)
                except Exception as exc:
                    self.engine.message_log.add_message(str(exc), color.impossible)
                    return None
                self._clear_from_item_slots(item)  # let sync_slots place at first free slot
                return None

        return None


# ─────────────────────────────────────────────────────────────────────────────
# Container grid UI — two-panel grid (player inv left, container right)
# ─────────────────────────────────────────────────────────────────────────────
#  Col 0      : left border
#  Cols 1–15  : player inventory grid  (5 cols × 3 scale = 15 panel cols)
#  Col 16     : vertical divider
#  Cols 17–31 : container grid         (5 cols × 3 scale = 15 panel cols)
#  Col 32     : scroll indicator space
#  Col 33     : right border
#  Row 0      : top border + titles
#  Row 1      : panel hint labels
#  Row 2      : horizontal separator
#  Rows 3–29  : item grids (9 rows × 3 scale = 27 panel rows)
#  Row 30     : separator above info strip
#  Rows 31–34 : info strip
#  Row 35     : bottom border

_CC_W: int           = 34
_CC_H: int           = 36
_CC_BLIT_X: int      = (80 - _CC_W) // 2   # = 23
_CC_BLIT_Y: int      = (50 - _CC_H) // 2   # = 7
_CC_GRID_SCALE: int  = 3
_CC_GRID_COLS: int   = 5
_CC_GRID_ROWS: int   = 9
_CC_LEFT_ORI: int    = 1    # player grid start col
_CC_RIGHT_ORI: int   = 17   # container grid start col
_CC_GRID_ROW_ORI: int = 3   # both grids' first row
_CC_DIV_X: int       = 16   # vertical divider col
_CC_INFO_SEP_Y: int  = 30   # separator above info strip
_CC_INFO_Y: int      = 31   # first info content row


class ContainerGridUI(PopupEventHandler):
    """Two-panel container grid: player inventory (left) + container items (right).

    Shift-click transfers items instantly.
    Drag within the same panel reorders; drag across panels transfers.
    The two item grids are GPU-rendered at 3× by main.py (same renderer as InventoryGridUI).
    """

    def __init__(self, engine: "Engine", container) -> None:
        super().__init__(engine)
        self.container = container

        engine.context_hints = [
            ("Shift+Click", "Transfer"),
            ("Drag",        "Move / Transfer"),
            ("Esc",         "Close"),
        ]

        self._inv_console            = tcod.console.Console(_CC_W, _CC_H, order="F")
        self._grid_console           = tcod.console.Console(_CC_GRID_COLS, _CC_GRID_ROWS, order="F")
        self._container_grid_console = tcod.console.Console(_CC_GRID_COLS, _CC_GRID_ROWS, order="F")
        self._player_qty_console     = tcod.console.Console(_CC_GRID_COLS * _CC_GRID_SCALE, _CC_GRID_ROWS * _CC_GRID_SCALE, order="F")
        self._container_qty_console  = tcod.console.Console(_CC_GRID_COLS * _CC_GRID_SCALE, _CC_GRID_ROWS * _CC_GRID_SCALE, order="F")
        self._drag_console           = tcod.console.Console(1, 1, order="F")

        # Sparse slot list for the container panel: items at random positions,
        # None = empty cell.  Persisted on the container object so the layout
        # survives between opens.  Drag reorders in-place; transfers update it.
        import random as _rand
        n_grid = _CC_GRID_COLS * _CC_GRID_ROWS
        if not hasattr(container, '_ui_slots'):
            # First open: scatter items into random positions and remember them.
            items = list(container.items)
            if len(items) <= n_grid:
                positions = _rand.sample(range(n_grid), len(items))
                container._ui_slots = [None] * n_grid
                for pos, item in zip(positions, items):
                    container._ui_slots[pos] = item
            else:
                container._ui_slots = [None] * n_grid
                for i, item in enumerate(items[:n_grid]):
                    container._ui_slots[i] = item
                container._ui_slots.extend(items[n_grid:])
        else:
            # Subsequent open: sync stale entries (items removed externally).
            valid = set(id(it) for it in container.items)
            for i, s in enumerate(container._ui_slots):
                if s is not None and id(s) not in valid:
                    container._ui_slots[i] = None
            # Any item not yet in slots (added externally) → first free slot.
            slotted = {id(s) for s in container._ui_slots if s is not None}
            for it in container.items:
                if id(it) not in slotted:
                    placed = False
                    for i in range(len(container._ui_slots)):
                        if container._ui_slots[i] is None:
                            container._ui_slots[i] = it
                            placed = True
                            break
                    if not placed:
                        container._ui_slots.append(it)
        self._container_slots: list = container._ui_slots

        self._player_scroll: int    = 0
        self._container_scroll: int = 0

        self._sel_player: int    = -1
        self._sel_container: int = -1
        self._hover_panel: Optional[str] = None  # "player" | "container" | None

        self._drag_item:     Optional["Item"] = None
        self._drag_src_type: Optional[str]    = None   # "player" | "container"
        self._drag_src_idx:  Optional[int]    = None
        self._drag_tile:     Tuple[int, int]  = (0, 0)
        self._drag_pixel:    Tuple[int, int]  = (0, 0)

        self._set_popup_bounds(_CC_BLIT_X, _CC_BLIT_Y, _CC_W, _CC_H)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    @staticmethod
    def _to_panel(tx: int, ty: int) -> Tuple[int, int]:
        return tx - _CC_BLIT_X, ty - _CC_BLIT_Y

    def _hit_left_cell(self, tx: int, ty: int) -> Optional[Tuple[int, int]]:
        ix, iy = self._to_panel(tx, ty)
        col = (ix - _CC_LEFT_ORI) // _CC_GRID_SCALE
        row = (iy - _CC_GRID_ROW_ORI) // _CC_GRID_SCALE
        if 0 <= col < _CC_GRID_COLS and 0 <= row < _CC_GRID_ROWS:
            return col, row
        return None

    def _hit_right_cell(self, tx: int, ty: int) -> Optional[Tuple[int, int]]:
        ix, iy = self._to_panel(tx, ty)
        col = (ix - _CC_RIGHT_ORI) // _CC_GRID_SCALE
        row = (iy - _CC_GRID_ROW_ORI) // _CC_GRID_SCALE
        if 0 <= col < _CC_GRID_COLS and 0 <= row < _CC_GRID_ROWS:
            return col, row
        return None

    def _cell_to_idx(self, col: int, row: int, scroll: int) -> int:
        return (scroll + row) * _CC_GRID_COLS + col

    @property
    def _grid_dest_tiles(self) -> Tuple[int, int, int, int]:
        return (
            _CC_BLIT_X + _CC_LEFT_ORI,
            _CC_BLIT_Y + _CC_GRID_ROW_ORI,
            _CC_GRID_COLS * _CC_GRID_SCALE,
            _CC_GRID_ROWS * _CC_GRID_SCALE,
        )

    @property
    def _container_grid_dest_tiles(self) -> Tuple[int, int, int, int]:
        return (
            _CC_BLIT_X + _CC_RIGHT_ORI,
            _CC_BLIT_Y + _CC_GRID_ROW_ORI,
            _CC_GRID_COLS * _CC_GRID_SCALE,
            _CC_GRID_ROWS * _CC_GRID_SCALE,
        )

    @property
    def _drag_dest_tiles(self) -> Tuple[int, int, int, int]:
        tx, ty = self._drag_tile
        dx = _clamp(tx - _CC_GRID_SCALE // 2, 0, 80 - _CC_GRID_SCALE)
        dy = _clamp(ty - _CC_GRID_SCALE // 2, 0, 50 - _CC_GRID_SCALE)
        return (dx, dy, _CC_GRID_SCALE, _CC_GRID_SCALE)

    @property
    def _drag_dest_pixels(self) -> Tuple[int, int, int, int]:
        """Drag ghost pixel rect, centred on the actual pixel cursor position."""
        px, py = self._drag_pixel
        size   = _CC_GRID_SCALE * 16
        return (px - size // 2, py - size // 2, size, size)

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _get_player_groups(self):
        return self.engine.player.inventory.get_display_groups()

    def _get_container_groups(self):
        """Return a sparse list mirroring _container_slots.
        Entries are {"item": item} for filled slots, None for empty slots."""
        return [{"item": s} if s is not None else None
                for s in self._container_slots]

    # ── Rendering ─────────────────────────────────────────────────────────────

    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        self._grid_console.clear()
        self._fill_player_grid()

        self._player_qty_console.clear()
        self._fill_player_qty_console()

        self._container_grid_console.clear()
        self._fill_container_grid()

        self._container_qty_console.clear()
        self._fill_container_qty_console()

        if self._drag_item is not None:
            self._drag_console.clear()
            self._fill_drag_console()

        c = self._inv_console
        c.clear()
        self._render_to_console(c)
        c.blit(console, _CC_BLIT_X, _CC_BLIT_Y)

    def _fill_drag_console(self) -> None:
        if self._drag_item is None:
            return
        item_ch  = getattr(self._drag_item, "char", "?")
        item_col = getattr(self._drag_item, "color", (200, 180, 100))
        self._drag_console.print(0, 0, item_ch, fg=item_col, bg=(0, 0, 0))

    def _fill_player_qty_console(self) -> None:
        gc = self._player_qty_console
        gc.tiles_rgb['bg'][:, :] = 0
        gc.tiles_rgb['fg'][:, :] = 0
        gc.tiles_rgb['ch'][:, :] = ord(' ')
        groups = self._get_player_groups()
        for row in range(_CC_GRID_ROWS):
            for col in range(_CC_GRID_COLS):
                idx = self._cell_to_idx(col, row, self._player_scroll)
                if idx >= len(groups):
                    continue
                item = groups[idx]['item']
                px   = col * _CC_GRID_SCALE
                py   = row * _CC_GRID_SCALE
                # Stack count — top-left, gold
                qty = groups[idx].get('quantity', 1)
                if qty > 1:
                    gc.print(px, py, f"x{qty}", fg=(255, 230, 120), bg=(0, 0, 0))
                # Enchantment level — bottom-right, cyan
                enc = getattr(item, 'enchantment_level', 0)
                if enc and enc > 0:
                    import roman as _roman
                    enc_label = f"+{_roman.toRoman(enc)}".rjust(_CC_GRID_SCALE)
                    gc.print(px, py + _CC_GRID_SCALE - 1, enc_label,
                             fg=(120, 200, 255), bg=(0, 0, 0))

    def _fill_container_qty_console(self) -> None:
        gc = self._container_qty_console
        gc.tiles_rgb['bg'][:, :] = 0
        gc.tiles_rgb['fg'][:, :] = 0
        gc.tiles_rgb['ch'][:, :] = ord(' ')
        for row in range(_CC_GRID_ROWS):
            for col in range(_CC_GRID_COLS):
                idx = self._cell_to_idx(col, row, self._container_scroll)
                if idx >= len(self._container_slots):
                    continue
                item = self._container_slots[idx]
                if item is None:
                    continue
                px  = col * _CC_GRID_SCALE
                py  = row * _CC_GRID_SCALE
                enc = getattr(item, 'enchantment_level', 0)
                if enc and enc > 0:
                    import roman as _roman
                    enc_label = f"+{_roman.toRoman(enc)}".rjust(_CC_GRID_SCALE)
                    gc.print(px, py + _CC_GRID_SCALE - 1, enc_label,
                             fg=(120, 200, 255), bg=(0, 0, 0))

    def _fill_side_grid(self, gc, groups, sel: int, scroll: int, src_key: str) -> int:
        """Fill one grid console; returns the clamped scroll value.
        groups may be sparse (entries can be None for empty slots)."""
        total      = len(groups)
        max_scroll = max(0, -(-total // _CC_GRID_COLS) - _CC_GRID_ROWS)
        scroll     = _clamp(scroll, 0, max_scroll)

        for row in range(_CC_GRID_ROWS):
            for col in range(_CC_GRID_COLS):
                idx         = (scroll + row) * _CC_GRID_COLS + col
                grp         = groups[idx] if idx < total else None
                is_filled   = grp is not None
                is_sel      = (idx == sel)
                is_drag_src = (self._drag_src_type == src_key
                               and self._drag_src_idx == idx)

                if is_filled:
                    item        = grp["item"]
                    is_equipped = (src_key == "player"
                                   and self.engine.player.equipment.item_is_equipped(item))
                else:
                    is_equipped = False

                cell_bg = (
                    _CELL_DRAG if is_drag_src
                    else _CELL_SEL if is_sel
                    else tuple(max(0, v * 70 // 100) for v in _CELL_FILLED) if (is_filled and is_equipped)
                    else _CELL_FILLED if is_filled
                    else _CELL_EMPTY
                )

                if is_filled:
                    item_ch      = getattr(item, "char", "?")
                    item_col     = getattr(item, "color", (200, 180, 100))
                    rar_col      = getattr(item, "rarity_color", cell_bg)
                    tinted_bg    = tuple(min(255, int(b * 75 // 100 + r * 25 // 100))
                                        for b, r in zip(cell_bg, rar_col))
                    if is_drag_src:
                        item_col = tuple(max(0, v - 80) for v in item_col)
                    gc.print(col, row, item_ch, fg=item_col, bg=tinted_bg)
                else:
                    gc.print(col, row, "·", fg=_SLOT_EMPTY_V, bg=cell_bg)

        return scroll

    def _fill_player_grid(self) -> None:
        self._player_scroll = self._fill_side_grid(
            self._grid_console, self._get_player_groups(),
            self._sel_player, self._player_scroll, "player",
        )

    def _fill_container_grid(self) -> None:
        self._container_scroll = self._fill_side_grid(
            self._container_grid_console, self._get_container_groups(),
            self._sel_container, self._container_scroll, "container",
        )

    def _render_to_console(self, c: tcod.Console) -> None:
        W, H = _CC_W, _CC_H
        bf   = _BORDER_DIM

        # Background + outer frame
        c.tiles_rgb["bg"][:, :] = _BG
        c.tiles_rgb["fg"][:, :] = _BG
        c.tiles_rgb["ch"][:, :] = ord(" ")
        c.draw_frame(0, 0, W, H, fg=bf, bg=_BG)

        # Titles embedded in top frame
        container_name = getattr(self.container.parent, "name", "Container")
        is_corpse      = getattr(self.container.parent, "type", None) == "Dead"
        right_title    = " Corpse " if is_corpse else f" {container_name} "
        c.print(1, 0, " Inventory ", fg=_TITLE_FG, bg=_BG)
        c.print(_CC_RIGHT_ORI, 0, right_title[:(_CC_W - _CC_RIGHT_ORI - 1)],
                fg=_TITLE_FG, bg=_BG)

        # Hint row
        c.print(2,              1, "← Your Items", fg=_HINT_FG, bg=_BG)
        c.print(_CC_RIGHT_ORI + 1, 1, "Container →",  fg=_HINT_FG, bg=_BG)

        # Vertical divider (rows 1 → info separator, exclusive)
        c.print(_CC_DIV_X, 0, "┬", fg=bf, bg=_BG)
        for y in range(1, _CC_INFO_SEP_Y):
            c.print(_CC_DIV_X, y, "│", fg=bf, bg=_BG)

        # Horizontal separator at row 2 (full width)
        for x in range(1, W - 1):
            c.print(x, 2, "─", fg=bf, bg=_BG)
        c.print(0,         2, "├", fg=bf, bg=_BG)
        c.print(_CC_DIV_X, 2, "┼", fg=bf, bg=_BG)
        c.print(W - 1,     2, "┤", fg=bf, bg=_BG)

        # Separator above info strip (full width, divider terminates here)
        for x in range(1, W - 1):
            c.print(x, _CC_INFO_SEP_Y, "─", fg=bf, bg=_BG)
        c.print(0,         _CC_INFO_SEP_Y, "├", fg=bf, bg=_BG)
        c.print(_CC_DIV_X, _CC_INFO_SEP_Y, "┴", fg=bf, bg=_BG)
        c.print(W - 1,     _CC_INFO_SEP_Y, "┤", fg=bf, bg=_BG)

        # Scroll indicators
        p_max_s = max(0, -(-len(self._get_player_groups())    // _CC_GRID_COLS) - _CC_GRID_ROWS)
        c_max_s = max(0, -(-len(self._get_container_groups()) // _CC_GRID_COLS) - _CC_GRID_ROWS)
        if self._player_scroll > 0:
            c.print(_CC_DIV_X, _CC_GRID_ROW_ORI, "↑", fg=_BORDER_BRIGHT, bg=_BG)
        if self._player_scroll < p_max_s:
            c.print(_CC_DIV_X, _CC_INFO_SEP_Y - 1, "↓", fg=_BORDER_BRIGHT, bg=_BG)
        _scroll_r = _CC_W - 2   # col 32
        if self._container_scroll > 0:
            c.print(_scroll_r, _CC_GRID_ROW_ORI, "↑", fg=_BORDER_BRIGHT, bg=_BG)
        if self._container_scroll < c_max_s:
            c.print(_scroll_r, _CC_INFO_SEP_Y - 1, "↓", fg=_BORDER_BRIGHT, bg=_BG)

        # Transparent holes for both grids (GPU-direct / context-menu BLEND path)
        for ori in (_CC_LEFT_ORI, _CC_RIGHT_ORI):
            x1 = ori
            x2 = ori + _CC_GRID_COLS * _CC_GRID_SCALE
            y1 = _CC_GRID_ROW_ORI
            y2 = _CC_GRID_ROW_ORI + _CC_GRID_ROWS * _CC_GRID_SCALE
            c.tiles_rgb["bg"][x1:x2, y1:y2] = 0
            c.tiles_rgb["fg"][x1:x2, y1:y2] = 0
            c.tiles_rgb["ch"][x1:x2, y1:y2] = ord(" ")

        self._draw_info_strip(c)

    def _draw_info_strip(self, c: tcod.Console) -> None:
        item: Optional["Item"] = None
        if self._sel_player >= 0:
            groups = self._get_player_groups()
            if self._sel_player < len(groups):
                item = groups[self._sel_player]["item"]
        elif self._sel_container >= 0:
            groups = self._get_container_groups()
            if self._sel_container < len(groups) and groups[self._sel_container] is not None:
                item = groups[self._sel_container]["item"]

        if item is None:
            c.print(2, _CC_INFO_Y,
                    "Hover an item to inspect  |  Shift+Click to transfer",
                    fg=_HINT_FG, bg=_BG)
            return

        name = item.name[:(_CC_W - 4)]
        c.print(2, _CC_INFO_Y, name,
                fg=getattr(item, "rarity_color", (220, 190, 120)), bg=_BG)

        parts: list[str] = []
        if getattr(item, "equippable", None):
            eq = item.equippable
            if getattr(eq, "power_bonus",   0): parts.append(f"Pwr:{eq.power_bonus:+}")
            if getattr(eq, "defense_bonus", 0): parts.append(f"Def:{eq.defense_bonus:+}")
            is_e = self.engine.player.equipment.item_is_equipped(item)
            parts.append("Equipped" if is_e else "Not Equipped")
        elif getattr(item, "consumable", None):
            parts.append("Consumable")
        else:
            parts.append("Miscellaneous")
        c.print(2, _CC_INFO_Y + 1, "  ".join(parts)[:(_CC_W - 4)],
                fg=_INFO_STAT, bg=_BG)

    # ── Event handlers ────────────────────────────────────────────────────────

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> None:
        super().ev_mousemotion(event)
        tx, ty = int(event.tile.x), int(event.tile.y)
        self._drag_tile  = (tx, ty)
        self._drag_pixel = (int(event.pixel.x), int(event.pixel.y))

        cell = self._hit_left_cell(tx, ty)
        if cell is not None:
            col, row = cell
            idx    = self._cell_to_idx(col, row, self._player_scroll)
            groups = self._get_player_groups()
            if idx < len(groups):
                if idx != self._sel_player:
                    self._sel_player    = idx
                    self._sel_container = -1
                    sounds.play_ui_move_sound()
                self._hover_panel = "player"
            else:
                self._sel_player  = -1
                self._hover_panel = "player"
            return

        cell = self._hit_right_cell(tx, ty)
        if cell is not None:
            col, row = cell
            idx    = self._cell_to_idx(col, row, self._container_scroll)
            groups = self._get_container_groups()
            if idx < len(groups) and groups[idx] is not None:
                if idx != self._sel_container:
                    self._sel_container = idx
                    self._sel_player    = -1
                    sounds.play_ui_move_sound()
                self._hover_panel = "container"
            else:
                self._sel_container = -1
                self._hover_panel   = "container"
            return

        self._sel_player    = -1
        self._sel_container = -1
        self._hover_panel   = None

    def ev_mousebuttondown(self, event: tcod.event.MouseButtonDown) -> Optional[object]:
        tx, ty = int(event.tile.x), int(event.tile.y)
        ix, iy = self._to_panel(tx, ty)
        if not (0 <= ix < _CC_W and 0 <= iy < _CC_H):
            return self.on_exit()

        ks = tcod.event.get_keyboard_state()
        shift = bool(ks[225] or ks[229])  # SDL_SCANCODE_LSHIFT=225, RSHIFT=229

        # Left (player) panel
        cell = self._hit_left_cell(tx, ty)
        if cell is not None:
            col, row = cell
            idx    = self._cell_to_idx(col, row, self._player_scroll)
            groups = self._get_player_groups()
            if idx < len(groups):
                item = groups[idx]["item"]
                if event.button == tcod.event.BUTTON_RIGHT:
                    return ItemContextMenu(self, item, tx, ty)
                if event.button == tcod.event.BUTTON_LEFT:
                    self._sel_player    = idx
                    self._sel_container = -1
                    if shift:
                        self._transfer_to_container(item)
                    else:
                        self.engine.mouse_held = True
                        self._drag_item     = item
                        self._drag_src_type = "player"
                        self._drag_src_idx  = idx
                        self._drag_tile     = (tx, ty)
                        if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                            try: item.pickup_sound()
                            except Exception: pass
            return None

        # Right (container) panel
        cell = self._hit_right_cell(tx, ty)
        if cell is not None:
            col, row = cell
            idx    = self._cell_to_idx(col, row, self._container_scroll)
            groups = self._get_container_groups()
            if idx < len(groups) and groups[idx] is not None:
                item = groups[idx]["item"]
                if event.button == tcod.event.BUTTON_RIGHT:
                    return ItemContextMenu(self, item, tx, ty)
                if event.button == tcod.event.BUTTON_LEFT:
                    self._sel_container = idx
                    self._sel_player    = -1
                    if shift:
                        self._transfer_to_player(item)
                    else:
                        self.engine.mouse_held = True
                        self._drag_item     = item
                        self._drag_src_type = "container"
                        self._drag_src_idx  = idx
                        self._drag_tile     = (tx, ty)
                        if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                            try: item.pickup_sound()
                            except Exception: pass
            return None

        return None

    def ev_mousebuttonup(self, event: tcod.event.MouseButtonUp) -> Optional[object]:
        if event.button != tcod.event.BUTTON_LEFT or self._drag_item is None:
            return None
        tx, ty = int(event.tile.x), int(event.tile.y)
        self._complete_drag(tx, ty)
        return None

    def _complete_drag(self, tx: int, ty: int) -> None:
        item     = self._drag_item
        src_type = self._drag_src_type
        src_idx  = self._drag_src_idx
        self._drag_item     = None
        self._drag_src_type = None
        self._drag_src_idx  = None
        if item is None:
            return

        left_cell  = self._hit_left_cell(tx, ty)
        right_cell = self._hit_right_cell(tx, ty)

        if left_cell is not None:
            col, row = left_cell
            dst_idx  = self._cell_to_idx(col, row, self._player_scroll)
            if src_type == "player":
                if dst_idx != src_idx:
                    self._swap_player_items(src_idx, dst_idx)
            elif src_type == "container":
                self._transfer_to_player(item)
            return

        if right_cell is not None:
            col, row = right_cell
            dst_idx  = self._cell_to_idx(col, row, self._container_scroll)
            if src_type == "container":
                if dst_idx != src_idx:
                    self._swap_container_items(src_idx, dst_idx)
            elif src_type == "player":
                self._transfer_to_container(item)
            return

        # Released outside any panel — drop player items on the ground if outside UI border
        ix, iy = self._to_panel(tx, ty)
        if not (0 <= ix < _CC_W and 0 <= iy < _CC_H):
            if src_type == "player":
                try:
                    actions.DropItem(self.engine.player, item).perform()
                except Exception as exc:
                    self.engine.message_log.add_message(str(exc), color.impossible)
            return
        # Inside panel but between grids — play sound, item stays where it was
        if hasattr(item, "drop_sound") and item.drop_sound is not None:
            try: item.drop_sound()
            except Exception: pass

    # ── Transfer helpers ──────────────────────────────────────────────────────

    def _transfer_to_container(self, item: "Item") -> None:
        if self.container.is_full():
            self.engine.message_log.add_message("Container is full.", color.impossible)
            return
        if self.engine.player.equipment.item_is_equipped(item):
            try:
                self.engine.player.equipment.unequip_item(item, add_message=True)
            except Exception:
                pass
        try:
            self.engine.player.inventory.items.remove(item)
        except ValueError:
            return
        self.container.items.append(item)
        # Place in first free slot of _container_slots
        placed = False
        for i in range(len(self._container_slots)):
            if self._container_slots[i] is None:
                self._container_slots[i] = item
                placed = True
                break
        if not placed:
            self._container_slots.append(item)
        try: item.parent = self.container
        except Exception: pass
        c_name = getattr(self.container.parent, "name", "container")
        self.engine.message_log.add_message(
            f"You place the {item.name} in the {c_name}.")
        if hasattr(item, "drop_sound") and item.drop_sound is not None:
            try: item.drop_sound()
            except Exception: pass

    def _transfer_to_player(self, item: "Item") -> None:
        if not self.engine.player.inventory.can_carry(item):
            self.engine.message_log.add_message("You are carrying too much.", color.impossible)
            return
        if "coin" in item.name.lower():
            try: self.container.items.remove(item)
            except ValueError: return
            # Clear from slot list
            for i, s in enumerate(self._container_slots):
                if s is item:
                    self._container_slots[i] = None
                    break
            self.engine.player.gold += getattr(item, "value", 0)
            self.engine.message_log.add_message("You pick up some coins.")
            if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
                try: item.pickup_sound()
                except Exception: pass
            return
        try:
            self.container.items.remove(item)
        except ValueError:
            return
        # Clear from container slot list
        for i, s in enumerate(self._container_slots):
            if s is item:
                self._container_slots[i] = None
                break
        self.engine.player.inventory.items.append(item)
        try: item.parent = self.engine.player.inventory
        except Exception: pass
        self.engine.message_log.add_message(f"You take the {item.name}.")
        if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
            try: item.pickup_sound()
            except Exception: pass
        is_corpse = getattr(self.container.parent, "type", None) == "Dead"
        if is_corpse and not self.container.items:
            import random as _random
            self.container.parent.char = _random.choice(
                [chr(0xE010), chr(0xE011), chr(0xE012)])

    def _swap_player_items(self, src_idx: int, dst_idx: int) -> None:
        groups = self._get_player_groups()
        if src_idx >= len(groups) or dst_idx >= len(groups):
            return
        items = self.engine.player.inventory.items
        try:
            si = items.index(groups[src_idx]["item"])
            di = items.index(groups[dst_idx]["item"])
            items[si], items[di] = items[di], items[si]
        except ValueError:
            pass

    def _swap_container_items(self, src_idx: int, dst_idx: int) -> None:
        slots = self._container_slots
        # Grow if needed (dst beyond current length)
        while len(slots) <= dst_idx:
            slots.append(None)
        if src_idx < len(slots):
            slots[src_idx], slots[dst_idx] = slots[dst_idx], slots[src_idx]

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[object]:
        key   = event.sym
        shift = bool(event.mod & (tcod.event.KMOD_LSHIFT | tcod.event.KMOD_RSHIFT))

        if key in (tcod.event.K_ESCAPE, tcod.event.K_TAB):
            return self.on_exit()

        if key == tcod.event.K_PAGEDOWN:
            if self._hover_panel == "container":
                self._container_scroll += 1
            else:
                self._player_scroll += 1
            return None

        if key == tcod.event.K_PAGEUP:
            if self._hover_panel == "container":
                self._container_scroll = max(0, self._container_scroll - 1)
            else:
                self._player_scroll = max(0, self._player_scroll - 1)
            return None

        if key in CONFIRM_KEYS:
            if shift:
                if self._sel_player >= 0:
                    groups = self._get_player_groups()
                    if self._sel_player < len(groups):
                        self._transfer_to_container(groups[self._sel_player]["item"])
                elif self._sel_container >= 0:
                    groups = self._get_container_groups()
                    if (self._sel_container < len(groups)
                            and groups[self._sel_container] is not None):
                        self._transfer_to_player(groups[self._sel_container]["item"])
            return None

        return None

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> Optional[object]:
        if self._hover_panel == "container":
            if event.y < 0:   self._container_scroll += 1
            elif event.y > 0: self._container_scroll = max(0, self._container_scroll - 1)
        else:
            if event.y < 0:   self._player_scroll += 1
            elif event.y > 0: self._player_scroll = max(0, self._player_scroll - 1)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Trade grid UI — player inventory (left) ↔ merchant inventory (right)
# Sell (left → right): player receives 75 % of item.value in gold.
# Buy  (right → left): player pays    150 % of item.value in gold.
# Inherits all grid/GPU rendering from ContainerGridUI; overrides only the
# transfer logic, titles, hint labels, and info strip.
# ─────────────────────────────────────────────────────────────────────────────

class TradeGridUI(ContainerGridUI):
    """Two-panel trade grid using the ContainerGridUI renderer.

    Left panel = player inventory (sell items).
    Right panel = merchant's inventory (buy items).

    Shift-click or drag-across-panels to buy / sell.
    Drag within the player panel reorders normally.
    Merchant panel items cannot be reordered by the player.
    """

    SELL_MULT: float = 0.75   # player sells at 75 % of base value
    BUY_MULT:  float = 1.50   # player buys  at 150 % of base value

    def __init__(self, engine: "Engine", container) -> None:
        super().__init__(engine, container)
        engine.context_hints = [
            ("Shift+Click", "Buy / Sell"),
            ("Drag",        "Buy / Sell"),
            ("Esc",         "Close"),
        ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _npc_name(self) -> str:
        return getattr(self.container.parent, "name", "Merchant")

    def _npc_color(self) -> tuple:
        col = getattr(self.container.parent, "color", None)
        if isinstance(col, (list, tuple)) and len(col) == 3:
            return tuple(col)
        return _TITLE_FG

    # ── Override rendering ────────────────────────────────────────────────────

    def _render_to_console(self, c: tcod.Console) -> None:
        W, H = _CC_W, _CC_H
        bf   = _BORDER_DIM

        c.tiles_rgb["bg"][:, :] = _BG
        c.tiles_rgb["fg"][:, :] = _BG
        c.tiles_rgb["ch"][:, :] = ord(" ")
        c.draw_frame(0, 0, W, H, fg=bf, bg=_BG)

        # Titles embedded in the top frame
        npc_name    = self._npc_name()
        right_title = f" {npc_name} "
        c.print(1, 0, " Inventory ", fg=_TITLE_FG, bg=_BG)
        c.print(_CC_RIGHT_ORI, 0, right_title[:(_CC_W - _CC_RIGHT_ORI - 1)],
                fg=self._npc_color(), bg=_BG)

        # Hint row — buy / sell labels
        c.print(2,                1, "\u2190 Sell \u00b775%",  fg=_HINT_FG, bg=_BG)
        c.print(_CC_RIGHT_ORI + 1, 1, "Buy \u00b7150% \u2192", fg=_HINT_FG, bg=_BG)

        # Vertical divider
        c.print(_CC_DIV_X, 0, "\u252c", fg=bf, bg=_BG)
        for y in range(1, _CC_INFO_SEP_Y):
            c.print(_CC_DIV_X, y, "\u2502", fg=bf, bg=_BG)

        # Horizontal separator at row 2
        for x in range(1, W - 1):
            c.print(x, 2, "\u2500", fg=bf, bg=_BG)
        c.print(0,         2, "\u251c", fg=bf, bg=_BG)
        c.print(_CC_DIV_X, 2, "\u253c", fg=bf, bg=_BG)
        c.print(W - 1,     2, "\u2524", fg=bf, bg=_BG)

        # Separator above info strip
        for x in range(1, W - 1):
            c.print(x, _CC_INFO_SEP_Y, "\u2500", fg=bf, bg=_BG)
        c.print(0,         _CC_INFO_SEP_Y, "\u251c", fg=bf, bg=_BG)
        c.print(_CC_DIV_X, _CC_INFO_SEP_Y, "\u2534", fg=bf, bg=_BG)
        c.print(W - 1,     _CC_INFO_SEP_Y, "\u2524", fg=bf, bg=_BG)

        # Scroll indicators
        p_max_s = max(0, -(-len(self._get_player_groups())    // _CC_GRID_COLS) - _CC_GRID_ROWS)
        c_max_s = max(0, -(-len(self._get_container_groups()) // _CC_GRID_COLS) - _CC_GRID_ROWS)
        if self._player_scroll > 0:
            c.print(_CC_DIV_X, _CC_GRID_ROW_ORI, "\u2191", fg=_BORDER_BRIGHT, bg=_BG)
        if self._player_scroll < p_max_s:
            c.print(_CC_DIV_X, _CC_INFO_SEP_Y - 1, "\u2193", fg=_BORDER_BRIGHT, bg=_BG)
        _scroll_r = _CC_W - 2
        if self._container_scroll > 0:
            c.print(_scroll_r, _CC_GRID_ROW_ORI, "\u2191", fg=_BORDER_BRIGHT, bg=_BG)
        if self._container_scroll < c_max_s:
            c.print(_scroll_r, _CC_INFO_SEP_Y - 1, "\u2193", fg=_BORDER_BRIGHT, bg=_BG)

        # Transparent holes for both item grids
        for ori in (_CC_LEFT_ORI, _CC_RIGHT_ORI):
            x1 = ori
            x2 = ori + _CC_GRID_COLS * _CC_GRID_SCALE
            y1 = _CC_GRID_ROW_ORI
            y2 = _CC_GRID_ROW_ORI + _CC_GRID_ROWS * _CC_GRID_SCALE
            c.tiles_rgb["bg"][x1:x2, y1:y2] = 0
            c.tiles_rgb["fg"][x1:x2, y1:y2] = 0
            c.tiles_rgb["ch"][x1:x2, y1:y2] = ord(" ")

        self._draw_info_strip(c)

    def _draw_info_strip(self, c: tcod.Console) -> None:
        item:   Optional["Item"] = None
        is_buy: bool             = False

        if self._sel_player >= 0:
            groups = self._get_player_groups()
            if self._sel_player < len(groups):
                item   = groups[self._sel_player]["item"]
                is_buy = False
        elif self._sel_container >= 0:
            groups = self._get_container_groups()
            if (self._sel_container < len(groups)
                    and groups[self._sel_container] is not None):
                item   = groups[self._sel_container]["item"]
                is_buy = True

        gold    = self.engine.player.gold
        gold_fg = (220, 180, 50) if gold > 0 else (160, 120, 50)

        if item is None:
            c.print(2, _CC_INFO_Y,
                    "Shift+LMB or drag to buy / sell",
                    fg=_HINT_FG, bg=_BG)
            c.print(2, _CC_INFO_Y + 1, f"Gold: {gold}", fg=gold_fg, bg=_BG)
            return

        name = item.name[:(_CC_W - 4)]
        c.print(2, _CC_INFO_Y, name,
                fg=getattr(item, "rarity_color", (220, 190, 120)), bg=_BG)

        if is_buy:
            price     = int(item.value * self.BUY_MULT)
            can_buy   = gold >= price
            price_col = (100, 210, 100) if can_buy else (200, 60, 40)
            c.print(2, _CC_INFO_Y + 1, f"Buy: {price}gp", fg=price_col, bg=_BG)
        else:
            price = int(item.value * self.SELL_MULT)
            c.print(2, _CC_INFO_Y + 1, f"Sell: {price}gp", fg=(160, 200, 100), bg=_BG)
        c.print(2, _CC_INFO_Y + 2, f"Gold: {gold}", fg=gold_fg, bg=_BG)

    # ── Trade-specific transfer helpers ───────────────────────────────────────

    def _transfer_to_container(self, item: "Item") -> None:
        """Sell item: remove from player inventory, credit gold at 75 % value."""
        if len(self.container.items) >= self.container.capacity:
            self.engine.message_log.add_message(
                "The merchant can't take any more items.", color.impossible)
            return
        if self.engine.player.equipment.item_is_equipped(item):
            self.engine.player.equipment.unequip_item(item, add_message=True)
        self.engine.player.inventory.items.remove(item)
        self.container.items.append(item)
        item.parent = self.container
        # Place in first free slot of the merchant's sparse slot list
        placed = False
        for i in range(len(self._container_slots)):
            if self._container_slots[i] is None:
                self._container_slots[i] = item
                placed = True
                break
        if not placed:
            self._container_slots.append(item)
        sell_price = int(item.value * self.SELL_MULT)
        self.engine.player.gold += sell_price
        sounds.play_equip_manycoins_sound()
        if hasattr(item, "drop_sound") and item.drop_sound is not None:
            item.drop_sound()
        self.engine.message_log.add_message(
            f"You sell the {item.name} for {sell_price}gp.")

    def _transfer_to_player(self, item: "Item") -> None:
        """Buy item: deduct gold at 150 % value, add item to player inventory."""
        buy_price = int(item.value * self.BUY_MULT)
        if self.engine.player.gold < buy_price:
            self.engine.message_log.add_message(
                f"You need {buy_price}gp to buy the {item.name}.",
                color.error)
            return
        if not self.engine.player.inventory.can_carry(item):
            self.engine.message_log.add_message(
                "You are carrying too much.", color.impossible)
            return
        self.container.items.remove(item)
        for i, s in enumerate(self._container_slots):
            if s is item:
                self._container_slots[i] = None
                break
        self.engine.player.inventory.items.append(item)
        item.parent = self.engine.player.inventory
        self.engine.player.gold -= buy_price
        sounds.play_equip_manycoins_sound()
        if hasattr(item, "pickup_sound") and item.pickup_sound is not None:
            item.pickup_sound()
        self.engine.message_log.add_message(
            f"You buy the {item.name} for {buy_price}gp.")

    # ── Override drag: suppress merchant-panel reorder ────────────────────────

    def _complete_drag(self, tx: int, ty: int) -> None:
        item     = self._drag_item
        src_type = self._drag_src_type
        src_idx  = self._drag_src_idx
        self._drag_item     = None
        self._drag_src_type = None
        self._drag_src_idx  = None
        if item is None:
            return

        left_cell  = self._hit_left_cell(tx, ty)
        right_cell = self._hit_right_cell(tx, ty)

        if left_cell is not None:
            col, row = left_cell
            dst_idx  = self._cell_to_idx(col, row, self._player_scroll)
            if src_type == "player":
                if dst_idx != src_idx:
                    self._swap_player_items(src_idx, dst_idx)
            elif src_type == "container":
                self._transfer_to_player(item)  # buy
            return

        if right_cell is not None:
            if src_type == "player":
                self._transfer_to_container(item)  # sell
            # Merchant's panel — don't allow player to reorder their wares
            return

        # Released outside any panel — drop player items on the ground
        ix, iy = self._to_panel(tx, ty)
        if not (0 <= ix < _CC_W and 0 <= iy < _CC_H):
            if src_type == "player":
                actions.DropItem(self.engine.player, item).perform()
        elif hasattr(item, "drop_sound") and item.drop_sound is not None:
            item.drop_sound()

