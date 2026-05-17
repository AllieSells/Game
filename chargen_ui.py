"""chargen_ui.py — Mouse-driven character creation popup.

Shown once after world generation completes, immediately after the CRT
screen-on animation.  The overworld map is rendered live as the backdrop;
the player customises their character before entering the tutorial floor.

Data is loaded from json/chargen.json and json/professions.json so new
origins, professions, and appearance options can be added without touching
this file. IMPORTANT: Only use trait names that exist in components.level.Level.TRAITS
when adding new origins or professions. See add_new_traits() instructions in level.py.

Optional Python hooks can be registered in a side-car module chargen_hooks.py.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Set

import tcod
import tcod.event
from tcod.console import Console

import color
import sounds
from input_handlers import PopupEventHandler
from render_functions import MenuRenderer
from components.level import Level
from balance_config import STARTING_MANA_BASE, STARTING_MANA_PER_ARCANA_LEVEL, VIGOR_HP_PER_LEVEL

if TYPE_CHECKING:
    from engine import Engine

# ─── Layout constants ─────────────────────────────────────────────────────────
# The popup sits centred on an 80×50 tile console.
_POP_W  = 64
_POP_H  = 42
_POP_X  = (80 - _POP_W) // 2   # = 8
_POP_Y  = (50 - _POP_H) // 2   # = 4

_SIDE_W = 13          # sidebar width (left border + labels + arrow indicator)
_DIV_X  = _POP_X + _SIDE_W          # column of the vertical divider  (= 21)
_CONT_X = _DIV_X + 1                # first column of the content area (= 22)
_CONT_Y = _POP_Y + 2                # first content row                (= 6)
_CONT_W = _POP_W - _SIDE_W - 2     # content area width               (= 49)
_LIST_W = 20          # list column width (name column in class/bg/equip sections)
# Bottom bar separator lives at _POP_Y+_POP_H-4; content must stay above it.
_CONT_H = _POP_H - 8               # = 34  (max_y = _CONT_Y + _CONT_H = 40)

_SECTIONS = ["Name", "Origin", "Profession", "Appearance", "Review"]

# Portrait layer fields — (knowledge_key, [option_values])
# "none" maps to None when written to knowledge so layers are skipped.
_PORTRAIT_FIELDS: List[Tuple[str, List[str]]] = [
    ("gender",      ["Male", "Female"]),
    ("skin_tone",   ["fair", "pale", "very pale", "light olive", "tan", "brown", "dark"]),
    ("hair_color",  ["brown", "black", "blonde", "red", "gray", "white", "none"]),
    ("hair_style",  ["short", "long", "curly", "wavy", "straight"]),
    ("facial_hair", ["none", "bearded", "stubbled", "mustached", "goateed"]),
]

_CHARGEN_JSON = Path(__file__).parent / "json" / "chargen.json"
_PROFESSIONS_JSON = Path(__file__).parent / "json" / "professions.json"

_KNOWN_ORIGIN_PERKS = {
    "starting_gold",
    "bonus_hp",
    "bonus_mana",
    "bonus_hunger",
    "bonus_saturation",
}


def _get_valid_traits() -> Set[str]:
    """Load valid trait names from Level.TRAITS for validation."""
    return set(Level.TRAITS)


def _validate_chargen_traits(data: dict) -> None:
    """Warn about invalid trait references in chargen data.
    
    Traits used in origins and professions must be defined in 
    components.level.Level.TRAITS. Invalid traits will be silently 
    skipped at character creation time, so this warning helps catch issues early.
    """
    valid = _get_valid_traits()
    
    # Check origin aptitudes
    for origin in data.get("origins", []):
        for trait in origin.get("aptitudes", {}).keys():
            if trait not in valid:
                print(f"[chargen] WARNING: Invalid trait '{trait}' in origin '{origin.get('id')}'. "
                      f"Add it to Level.TRAITS in components/level.py. "
                      f"Valid traits: {sorted(valid)}")
    
    # Check profession skills
    for prof in data.get("professions", []):
        for trait in prof.get("skills", {}).keys():
            if trait not in valid:
                print(f"[chargen] WARNING: Invalid trait '{trait}' in profession '{prof.get('id')}'. "
                      f"Add it to Level.TRAITS in components/level.py. "
                      f"Valid traits: {sorted(valid)}")


def _build_spell_class_map() -> Dict[str, type]:
    """Build a name->class map for all spell classes in components.spells."""
    from components import spells as spells_module
    from components.spells import Spell

    spell_map: Dict[str, type] = {}
    for attr_name in dir(spells_module):
        obj = getattr(spells_module, attr_name, None)
        if not isinstance(obj, type):
            continue
        if not issubclass(obj, Spell) or obj is Spell:
            continue
        try:
            spell_obj = obj()
        except Exception:
            # Ignore non-instantiable classes so chargen stays robust.
            continue
        spell_map[spell_obj.name.lower()] = obj

    return spell_map


def _validate_starting_spells(data: dict) -> None:
    """Warn about invalid spell names in profession starting_spells lists."""
    spell_map = _build_spell_class_map()

    for prof in data.get("professions", []):
        for spell_name in prof.get("starting_spells", []) or []:
            if str(spell_name).lower() not in spell_map:
                print(
                    f"[chargen] WARNING: Unknown starting spell '{spell_name}' "
                    f"in profession '{prof.get('id')}'."
                )


def _validate_origin_perks(data: dict) -> None:
    """Warn about unknown origin perk keys so data stays modular and safe."""
    for origin in data.get("origins", []):
        perks = origin.get("origin_perks", {}) or {}
        for key in perks.keys():
            if key not in _KNOWN_ORIGIN_PERKS:
                print(
                    f"[chargen] WARNING: Unknown origin perk '{key}' in origin "
                    f"'{origin.get('id')}'. Known perks: {sorted(_KNOWN_ORIGIN_PERKS)}"
                )


def _load_data() -> dict:
    with open(_CHARGEN_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    with open(_PROFESSIONS_JSON, encoding="utf-8") as fh:
        data["professions"] = json.load(fh)
    # Validate that all traits in chargen data exist in Level.TRAITS
    _validate_chargen_traits(data)
    # Validate spell names used in profession starting spell grants.
    _validate_starting_spells(data)
    # Validate optional origin gameplay perks.
    _validate_origin_perks(data)
    return data


# Shift-key symbol map for name text input (same pattern as rest of codebase)
_SHIFT_MAP: Dict[str, str] = {
    '`': '~', '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
    '6': '^', '7': '&', '8': '*', '9': '(', '0': ')', '-': '_',
    '=': '+', '[': '{', ']': '}', '\\': '|', ';': ':', "'": '"',
    ',': '<', '.': '>', '/': '?',
}

def _key_to_char(event: tcod.event.KeyDown) -> str:
    """Return the printable char for a keydown event, or '' if none."""
    code = int(event.sym)
    if code < 32 or code > 126:
        return ''
    ch = chr(code)
    shifted = bool(event.mod & (tcod.event.Modifier.LSHIFT | tcod.event.Modifier.RSHIFT))
    if shifted:
        return ch.upper() if ch.isalpha() else _SHIFT_MAP.get(ch, ch)
    return ch


def _format_origin_perk_label(key: str, value: int) -> str:
    """Return a concise label for a supported origin perk."""
    if key == "starting_gold":
        return f"Starting Gold: +{int(value)}"
    if key == "bonus_hp":
        return f"Max HP: +{int(value)}"
    if key == "bonus_mana":
        return f"Max Mana: +{int(value)}"
    if key == "bonus_hunger":
        return f"Hunger Reserve: +{int(value)}"
    if key == "bonus_saturation":
        return f"Saturation: +{int(value)}"
    return f"{key}: {value}"


def _format_starting_item_labels(starting_items: List[str], equip_pool: List[dict]) -> List[str]:
    """Return display labels for starting items, collapsing duplicate refs."""
    item_names: Dict[str, str] = {}
    for item in equip_pool:
        ref = item.get("ref", "")
        if ref and ref not in item_names:
            default_name = ref.replace("_", " ").title()
            item_names[ref] = item.get("name", default_name)

    grouped_items: Dict[str, int] = {}
    for ref in starting_items or []:
        grouped_items[ref] = grouped_items.get(ref, 0) + 1

    labels: List[str] = []
    for ref, count in grouped_items.items():
        item_name = item_names.get(ref, ref.replace("_", " ").title())
        has_inline_count = "(x" in item_name.lower()
        labels.append(f"{item_name} {count}x" if count > 1 and not has_inline_count else item_name)
    return labels


# ──────────────────────────────────────────────────────────────────────────────

class CharacterCreationHandler(PopupEventHandler):
    """Modal character-creation screen shown over the live overworld map."""

    def __init__(self, engine: "Engine") -> None:
        super().__init__(engine)
        self._data = _load_data()

        # ── selections ────────────────────────────────────────────────
        self._section: int = 0

        self._name: str = "Adventurer"
        self._name_cursor: int = len(self._name)
        self._name_focused: bool = True   # auto-focus the name field

        self._bg_idx: int = 0
        self._bg_scroll: int = 0

        self._prof_idx: int = 0
        self._prof_scroll: int = 0

        # Portrait appearance — indexed per field
        self._portrait_sel: int = 0
        self._portrait_idxs: Dict[str, int] = {f: 0 for f, _ in _PORTRAIT_FIELDS}
        self._portrait_path: Optional[str] = None
        self._portrait_dest_tiles: Optional[Tuple[int, int, int, int]] = None
        self._rebuild_portrait()

        # Item pool (used for resolving profession kit labels)
        self._equip_pool: List[dict] = self._data.get("items_pool", [])

        # ── backdrop: the map the player starts on (tutorial floor) ─────
        self._bg_map = engine.game_map

        # ── hover tracking (reset each frame by ev_mousemotion) ───────
        self._hovered_y:       int = -1   # screen-y of hovered row
        self._hovered_section: int = -1   # sidebar index being hovered

        # ── per-frame hit regions (rebuilt each on_render call) ───────
        self._sidebar_ys: List[int] = []
        # Each entry: (screen_y, absolute_index_in_list)
        self._list_hit_rows: List[Tuple[int, int]] = []
        # Appearance arrow click zones — (left_pos, right_pos) per field row
        self._portrait_arrows: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
        # Confirm button rect (x, y, w, h)
        self._confirm_rect: Optional[Tuple[int, int, int, int]] = None
        # Name field text row (x, y, max_chars)
        self._name_field: Optional[Tuple[int, int, int]] = None

    # ────────────────────────────────────────────────────────────────────
    # Portrait builder
    # ────────────────────────────────────────────────────────────────────

    def _rebuild_portrait(self) -> None:
        """Composite a fresh portrait PNG from the current knowledge selections."""
        import sprite_manager as _sm

        class _MockActor:
            def __init__(self, know: dict) -> None:
                self.knowledge = know
                self._portrait_path: Optional[str] = None
                self.name = "Player"
                self.char = chr(0xE03C)

        know: Dict[str, object] = {}
        for field, opts in _PORTRAIT_FIELDS:
            val = opts[self._portrait_idxs.get(field, 0) % len(opts)]
            know[field] = None if val == "none" else val

        mock = _MockActor(know)
        _sm.compose_portrait(mock)
        self._portrait_path = mock._portrait_path

    # ────────────────────────────────────────────────────────────────────
    # Convenience properties
    # ────────────────────────────────────────────────────────────────────

    @property
    def _professions(self) -> List[dict]:
        return self._data.get("professions", [])

    @property
    def _origins(self) -> List[dict]:
        # Keep fallback for existing save/data compatibility.
        return self._data.get("origins", self._data.get("backgrounds", []))



    def _selected_origin(self) -> dict:
        if self._origins and 0 <= self._bg_idx < len(self._origins):
            return self._origins[self._bg_idx]
        return {}

    def _selected_profession(self) -> dict:
        if self._professions and 0 <= self._prof_idx < len(self._professions):
            return self._professions[self._prof_idx]
        return {}

    def _calculate_character_modifiers(self) -> Dict[str, int]:
        """Combine origin aptitudes and profession skills into one modifier map."""
        origin = self._selected_origin()
        profession = self._selected_profession()

        modifiers: Dict[str, int] = {}
        for trait, value in (origin.get("aptitudes", {}) or {}).items():
            modifiers[trait] = modifiers.get(trait, 0) + int(value)
        for trait, value in (profession.get("skills", {}) or {}).items():
            modifiers[trait] = modifiers.get(trait, 0) + int(value)
        return modifiers

    def _create_character_setup(self) -> dict:
        """Create a final setup object from selected origin + profession."""
        origin = self._selected_origin()
        prof = self._selected_profession()
        return {
            "origin_id": origin.get("id", ""),
            "profession_id": prof.get("id", ""),
            "aptitudes": dict(origin.get("aptitudes", {}) or {}),
            "origin_perks": dict(origin.get("origin_perks", {}) or {}),
            "skills": dict(prof.get("skills", {}) or {}),
            "starting_spells": list(prof.get("starting_spells", []) or []),
            "starting_items": list(prof.get("starting_items", []) or []),
            "origin_tags": list(origin.get("tags", []) or []),
            "profession_tags": list(prof.get("tags", []) or []),
        }


    # ────────────────────────────────────────────────────────────────────
    # Keyboard  (handled entirely in ev_keydown — no ev_textinput)
    # ────────────────────────────────────────────────────────────────────

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional["CharacterCreationHandler"]:
        sym = event.sym

        # Ignore bare modifier keys
        if sym in {tcod.event.K_LSHIFT, tcod.event.K_RSHIFT,
                   tcod.event.K_LCTRL,  tcod.event.K_RCTRL,
                   tcod.event.K_LALT,   tcod.event.K_RALT}:
            return self

        # ── Name field ────────────────────────────────────────────────
        if self._name_focused and self._section == 0:
            if sym == tcod.event.KeySym.BACKSPACE:
                if self._name_cursor > 0:
                    self._name = (self._name[:self._name_cursor - 1]
                                  + self._name[self._name_cursor:])
                    self._name_cursor -= 1
            elif sym == tcod.event.KeySym.DELETE:
                if self._name_cursor < len(self._name):
                    self._name = (self._name[:self._name_cursor]
                                  + self._name[self._name_cursor + 1:])
            elif sym == tcod.event.KeySym.LEFT:
                self._name_cursor = max(0, self._name_cursor - 1)
            elif sym == tcod.event.KeySym.RIGHT:
                self._name_cursor = min(len(self._name), self._name_cursor + 1)
            elif sym == tcod.event.KeySym.HOME:
                self._name_cursor = 0
            elif sym == tcod.event.KeySym.END:
                self._name_cursor = len(self._name)
            elif sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER,
                         tcod.event.KeySym.TAB):
                self._name_focused = False
                self._section = 1
                sounds.play_ui_move_sound()
            else:
                ch = _key_to_char(event)
                if ch and len(self._name) < 30:
                    self._name = (self._name[:self._name_cursor]
                                  + ch + self._name[self._name_cursor:])
                    self._name_cursor += 1
            return self

        # ── Global ────────────────────────────────────────────────────
        if sym == tcod.event.KeySym.ESCAPE:
            return self._apply_and_confirm()

        s = self._section

        if sym in (tcod.event.KeySym.UP, tcod.event.KeySym.DOWN):
            d = -1 if sym == tcod.event.KeySym.UP else 1
            _mv = _CONT_H - 2
            if s == 1 and self._origins:
                self._bg_idx = max(0, min(len(self._origins) - 1,
                                          self._bg_idx + d))
                if self._bg_idx < self._bg_scroll:
                    self._bg_scroll = self._bg_idx
                elif self._bg_idx >= self._bg_scroll + _mv:
                    self._bg_scroll = self._bg_idx - _mv + 1
                sounds.play_ui_move_sound()
            elif s == 2 and self._professions:
                self._prof_idx = max(0, min(len(self._professions) - 1,
                                            self._prof_idx + d))
                if self._prof_idx < self._prof_scroll:
                    self._prof_scroll = self._prof_idx
                elif self._prof_idx >= self._prof_scroll + _mv:
                    self._prof_scroll = self._prof_idx - _mv + 1
                sounds.play_ui_move_sound()
            elif s == 3:
                self._portrait_sel = max(0, min(len(_PORTRAIT_FIELDS) - 1,
                                                self._portrait_sel + d))
                sounds.play_ui_move_sound()

        elif sym in (tcod.event.KeySym.LEFT, tcod.event.KeySym.RIGHT) and s == 3:
            field, opts = _PORTRAIT_FIELDS[self._portrait_sel]
            d = -1 if sym == tcod.event.KeySym.LEFT else 1
            self._portrait_idxs[field] = (self._portrait_idxs[field] + d) % len(opts)
            self._rebuild_portrait()
            sounds.play_ui_move_sound()

        elif sym == tcod.event.KeySym.TAB:
            self._name_focused = False
            self._section = (self._section + 1) % len(_SECTIONS)
            sounds.play_ui_move_sound()

        elif sym in (tcod.event.KeySym.RETURN, tcod.event.KeySym.KP_ENTER,
                     tcod.event.KeySym.SPACE):
            if s == len(_SECTIONS) - 1:
                return self._apply_and_confirm()
            else:
                self._section = (self._section + 1) % len(_SECTIONS)
                sounds.play_ui_move_sound()

        return self

    # ────────────────────────────────────────────────────────────────────
    # Mouse
    # ────────────────────────────────────────────────────────────────────

    def on_exit(self) -> "CharacterCreationHandler":
        # Clicking outside the popup keeps it open (no accidental game start)
        return self

    def on_left_click(self, mx: int, my: int) -> Optional["CharacterCreationHandler"]:
        # ── Confirm button ────────────────────────────────────────────
        if self._confirm_rect:
            cx, cy, cw, ch = self._confirm_rect
            if cx <= mx < cx + cw and cy <= my < cy + ch:
                return self._apply_and_confirm()

        # ── Sidebar section tabs ──────────────────────────────────────
        for i, sy in enumerate(self._sidebar_ys):
            if my == sy and _POP_X + 1 <= mx < _DIV_X:
                if i != self._section:
                    self._section = i
                    self._name_focused = False
                    sounds.play_ui_move_sound()
                return self

        # ── Name field click ──────────────────────────────────────────
        if self._section == 0 and self._name_field is not None:
            fx, fy, fw = self._name_field
            if my == fy and fx <= mx < fx + fw:
                self._name_focused = True
                offset = mx - fx
                self._name_cursor = min(max(0, offset), len(self._name))
                return self
            self._name_focused = False
            return self

        # ── Scrollable list items (origin / profession) ───────────────
        for screen_y, abs_idx in self._list_hit_rows:
            if my == screen_y and _CONT_X <= mx < _CONT_X + _LIST_W:
                self._on_list_select(abs_idx)
                return self

        # ── Appearance portrait arrows ────────────────────────────────
        if self._section == 3:
            for i, (al, ar) in enumerate(self._portrait_arrows):
                if (mx, my) == al:
                    field, opts = _PORTRAIT_FIELDS[i]
                    self._portrait_idxs[field] = (self._portrait_idxs[field] - 1) % len(opts)
                    self._portrait_sel = i
                    self._rebuild_portrait()
                    sounds.play_ui_move_sound()
                    return self
                if (mx, my) == ar:
                    field, opts = _PORTRAIT_FIELDS[i]
                    self._portrait_idxs[field] = (self._portrait_idxs[field] + 1) % len(opts)
                    self._portrait_sel = i
                    self._rebuild_portrait()
                    sounds.play_ui_move_sound()
                    return self

        return self

    def ev_mousemotion(self, event: tcod.event.MouseMotion) -> "CharacterCreationHandler":
        mx, my = int(event.tile.x), int(event.tile.y)
        # ── sidebar section hover ─────────────────────────────────────
        self._hovered_section = -1
        for i, sy in enumerate(self._sidebar_ys):
            if my == sy and _POP_X + 1 <= mx < _DIV_X:
                self._hovered_section = i
                break
        # ── content row hover ─────────────────────────────────────────
        # Track by screen-y; used by list rows and stat rows
        if _CONT_X <= mx < _POP_X + _POP_W - 1 and _CONT_Y <= my < _CONT_Y + _CONT_H:
            self._hovered_y = my
        else:
            self._hovered_y = -1
        return self

    def ev_mousewheel(self, event: tcod.event.MouseWheel) -> "CharacterCreationHandler":
        delta = 1 if event.y < 0 else -1
        s = self._section
        if s == 1:
            mx = max(0, len(self._origins) - (_CONT_H - 2))
            self._bg_scroll = max(0, min(mx, self._bg_scroll + delta))
        elif s == 2:
            mx = max(0, len(self._professions) - (_CONT_H - 2))
            self._prof_scroll = max(0, min(mx, self._prof_scroll + delta))
        return self

    def _on_list_select(self, abs_idx: int) -> None:
        s = self._section
        if s == 1 and 0 <= abs_idx < len(self._origins):
            self._bg_idx = abs_idx
            sounds.play_ui_move_sound()
        elif s == 2 and 0 <= abs_idx < len(self._professions):
            self._prof_idx = abs_idx
            sounds.play_ui_move_sound()

    # ────────────────────────────────────────────────────────────────────
    # Rendering
    # ────────────────────────────────────────────────────────────────────

    def on_render(self, console: Console) -> None:
        # 1. Render the tutorial floor (engine.game_map) as the backdrop.
        self._bg_map.render(console)

        # 2. Dim everything outside (and inside) the popup
        self.render_faded(console, _POP_X, _POP_Y, _POP_W, _POP_H)

        # 3. Register popup bounds for click-outside handling
        self._set_popup_bounds(_POP_X, _POP_Y, _POP_W, _POP_H)

        # 4. Parchment background + ornate border
        MenuRenderer.draw_parchment_background(console, _POP_X, _POP_Y,
                                               _POP_W, _POP_H)
        MenuRenderer.draw_ornate_border(console, _POP_X, _POP_Y,
                                        _POP_W, _POP_H, "Character Creation")

        # 5. Sidebar section navigator
        self._render_sidebar(console)

        # 6. Vertical divider — runs from top border down to the bottom separator only
        _sep_y = _POP_Y + _POP_H - 4   # row of the bottom bar horizontal separator
        for row in range(_POP_Y + 1, _sep_y):
            console.print(x=_DIV_X, y=row, string="│", fg=color.dark_gray, bg=color.parchment_bg)
        console.print(x=_DIV_X, y=_POP_Y,  string="┬", fg=color.dark_gray, bg=color.parchment_bg)
        console.print(x=_DIV_X, y=_sep_y,  string="┴", fg=color.dark_gray, bg=color.parchment_bg)

        # 7. Active section content
        self._render_section(console)

        # 8. Bottom summary bar + confirm button
        self._render_bottom_bar(console)

    # ─── Sidebar ──────────────────────────────────────────────────────

    def _render_sidebar(self, console: Console) -> None:
        self._sidebar_ys = []
        for i, label in enumerate(_SECTIONS):
            y = _CONT_Y + i
            self._sidebar_ys.append(y)
            selected = (i == self._section)
            hovered  = (i == self._hovered_section) and not selected
            if selected:
                fg, bg = color.menu_title, (80, 60, 30)
            elif hovered:
                fg, bg = color.white, (55, 45, 20)
            else:
                fg, bg = color.dark_gray, color.parchment_bg
            text = f" {label:<{_SIDE_W - 3}}"[:_SIDE_W - 2]
            console.print(x=_POP_X + 1, y=y, string=text, fg=fg, bg=bg)
            if selected:
                console.print(x=_DIV_X - 1, y=y, string=">",
                              fg=color.menu_title)

    # ─── Section dispatcher ───────────────────────────────────────────

    def _render_section(self, console: Console) -> None:
        # Reset per-frame hit regions
        self._list_hit_rows = []
        # Portrait overlay is drawn by main.py when these fields are set.
        # Clear them each frame so only the Appearance section can opt in.
        self._portrait_dest_tiles = None
        self._portrait_arrows = []
        s = self._section
        if s == 0:
            self._render_name(console)
        elif s == 1:
            self._render_list(console, self._origins, self._bg_idx, self._bg_scroll)
        elif s == 2:
            self._render_list(console, self._professions, self._prof_idx, self._prof_scroll)
        elif s == 3:
            self._render_appearance(console)
        elif s == 4:
            self._render_review(console)

    # ─── Name ─────────────────────────────────────────────────────────

    def _render_name(self, console: Console) -> None:
        cx = _CONT_X + 2
        cy = _CONT_Y + 2
        console.print(x=cx, y=cy, string="What are you called, traveller?", fg=color.menu_title)
        cy += 2

        fw = _CONT_W - 8      # input box width
        frame_fg = color.menu_title if self._name_focused else color.dark_gray
        console.draw_frame(x=cx, y=cy, width=fw, height=3,
                           fg=frame_fg, bg=color.parchment_bg)

        # Clip the name to the visible portion of the field
        max_vis = fw - 2
        start   = max(0, self._name_cursor - max_vis + 1)
        visible = self._name[start:start + max_vis]
        vis_cur = self._name_cursor - start

        console.print(x=cx + 1, y=cy + 1, string=visible, fg=color.white)

        if self._name_focused:
            if vis_cur < len(visible):
                console.print(x=cx + 1 + vis_cur, y=cy + 1,
                              string=visible[vis_cur],
                              fg=color.black, bg=color.white)
            else:
                console.print(x=cx + 1 + vis_cur, y=cy + 1,
                              string="_", fg=color.white)

        # Store hit region for click-to-focus
        self._name_field = (cx + 1, cy + 1, fw - 2)
        cy += 5


    # ─── Scrollable list (origin / profession) ────────────────────────

    def _render_list(self, console: Console, items: list,
                     selected: int, scroll: int) -> None:
        LIST_W = 20
        desc_x = _CONT_X + LIST_W + 2
        desc_w = _CONT_W - LIST_W - 4
        max_vis = _CONT_H - 2

        # Header rule
        console.print(x=_CONT_X, y=_CONT_Y,
                      string="─" * LIST_W, fg=color.dark_gray)
        console.print(x=desc_x,  y=_CONT_Y,
                      string="─" * min(desc_w, _POP_X + _POP_W - desc_x - 1),
                      fg=color.dark_gray)

        # List entries
        visible = items[scroll:scroll + max_vis]
        for i, item in enumerate(visible):
            abs_i = i + scroll
            y     = _CONT_Y + 1 + i
            self._list_hit_rows.append((y, abs_i))
            sel = (abs_i == selected)
            hov = (y == self._hovered_y) and not sel
            if sel:
                bg, fg = (80, 60, 30), color.white
            elif hov:
                bg, fg = (55, 45, 20), color.white
            else:
                bg, fg = color.parchment_bg, color.dark_gray
            prefix = ">" if sel else ("~" if hov else " ")
            label = f"{prefix}{item.get('name', '???'):<{LIST_W - 1}}"[:LIST_W]
            console.print(x=_CONT_X, y=y, string=label, fg=fg, bg=bg)

        # Scroll arrows
        if scroll > 0:
            console.print(x=_CONT_X + LIST_W // 2, y=_CONT_Y,
                          string="▲", fg=color.dark_gray)
        if scroll + max_vis < len(items):
            console.print(x=_CONT_X + LIST_W // 2,
                          y=_CONT_Y + 1 + len(visible),
                          string="▼", fg=color.dark_gray)

        # Description panel for the highlighted entry
        if 0 <= selected < len(items):
            sel_item = items[selected]
            dy = _CONT_Y + 1
            dy = self._print_wrapped(console,
                                     sel_item.get("description", ""),
                                     desc_x, dy, desc_w,
                                     color.light_gray)
            dy += 1

            aptitudes = sel_item.get("aptitudes", {})
            if aptitudes:
                if dy < _CONT_Y + _CONT_H:
                    console.print(x=desc_x, y=dy,
                                  string="Aptitudes:", fg=color.menu_title)
                    dy += 1
                for trait, val in aptitudes.items():
                    if dy >= _CONT_Y + _CONT_H:
                        break
                    label = str(trait).replace("_", " ").title()
                    if isinstance(val, (int, float)):
                        sign = "+" if val >= 0 else ""
                        value_text = f"{sign}{val}"
                    else:
                        value_text = str(val)
                    console.print(x=desc_x, y=dy,
                                  string=f"  {label}: {value_text}",
                                  fg=color.welcome_text)
                    dy += 1

            # For origins: show gameplay perks that are distinct from profession skills.
            origin_perks = sel_item.get("origin_perks", {})
            if origin_perks:
                dy += 1
                if dy < _CONT_Y + _CONT_H:
                    console.print(x=desc_x, y=dy,
                                  string="Origin Perks:", fg=color.menu_title)
                    dy += 1
                for key, value in origin_perks.items():
                    if dy >= _CONT_Y + _CONT_H:
                        break
                    console.print(x=desc_x, y=dy,
                                  string=f"  {_format_origin_perk_label(str(key), int(value))}",
                                  fg=color.light_gray)
                    dy += 1

            tags = sel_item.get("tags", [])
            if tags:
                dy += 1
                if dy < _CONT_Y + _CONT_H:
                    console.print(x=desc_x, y=dy,
                                  string="Tags:", fg=color.menu_title)
                    dy += 1
                for tag in tags:
                    if dy >= _CONT_Y + _CONT_H:
                        break
                    console.print(x=desc_x, y=dy,
                                  string=f"  {tag}",
                                  fg=color.light_gray)
                    dy += 1

            # For professions: show skill gains.
            skills = sel_item.get("skills", {})
            if skills:
                dy += 1
                if dy < _CONT_Y + _CONT_H:
                    console.print(x=desc_x, y=dy,
                                  string="Skills:", fg=color.menu_title)
                    dy += 1
                for skill, level in skills.items():
                    if dy >= _CONT_Y + _CONT_H:
                        break
                    label = str(skill).replace("_", " ").title()
                    sign = "+" if int(level) >= 0 else ""
                    console.print(x=desc_x, y=dy,
                                  string=f"  {label}: {sign}{level}",
                                  fg=color.welcome_text)
                    dy += 1

            # For professions: show starting kit.
            starting_items = sel_item.get("starting_items", [])
            if starting_items:
                dy += 1
                if dy < _CONT_Y + _CONT_H:
                    console.print(x=desc_x, y=dy,
                                  string="Starting items:", fg=color.menu_title)
                    dy += 1
                for item_label in _format_starting_item_labels(starting_items, self._equip_pool):
                    if dy >= _CONT_Y + _CONT_H:
                        break
                    console.print(x=desc_x, y=dy,
                                  string=f"  {item_label}",
                                  fg=color.light_gray)
                    dy += 1

            # For professions: show persistent starting spell unlocks.
            starting_spells = sel_item.get("starting_spells", [])
            if starting_spells:
                dy += 1
                if dy < _CONT_Y + _CONT_H:
                    console.print(x=desc_x, y=dy,
                                  string="Starting spells:", fg=color.menu_title)
                    dy += 1
                for spell_name in starting_spells:
                    if dy >= _CONT_Y + _CONT_H:
                        break
                    console.print(x=desc_x, y=dy,
                                  string=f"  {spell_name}",
                                  fg=color.light_gray)
                    dy += 1

    # ─── Review ───────────────────────────────────────────────────────

    def _render_review(self, console: Console) -> None:
        origin = self._selected_origin()
        prof = self._selected_profession()
        mods = self._calculate_character_modifiers()

        x = _CONT_X
        y = _CONT_Y
        console.print(x=x, y=y, string=f"Name: {self._name}", fg=color.menu_title)
        y += 1
        console.print(x=x, y=y, string=f"Origin: {origin.get('name', '—')}", fg=color.light_gray)
        y += 1
        console.print(x=x, y=y, string=f"Profession: {prof.get('name', '—')}", fg=color.light_gray)
        y += 2

        console.print(x=x, y=y, string="Aptitudes:", fg=color.menu_title)
        y += 1
        for trait, val in (origin.get("aptitudes", {}) or {}).items():
            if y >= _CONT_Y + _CONT_H:
                return
            sign = "+" if int(val) >= 0 else ""
            label = str(trait).replace("_", " ").title()
            console.print(x=x, y=y, string=f"  {label}: {sign}{val}", fg=color.welcome_text)
            y += 1

        origin_perks = origin.get("origin_perks", {}) or {}
        if origin_perks:
            y += 1
            if y >= _CONT_Y + _CONT_H:
                return
            console.print(x=x, y=y, string="Origin Perks:", fg=color.menu_title)
            y += 1
            for key, value in origin_perks.items():
                if y >= _CONT_Y + _CONT_H:
                    return
                console.print(
                    x=x,
                    y=y,
                    string=f"  {_format_origin_perk_label(str(key), int(value))}",
                    fg=color.light_gray,
                )
                y += 1

        y += 1
        if y >= _CONT_Y + _CONT_H:
            return
        console.print(x=x, y=y, string="Profession Skills:", fg=color.menu_title)
        y += 1
        for trait, val in (prof.get("skills", {}) or {}).items():
            if y >= _CONT_Y + _CONT_H:
                return
            sign = "+" if int(val) >= 0 else ""
            label = str(trait).replace("_", " ").title()
            console.print(x=x, y=y, string=f"  {label}: {sign}{val}", fg=color.welcome_text)
            y += 1

        starting_spells = prof.get("starting_spells", []) or []
        if starting_spells:
            y += 1
            if y >= _CONT_Y + _CONT_H:
                return
            console.print(x=x, y=y, string="Starting Spells:", fg=color.menu_title)
            y += 1
            for spell_name in starting_spells:
                if y >= _CONT_Y + _CONT_H:
                    return
                console.print(x=x, y=y, string=f"  {spell_name}", fg=color.light_gray)
                y += 1

        y += 1
        if y >= _CONT_Y + _CONT_H:
            return
        console.print(x=x, y=y, string="Starting Kit:", fg=color.menu_title)
        y += 1
        for item_label in _format_starting_item_labels(prof.get("starting_items", []) or [], self._equip_pool):
            if y >= _CONT_Y + _CONT_H:
                return
            console.print(x=x, y=y, string=f"  {item_label}", fg=color.light_gray)
            y += 1

        y += 1
        if y >= _CONT_Y + _CONT_H:
            return
        console.print(x=x, y=y, string="Tags:", fg=color.menu_title)
        y += 1
        for tag in list(origin.get("tags", []) or []) + list(prof.get("tags", []) or []):
            if y >= _CONT_Y + _CONT_H:
                return
            console.print(x=x, y=y, string=f"  {tag}", fg=color.light_gray)
            y += 1

        # Quick final modifier summary to aid readability.
        y += 1
        if y < _CONT_Y + _CONT_H:
            console.print(x=x, y=y, string="Final Modifiers:", fg=color.menu_title)
            y += 1
        for trait, val in mods.items():
            if y >= _CONT_Y + _CONT_H:
                break
            sign = "+" if int(val) >= 0 else ""
            label = str(trait).replace("_", " ").title()
            console.print(x=x, y=y, string=f"  {label}: {sign}{val}", fg=color.light_gray)
            y += 1

    # ─── Appearance ───────────────────────────────────────────────────

    def _render_appearance(self, console: Console) -> None:
        # Portrait preview box on the right side of the content area
        PORT_COL = _POP_X + _POP_W - 13   # col 59 — 10 wide, right-aligned
        PORT_ROW = _CONT_Y + 1             # row 7
        PORT_W   = 10
        PORT_H   = 12
        # Dark background tile-block — main.py blits the PNG portrait on top
        console.draw_rect(PORT_COL, PORT_ROW, PORT_W, PORT_H,
                          ch=ord(' '), fg=color.black, bg=(20, 15, 10))
        console.draw_frame(PORT_COL - 1, PORT_ROW - 1, PORT_W + 2, PORT_H + 2,
                           title="Portrait",
                           fg=color.dark_gray, bg=color.parchment_bg)
        self._portrait_dest_tiles = (PORT_COL, PORT_ROW, PORT_W, PORT_H)

        # Field rows on the left side
        self._portrait_arrows = []
        cx = _CONT_X + 1   # col 23
        cy = _CONT_Y + 1   # row 7
        for i, (field, opts) in enumerate(_PORTRAIT_FIELDS):
            selected = (i == self._portrait_sel)
            row_bg   = (60, 48, 22) if selected else color.parchment_bg
            val      = opts[self._portrait_idxs.get(field, 0) % len(opts)]
            label    = field.replace("_", " ").title()
            # label (12) · ◄ · value (13) · ►
            al = (cx + 13, cy)
            ar = (cx + 28, cy)
            fg_label = color.menu_title if selected else color.dark_gray
            fg_val   = color.white      if selected else color.light_gray
            console.print(x=cx,       y=cy, string=f"{label:<12}",    fg=fg_label, bg=row_bg)
            console.print(x=al[0],    y=cy, string="\u25c4",           fg=color.menu_title, bg=row_bg)
            console.print(x=al[0]+1,  y=cy, string=f" {val:<13}",      fg=fg_val,   bg=row_bg)
            console.print(x=ar[0],    y=cy, string="\u25ba",           fg=color.menu_title, bg=row_bg)
            self._portrait_arrows.append((al, ar))
            cy += 1

        console.print(x=cx, y=cy + 1,
                      string="\u2190\u2192 change  \u2191\u2193 row",
                      fg=color.dark_gray, bg=color.parchment_bg)

    # ─── Bottom bar ───────────────────────────────────────────────────

    def _render_bottom_bar(self, console: Console) -> None:
        bar_y = _POP_Y + _POP_H - 3

        # Horizontal separator
        for col in range(_POP_X + 1, _POP_X + _POP_W - 1):
            console.print(x=col, y=bar_y - 1, string="─", fg=color.dark_gray, bg=color.parchment_bg)

        # Summary line
        prof_name = self._professions[self._prof_idx]["name"] if self._professions else "—"
        origin_name = self._origins[self._bg_idx]["name"] if self._origins else "—"
        summary  = f"{self._name} / {origin_name} / {prof_name}"
        console.print(x=_POP_X + 2, y=bar_y,
                      string=summary[:_POP_W - 18], fg=color.light_gray)

        # Confirm button
        btn   = " Confirm > "
        btn_x = _POP_X + _POP_W - len(btn) - 2
        console.print(x=btn_x, y=bar_y, string=btn,
                      fg=color.black, bg=color.welcome_text)
        self._confirm_rect = (btn_x, bar_y, len(btn), 1)

    # ────────────────────────────────────────────────────────────────────
    # Utility
    # ────────────────────────────────────────────────────────────────────

    def _print_wrapped(self, console: Console, text: str,
                       x: int, y: int, width: int, fg) -> int:
        """Word-wrap *text* into the console; returns the y after the last line."""
        max_y = _CONT_Y + _CONT_H
        words = text.split()
        line  = ""
        for w in words:
            test = (line + " " + w).strip()
            if len(test) <= width:
                line = test
            else:
                if y < max_y and line:
                    console.print(x=x, y=y, string=line, fg=fg)
                y += 1
                line = w
        if line and y < max_y:
            console.print(x=x, y=y, string=line, fg=fg)
            y += 1
        return y

    # ────────────────────────────────────────────────────────────────────
    # Apply choices & start the game
    # ────────────────────────────────────────────────────────────────────

    def _apply_and_confirm(self):
        from input_handlers import MainGameEventHandler

        p = self.engine.player

        # Name
        p.name = self._name.strip() or "Adventurer"

        # Appearance — write portrait knowledge and regenerate portrait
        import sprite_manager as _sm
        know: Dict[str, object] = {}
        for field, opts in _PORTRAIT_FIELDS:
            val = opts[self._portrait_idxs.get(field, 0) % len(opts)]
            know[field] = None if val == "none" else val
        if not hasattr(p, 'knowledge') or p.knowledge is None:
            p.knowledge = {}
        p.knowledge.update(know)
        _sm.compose_portrait(p)

        # Reset all traits to base before applying life-path modifiers.
        if hasattr(p, "level") and getattr(p.level, "traits", None):
            for trait in p.level.traits:
                p.level.traits[trait]["level"] = 1

        # Build one final setup object from origin + profession.
        setup = self._create_character_setup()
        p.knowledge["character_setup"] = setup

        # Apply origin aptitudes.
        for trait, bonus in setup.get("aptitudes", {}).items():
            if trait in p.level.traits:
                p.level.traits[trait]["level"] = max(
                    1,
                    min(5, p.level.traits[trait]["level"] + int(bonus)),
                )

        # Apply profession skills.
        for trait, bonus in setup.get("skills", {}).items():
            if trait in p.level.traits:
                p.level.traits[trait]["level"] = max(
                    1,
                    min(5, p.level.traits[trait]["level"] + int(bonus)),
                )

        # Profession starting kit (fixed item refs).
        _give_fixed_items(setup.get("starting_items", []), p)
        # Profession starting spells (persistent known spells, not consumables).
        _give_starting_spells(setup.get("starting_spells", []), p)
        # Origin perks are separate from profession and shape initial run state.
        _apply_origin_perks(setup.get("origin_perks", {}), p)

        prof = self._selected_profession()
        self._run_hook(prof.get("python_hook"), p, prof)

        # Origin flavor hook
        origin = self._selected_origin()
        self._run_hook(origin.get("python_hook"), p, origin)

        # Sync mana pool from finalized arcana level.
        # Keep the early-game curve gentle so life-path choices don't over-spike starts.
        # Then anchor runtime mana growth so post-chargen arcana levels use runtime scaling.
        if hasattr(p, "level") and getattr(p.level, "traits", None):
            arcana_level = int(p.level.traits.get("arcana", {}).get("level", 1) or 1)
            base_mana = max(int(getattr(p, "mana_max", 0) or 0), STARTING_MANA_BASE)
            p.level.base_mana_max = base_mana
            if hasattr(p, "fighter") and p.fighter:
                p.level.base_max_hp = max(1, int(getattr(p.fighter, "max_hp", 1) or 1))

            # Seed chargen mana from the intended baseline before the first resync.
            # Otherwise the resync anchors against the player's pre-chargen 0 mana pool.
            p.level.set_mana_scaling_anchor(
                current_mana_max=base_mana,
                arcana_level=1,
            )

            p.level.resync_derived_stats(
                hp_per_vigor_level=VIGOR_HP_PER_LEVEL,
                mana_per_arcana_level=STARTING_MANA_PER_ARCANA_LEVEL,
                heal_on_hp_increase=True,
                refill_mana_on_increase=True,
            )

            p.level.set_mana_scaling_anchor(
                current_mana_max=int(getattr(p, "mana_max", 0) or 0),
                arcana_level=arcana_level,
            )

        # Restore minimap state set by AskUserEventHandler.__init__
        self.engine.show_minimap = getattr(self.engine, "_pre_menu_minimap", 1)

        sounds.start_dungeon_music()
        return MainGameEventHandler(self.engine)

    @staticmethod
    def _run_hook(hook_name: Optional[str], player, data: dict) -> None:
        """Call an optional function from chargen_hooks.py if it exists."""
        if not hook_name:
            return
        try:
            import importlib
            chargen_hooks = importlib.import_module("chargen_hooks")
            fn = getattr(chargen_hooks, hook_name, None)
            if callable(fn):
                fn(player, data)
        except ImportError:
            pass
        except Exception as e:
            print(f"[chargen] hook {hook_name!r} error: {e}")


def _give_fixed_items(item_refs: list, player) -> None:
    """Give fixed profession starting items by ref."""
    import entity_factories as ef
    for ref in item_refs:
        item_obj = getattr(ef, ref, None)
        if item_obj is None:
            print(f"[chargen] unknown fixed item ref: {ref!r}")
            continue
        try:
            if callable(item_obj):
                item_copy = item_obj()
                item_copy.parent = player.inventory
                player.inventory.items.append(item_copy)
                continue

            item_name = str(getattr(item_obj, "name", "")).lower()
            item_tags = [str(tag).lower() for tag in getattr(item_obj, "tags", []) or []]
            if "scroll" in item_name or "scroll" in item_tags:
                spell_key = None
                for candidate in ("fireball", "lightning", "darkvision", "confusion"):
                    if candidate in item_name or candidate in item_tags:
                        spell_key = candidate
                        break
                item_copy = ef.get_scroll(spell_key) if spell_key is not None else copy.deepcopy(item_obj)
            else:
                item_copy = copy.deepcopy(item_obj)
            item_copy.parent = player.inventory
            player.inventory.items.append(item_copy)
        except Exception as e:
            print(f"[chargen] failed to give fixed item {ref!r}: {e}")


def _give_starting_spells(spell_names: list, player) -> None:
    """Grant persistent known spells by name to the player."""
    if not spell_names:
        return

    if not hasattr(player, "known_spells") or player.known_spells is None:
        player.known_spells = []

    spell_map = _build_spell_class_map()

    for spell_name in spell_names:
        key = str(spell_name).lower()
        spell_cls = spell_map.get(key)
        if spell_cls is None:
            print(f"[chargen] unknown starting spell: {spell_name!r}")
            continue

        already_known = False
        for known_spell in player.known_spells:
            known_name = str(getattr(known_spell, "name", "")).lower()
            if known_name == key or known_name.startswith(key + " "):
                already_known = True
                break

        if already_known:
            continue

        try:
            player.known_spells.append(spell_cls())
        except Exception as e:
            print(f"[chargen] failed to grant starting spell {spell_name!r}: {e}")


def _apply_origin_perks(origin_perks: dict, player) -> None:
    """Apply origin-only gameplay perks so origin and profession stay distinct."""
    perks = origin_perks or {}

    def _as_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    bonus_gold = _as_int(perks.get("starting_gold", 0))
    if bonus_gold and hasattr(player, "gold"):
        player.gold = int(getattr(player, "gold", 0) or 0) + bonus_gold

    bonus_hp = _as_int(perks.get("bonus_hp", 0))
    if bonus_hp and hasattr(player, "fighter") and player.fighter:
        player.fighter.max_hp = max(1, int(player.fighter.max_hp) + bonus_hp)
        player.fighter.hp = min(player.fighter.max_hp, int(player.fighter.hp) + bonus_hp)
        if hasattr(player, "body_parts") and player.body_parts is not None:
            try:
                player.body_parts.set_max_health(player.fighter.max_hp)
            except Exception:
                pass

    bonus_mana = _as_int(perks.get("bonus_mana", 0))
    if bonus_mana and hasattr(player, "mana_max"):
        player.mana_max = int(getattr(player, "mana_max", 0) or 0) + bonus_mana
        player.mana = min(int(getattr(player, "mana", 0) or 0) + bonus_mana, player.mana_max)

    bonus_hunger = _as_int(perks.get("bonus_hunger", 0))
    if bonus_hunger and hasattr(player, "hunger"):
        player.hunger = int(getattr(player, "hunger", 0) or 0) + bonus_hunger

    bonus_saturation = _as_int(perks.get("bonus_saturation", 0))
    if bonus_saturation and hasattr(player, "saturation"):
        player.saturation = int(getattr(player, "saturation", 0) or 0) + bonus_saturation
