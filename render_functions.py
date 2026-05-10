from __future__ import annotations

from typing import Tuple, TYPE_CHECKING

import tcod
import numpy as np

import color
import text_utils
import time
import sprite_manager

# Try to import animation helpers if they exist; fall back gracefully.
try:
    from animations import FireFlicker, FireSmoke, LightningAnimation, FireballAnimation
except Exception:
    FireFlicker = FireSmoke = LightningAnimation = FireballAnimation = None

if TYPE_CHECKING:
    from tcod.console import Console
    from engine import Engine
    from game_map import GameMap

# Body part abbreviations for combat display (regional tag-based)
BODY_PART_ABBREV = {
    None: "Rnd",            # Random targeting
    "cranium": "Hd",        # Head/Neck region
    "core": "Trs",          # Torso/Chest region  
    "upper_limbs": "Arm",   # Arms/Hands region
    "lower_limbs": "Leg",   # Legs/Feet region
}


SPEECH_BUBBLE_ANIMATIONS = {
    "speech_bubble": [0xE0F0, 0xE0F1, 0xE0F2],  # Standard speech bubble with subtle flicker
}


class SpeechBubble:
    def __init__(self, entity, duration: int = 120, type: str = "speech_bubble"):
        self.entity = entity
        self.duration = duration
        self._tick_count = 0
        self.type = type
    
    def tick(self):
        if self.entity.fighter.hp <= 0:
            return True
        """Called every game tick"""
        if self.duration > 0:
            self.duration -= 1
        self._tick_count += 1

        if self.type in SPEECH_BUBBLE_ANIMATIONS:
            frames = SPEECH_BUBBLE_ANIMATIONS[self.type]
            frame_index = (self._tick_count // 10) % len(frames)
            self.entity.char = sprite_manager.compose_sprite([ord(self.entity.char), frames[frame_index]])

        if self.duration <= 0:
            sprite_manager.refresh_actor_sprite(self.entity)  # Reset to base sprite
            return True
        return False
    
class SwimmingAnimation:
    
    CHARS = [0xE145, 0xE146, 0xE147, 0xE148, 0xE149]  # Water splash animation frames
    FRAME_DURATION = 5  # Ticks per frame

    def __init__(self, entity):
        self.entity = entity
        self._tick_count = 0
        

    def tick(self):
        """Called every game tick"""
        if self.entity.fighter.hp <= 0:
            return True
        if not getattr(self.entity, 'is_swimming', False):
            sprite_manager.refresh_actor_sprite(self.entity)  # Reset to base sprite
            return True
        
        sequence = [0, 1, 2, 3, 4, 3, 2, 1]

        idx = (self._tick_count // self.FRAME_DURATION) % len(sequence)
        frame_index = self.CHARS[sequence[idx]]

        # Refresh base render (keeps equipped layers) before applying water splash.
        sprite_manager.refresh_actor_sprite(self.entity)

        # Crop the first entry (the entity sprite) so only top half appears,
        # then draw the water animation behind the entity.
        self.entity.char = sprite_manager.compose_sprite(
            [ord(self.entity.char), frame_index],
            y_crop=16,
            top_first_layer=False,
        )

        self._tick_count += 1
        return False


class MenuRenderer:
    """Provides reusable rendering utilities for menus and UIs."""
    
    @staticmethod
    def draw_parchment_background(console: tcod.Console, x: int, y: int, 
                                   width: int, height: int, 
                                   bg_color: Tuple[int, int, int] = (45, 35, 25)) -> None:
        """Draw a parchment-style background for a menu window."""
        console.draw_rect(x=x, y=y, width=width, height=height, ch=ord(' '), bg=bg_color)
    
    @staticmethod
    def draw_ornate_border(console: tcod.Console, x: int, y: int, 
                          width: int, height: int, title: str = "",
                          border_fg: Tuple[int, int, int] = (139, 105, 60),
                          title_fg: Tuple[int, int, int] = (255, 215, 0),
                          bg: Tuple[int, int, int] = (45, 35, 25)) -> None:
        """Draw an ornate border with fantasy styling and optional title.
        
        Args:
            console: The tcod console to draw on
            x: X coordinate of the window
            y: Y coordinate of the window
            width: Width of the window
            height: Height of the window
            title: Optional title to display at the top
            border_fg: Color of the border
            title_fg: Color of the title
            bg: Background color
        """
        # Draw border
        console.draw_frame(x, y, width, height, fg=border_fg, bg=bg)
        
        # Draw ornate title if provided
        if title:
            title_decorated = f"✦ {title} ✦"
            title_start = x + (width - len(title_decorated)) // 2
            console.print(title_start, y, title_decorated, fg=title_fg, bg=bg)





def get_names_at_location(x: int, y: int, game_map: GameMap) -> str:
    x, y = int(x), int(y)
    if not game_map.in_bounds(x, y) or not game_map.visible[x, y]:
        return ""

    entity_names = []
    for entity in game_map.entities:
        if entity.x == x and entity.y == y:
            # Use unknown_name for actors if not known, but real name for items
            display_name = entity.name
            if hasattr(entity, 'unknown_name') and hasattr(entity, 'ai'):
                # This is an actor (has AI), check if known
                if hasattr(entity, 'is_known') and entity.is_known:
                    display_name = entity.name
                else:
                    display_name = entity.unknown_name
            else:
                display_name = entity.name
            entity_names.append(display_name)
    names = ", ".join(entity_names)
    names = names.capitalize()
    
    # Get tile name
    tile = (game_map.tiles['name'][x, y]).capitalize()
    
    # Check for liquid coating
    liquid_info = ""
    if hasattr(game_map, 'liquid_system'):
        coating = game_map.liquid_system.get_coating(x, y)
        if coating:
            liquid_name = coating.liquid_type.get_display_name()
            liquid_info = f" coated in {liquid_name}"
    
    # If no entities, show tile name instead
    if not names:
        names = tile + liquid_info
    else:
        names = f"{names} ({tile}{liquid_info})"
    
    return names

def render_debug_overlay(console: Console, fps: float, player_pos: Tuple[int, int], handler_name: str, entity_count: int, engine: Engine) -> None:          
    x, y = player_pos
    
    render_x = 0
    render_y = 0
    # Store frame times for the last N seconds
    if not hasattr(render_debug_overlay, "_frame_times"):
        render_debug_overlay._frame_times = []
        render_debug_overlay._last_update = time.time()

    now = time.time()
    render_debug_overlay._frame_times.append(fps)
    # Keep only the last 5 seconds worth of frame rates
    while render_debug_overlay._frame_times and now - render_debug_overlay._last_update > 5:
        render_debug_overlay._frame_times.pop(0)
        render_debug_overlay._last_update += 1

    if render_debug_overlay._frame_times:
        min_fps = min(render_debug_overlay._frame_times)
        max_fps = max(render_debug_overlay._frame_times)
        console.print(render_x, render_y + 5, f"Min FPS (5s): {min_fps:.1f}", fg=(255, 255, 255))
        console.print(render_x, render_y + 6, f"Max FPS (5s): {max_fps:.1f}", fg=(255, 255, 255))
    frame_time = 1.0 / fps if fps > 0 else 0
    frame_time_ms = frame_time * 1000

    console.print(render_x, render_y, f"Player: ({x}, {y})", fg=(255, 255, 255))
    console.print(render_x, render_y + 1, f"Handler: {handler_name}", fg=(255, 255, 255))
    console.print(render_x, render_y + 2, f"Entities: {entity_count}", fg=(255, 255, 255))
    console.print(render_x, render_y + 3, f"FPS: {fps:.1f}", fg=(255, 255, 255))
    console.print(render_x, render_y + 4, f"Frame Time: {frame_time_ms:.2f}ms", fg=(255, 255, 255))
    console.print(render_x, render_y + 5, f"Mouse Pos: ({engine.mouse_x}, {engine.mouse_y})", fg=(255, 255, 255))







def render_names_at_mouse(console: 'Console', mouse_x: int, mouse_y: int, game_map: GameMap) -> None:
    names = get_names_at_location(mouse_x, mouse_y, game_map)
    if not names:
        return

    # Draw a semi-transparent backdrop behind the tooltip to make it legible
    width = max(10, len(names) + 2)
    x = max(0, min(mouse_x, game_map.width - width))
    y = max(0, min(mouse_y, game_map.height - 1))

    # Draw background rectangle (single-line tooltip)
    for dx in range(width):
        console.print(x + dx, y, " ", bg=(40, 40, 40))

    console.print(x + 1, y, names, fg=(255, 255, 255))


# HP bar render with adjustable coordinates
def render_bar(
        console: 'Console', current_value: int, maximum_value: int, total_width: int
) -> None:
    # === ADJUSTABLE COORDINATES ===
    HP_BAR_X = 1
    HP_BAR_Y = 43
    # ==============================
    
    bar_width = int(float(current_value) / maximum_value * (total_width - 2))  # Account for border
    
    # Health bar with red/green gradient
    health_ratio = current_value / maximum_value
    if health_ratio > 0.6:
        bar_color = (0, 120, 0)  # Green
    elif health_ratio > 0.3:
        bar_color = (120, 120, 0)  # Yellow
    else:
        bar_color = (120, 0, 0)  # Red
        
    if bar_width > 0:
        console.draw_rect(
            x=HP_BAR_X, y=HP_BAR_Y, width=bar_width, height=1, ch=1, bg=bar_color
        )

    console.print(
        x=HP_BAR_X, y=HP_BAR_Y, string=f"HP: {current_value}/{maximum_value}", fg=color.fantasy_text
    )

# Mana bar render with adjustable coordinates
def render_mana_bar(
        console: 'Console', current_value: int, maximum_value: int, total_width: int
) -> None:
    MANA_BAR_X = 1
    MANA_BAR_Y = 45
    try:
        bar_width = int(float(current_value) / maximum_value * (total_width - 2))  # Account for border
    except ZeroDivisionError:
        bar_width = 0

    if bar_width > 0:
        console.draw_rect(
            x=MANA_BAR_X, y=MANA_BAR_Y, width=bar_width, height=1, ch=1, bg=(0, 0, 120)
        )

    console.print(
        x=MANA_BAR_X, y=MANA_BAR_Y, string=f"Mana: {current_value}/{maximum_value}", fg=color.fantasy_text
    )

# Lucidity bar render with adjustable coordinates
def render_lucidity_bar(
        console: 'Console', current_value: int, maximum_value: int, total_width: int
) -> None:
    # === ADJUSTABLE COORDINATES ===
    LUCIDITY_BAR_X = 1
    LUCIDITY_BAR_Y = 44
    # ==============================
    
    bar_width = int(float(current_value) / maximum_value * (total_width - 2))  # Account for border

    if bar_width > 0:
        console.draw_rect(
            x=LUCIDITY_BAR_X, y=LUCIDITY_BAR_Y, width=bar_width, height=1, ch=1, bg=(80, 80, 140)
        )

    console.print(
        x=LUCIDITY_BAR_X, y=LUCIDITY_BAR_Y, string=f"Lucidity: {current_value}/{maximum_value}", fg=color.fantasy_text
    )

def render_player_level(
        console: 'Console', current_value: int, maximum_value: int, total_value: int, total_width: int
) -> None:
    # === ADJUSTABLE COORDINATES ===
    LEVEL_BAR_X = 1
    LEVEL_BAR_Y = 45
    # ==============================
    
    bar_width = int(float(current_value) / maximum_value * (total_width - 2))  # Account for border
    
    if bar_width > 0:
        console.draw_rect(
            x=LEVEL_BAR_X, y=LEVEL_BAR_Y, width=bar_width, height=1, ch=1, bg=(120, 60, 200)
        )

    console.print(
        x=LEVEL_BAR_X, y=LEVEL_BAR_Y, string=f"Level: {current_value}/{maximum_value} ({total_value})", fg=color.fantasy_text
    )

def render_biome(
        console: 'Console', biome_name: str, map: GameMap = None,
) -> None:
    # === ADJUSTABLE COORDINATES ===
    BIOME_X = 1
    BIOME_Y = 48
    # ==============================
    
    console.print(x=BIOME_X, y=BIOME_Y, string=f"{biome_name}", fg=color.grey)


def render_dungeon_level(
        console: 'Console', dungeon_level: int, map: GameMap = None,
) -> None:
    # === ADJUSTABLE COORDINATES ===
    DUNGEON_LEVEL_X = 1
    DUNGEON_LEVEL_Y = 47
    # ==============================
    
    console.print(x=DUNGEON_LEVEL_X, y=DUNGEON_LEVEL_Y, string=f"Dungeon: {dungeon_level}", fg=color.bronze_text)

def render_gold(
        console: 'Console', gold_amount: int,
) -> None:
    # === ADJUSTABLE COORDINATES ===
    GOLD_X = 1
    GOLD_Y = 46
    # ==============================
    
    console.print(x=GOLD_X, y=GOLD_Y, string=f"Gold: {gold_amount}", fg=color.gold_accent)

def render_ui_buttons(
        console: 'Console', hovered_button: str = None) -> None:
    # === ADJUSTABLE COORDINATES ===
    INVENTORY_BUTTON_X = 36
    EQUIPMENT_BUTTON_X = 52
    BUTTON_Y = 40
    # ==============================
    inv_color = color.gold_accent if hovered_button == "inventory" else color.bronze_text
    equip_color = color.gold_accent if hovered_button == "equipment" else color.bronze_text
    console.print(x=INVENTORY_BUTTON_X, y=BUTTON_Y, string="Inventory [TAB]", fg=inv_color)
    console.print(x=EQUIPMENT_BUTTON_X, y=BUTTON_Y, string="Equipment [E]", fg=equip_color)


def _collect_coating_effects(player) -> list:
    """Scan all body parts and return one display-only Effect per unique coating type."""
    from components.effect import BloodyEffect, WetEffect, OilyEffect, SlimyEffect

    _COATING_EFFECT_MAP = {
        "blood": lambda: BloodyEffect(duration=None),
        "water": lambda: WetEffect(duration=None),
        "oil":   lambda: OilyEffect(duration=None),
        "slime": lambda: SlimyEffect(duration=None),
    }

    if player is None:
        return []
    seen = set()
    results = []
    try:
        body_parts = getattr(player, "body_parts", None)
        parts_map = getattr(body_parts, "body_parts", {}) if body_parts else {}
        for body_part in parts_map.values():
            coating = getattr(body_part, "coating", None)
            if coating is None:
                continue
            liquid_type = getattr(coating, "liquid_type", coating)
            try:
                name = liquid_type.get_display_name().lower()
            except Exception:
                name = str(getattr(liquid_type, "name", "")).lower()
            if name and name not in ("none", "") and name not in seen:
                seen.add(name)
                factory = _COATING_EFFECT_MAP.get(name)
                if factory:
                    results.append(factory())
    except Exception:
        pass
    return results


def _collect_effect_display_entries(player) -> list:
    effects = list(getattr(player, "effects", []) or [])

    # Keep only one effect per name for HUD display.
    unique_by_name = {}
    order = []
    for effect in effects:
        name = getattr(effect, "name", effect.__class__.__name__)
        if name not in unique_by_name:
            unique_by_name[name] = effect
            order.append(name)
            continue

        existing = unique_by_name[name]
        existing_duration = getattr(existing, "duration", None)
        new_duration = getattr(effect, "duration", None)

        # Prefer non-expiring effects; otherwise keep the one with longer duration.
        if existing_duration is None:
            continue
        if new_duration is None or (isinstance(new_duration, int) and new_duration > existing_duration):
            unique_by_name[name] = effect

    effects = [unique_by_name[name] for name in order]

    # Inject display-only effects for any body-part coatings not already represented.
    for coating_effect in _collect_coating_effects(player):
        effect_name = getattr(coating_effect, "name", "")
        if effect_name not in unique_by_name:
            effects.append(coating_effect)

    return effects


# Combat status panel with adjustable coordinates
def render_combat_stats(
        console: 'Console', dodge_direction: str = "North", attack_type: str = "Random", player=None,
) -> None:
    # === ADJUSTABLE COORDINATES ===
    PANEL_X = 0
    PANEL_Y = 39
    PANEL_WIDTH = console.width
    PANEL_HEIGHT = 4
    COMBAT_TEXT_X = 1
    EFFECTS_TEXT_X = 10
    WEAPON_TEXT_OFFSET_FROM_RIGHT = 2
    # ==============================
    
    # Draw black background around edges
    #console.draw_rect(x=PANEL_X, y=PANEL_Y, width=PANEL_WIDTH, height=PANEL_HEIGHT, ch=ord(' '), bg=(0, 0, 0))
    # Draw parchment background for panel interior
    #console.draw_rect(x=PANEL_X+1, y=PANEL_Y+1, width=PANEL_WIDTH-2, height=PANEL_HEIGHT-2, ch=ord(' '), bg=color.parchment_bg)
    # Draw horizontal divider line, but skip both vertical divider positions
    
    # Left part of horizontal line (before first divider at x=12)
    console.draw_rect(x=PANEL_X+1, y=PANEL_Y+3, width=8, height=1, ch=ord('─'), bg=color.parchment_dark, fg=color.bronze_border)
    # Middle part of horizontal line (between dividers at x=12 and x=20)  
    console.draw_rect(x=10, y=PANEL_Y+3, width=10, height=1, ch=ord('─'), bg=color.parchment_dark, fg=color.bronze_border)
    # Right part of horizontal line split into sections to preserve T-junctions at DIVIDER_X3=35 and DIVIDER_X4=65
    console.draw_rect(x=21, y=PANEL_Y+3, width=14, height=1, ch=ord('─'), bg=color.parchment_dark, fg=color.bronze_border)   # x=21..34
    console.draw_rect(x=36, y=PANEL_Y+3, width=29, height=1, ch=ord('─'), bg=color.parchment_dark, fg=color.bronze_border)   # x=36..64
    console.draw_rect(x=66, y=PANEL_Y+3, width=PANEL_WIDTH-67, height=1, ch=ord('─'), bg=color.parchment_dark, fg=color.bronze_border)  # x=66..
    # Combat stats on first content line
    dodge_text = f"DDG: {dodge_direction[0].upper() if dodge_direction else 'R'}"
    console.print(x=COMBAT_TEXT_X, y=PANEL_Y + 1, string=dodge_text, fg=color.bronze_text)
    
    # Get attack abbreviation from lookup table
    attack_abbrev = BODY_PART_ABBREV.get(attack_type, attack_type[:3].upper() if attack_type else "Rnd")
    console.print(x=COMBAT_TEXT_X, y=PANEL_Y + 2, string=f"ATK: {attack_abbrev}", fg=color.bronze_text)
    
    # Effects box: glyph-only display (no headers). Use both rows in this UI box.
    effect_row_top = PANEL_Y + 1
    effect_row_bottom = PANEL_Y + 2
    display_effects = _collect_effect_display_entries(player) if player else []
    if display_effects:
        max_per_row = 12
        for idx, effect in enumerate(display_effects[: max_per_row * 2]):
            try:
                display = effect.get_display() if hasattr(effect, "get_display") else None
                glyph = getattr(display, "glyph", "?") if display else "?"
                fg = getattr(display, "fg", color.fantasy_text) if display else color.fantasy_text
                bg = getattr(display, "bg", None) if display else None

                row = 0 if idx < max_per_row else 1
                col = idx if row == 0 else idx - max_per_row
                draw_x = EFFECTS_TEXT_X + (col * 2)
                draw_y = effect_row_top if row == 0 else effect_row_bottom

                if isinstance(glyph, int):
                    console.tiles_rgb[draw_x, draw_y]["ch"] = glyph
                    console.tiles_rgb[draw_x, draw_y]["fg"] = fg
                    if bg is not None:
                        console.tiles_rgb[draw_x, draw_y]["bg"] = bg
                else:
                    console.print(x=draw_x, y=draw_y, string=str(glyph), fg=fg, bg=bg)
            except Exception:
                continue

    # Show weapon and ammo info on the right side
    if player is None:
        return

    equipment = getattr(player, "equipment", None)
    inventory = getattr(player, "inventory", None)
    if not equipment:
        return

    # Show equipped weapon
    equipped_items = list(equipment.grasped_items.values())
    weapon_name = "None"
    
    for item in equipped_items:
        if item and hasattr(item, "equippable") and item.equippable:
            weapon_name = item.name
            break
    
    weapon_text = f"Weapon: {weapon_name[:15]}"  # Truncate long names
    weapon_x = max(1, console.width - len(weapon_text) - WEAPON_TEXT_OFFSET_FROM_RIGHT)
    console.print(x=weapon_x, y=PANEL_Y + 1, string=weapon_text, fg=color.bronze_text)

    # Show ammo only when a bow is currently equipped/readied.
    has_bow = False
    arrow_count = 0

    equipped_items = list(equipment.grasped_items.values()) + list(equipment.equipped_items.values())

    for item in equipped_items:
        if not item or not hasattr(item, "equippable") or not item.equippable:
            continue
        eq_type_name = item.equippable.equipment_type.name
        tags = {tag.lower() for tag in getattr(item, "tags", [])}
        if eq_type_name == "RANGED" or "bow" in tags:
            has_bow = True
        if eq_type_name == "PROJECTILE" or "arrow" in tags or "ammunition" in tags:
            arrow_count += 1

    if inventory:
        for item in inventory.items:
            if not item or not hasattr(item, "equippable") or not item.equippable:
                continue
            eq_type_name = item.equippable.equipment_type.name
            tags = {tag.lower() for tag in getattr(item, "tags", [])}
            if eq_type_name == "PROJECTILE" or "arrow" in tags or "ammunition" in tags:
                arrow_count += 1

    if has_bow:
        ammo_text = f"Arrows: {arrow_count}"
        ammo_x = max(1, console.width - len(ammo_text) - WEAPON_TEXT_OFFSET_FROM_RIGHT)
        console.print(x=ammo_x, y=PANEL_Y + 2, string=ammo_text, fg=color.bronze_text)







def render_status_hover_panel(console: 'Console', mouse_ui_x: int, mouse_ui_y: int, player=None) -> None:
    """Show effect details when hovering over individual effect glyphs in the HUD."""

    # --- Optimization: cache last hovered effect and mouse position ---
    if not hasattr(render_status_hover_panel, "_cache"):
        render_status_hover_panel._cache = {
            "last_mouse": None,
            "last_effect": None,
            "last_lines": None,
            "last_frame_color": None,
            "last_draw": None,
        }
    cache = render_status_hover_panel._cache

    if player is None:
        return

    panel_y = 39
    effects_x = 10
    hovered_effect = None
    display_effects = _collect_effect_display_entries(player)
    if display_effects and mouse_ui_y in {panel_y + 1, panel_y + 2}:
        max_per_row = 12
        if mouse_ui_y == panel_y + 1:
            row_start = 0
            row_end = min(max_per_row, len(display_effects))
        else:
            row_start = max_per_row
            row_end = min(max_per_row * 2, len(display_effects))

        icon_x = effects_x
        for idx in range(row_start, row_end):
            if mouse_ui_x == icon_x:
                hovered_effect = display_effects[idx]
                break
            icon_x += 2

    # Only recompute if mouse or effect changed
    mouse_key = (mouse_ui_x, mouse_ui_y)
    if (
        cache["last_mouse"] == mouse_key
        and cache["last_effect"] == hovered_effect
        and cache["last_draw"] is not None
    ):
        # Redraw from cache
        x, y, width, height, draw_lines, frame_color = cache["last_draw"]
    else:
        cache["last_mouse"] = mouse_key
        cache["last_effect"] = hovered_effect
        if hovered_effect is None:
            cache["last_draw"] = None
            return
        lines = []
        try:
            display = hovered_effect.get_display() if hasattr(hovered_effect, "get_display") else None
            duration = getattr(hovered_effect, "duration", None)
            turns_text = "indefinite" if duration is None else f"{duration}t"
            title = ((getattr(display, "label", None) if display else None) or getattr(hovered_effect, "name", "Unknown")) + (f" ({turns_text})")
            lines.append(title)
            desc = getattr(hovered_effect, "description", "") or "No description."
            lines.append(f"{desc}")
            effect_type = getattr(hovered_effect, "type", None)
            if effect_type == "debuff":
                frame_color = color.red
            elif effect_type == "buff":
                frame_color = color.green
            elif effect_type == "status":
                frame_color = color.blue
            else:
                frame_color = color.bronze_border
        except Exception:
            lines.append("Unknown")
            frame_color = color.bronze_border

        if not lines:
            cache["last_draw"] = None
            return

        max_width = max(24, min(console.width - 4, max(len(line) for line in lines) + 2))
        max_body_lines = min(len(lines), 8)
        draw_lines = [line[: max_width - 2] for line in lines[:max_body_lines]]
        width = max_width
        height = len(draw_lines) + 2
        x = max(1, min(mouse_ui_x + 1, console.width - width - 1))
        hud_top = 39
        hud_bottom = console.height - 1
        max_height_in_hud = max(3, hud_bottom - hud_top + 1)
        if height > max_height_in_hud:
            height = max_height_in_hud
            draw_lines = draw_lines[: max(1, height - 2)]
        y = max(hud_top, min(mouse_ui_y - height, hud_bottom - height + 1))
        cache["last_draw"] = (x, y, width, height, draw_lines, frame_color)

    # Draw the cached or computed tooltip
    if cache["last_draw"] is None:
        return
    x, y, width, height, draw_lines, frame_color = cache["last_draw"]
    console.draw_rect(x=x, y=y, width=width, height=height, ch=ord(" "), bg=color.parchment_bg)
    console.draw_frame(x=x, y=y, width=width, height=height, fg=frame_color, bg=color.parchment_bg)
    for idx, line in enumerate(draw_lines, start=1):
        fg = color.fantasy_text if idx == 1 else color.bronze_text
        console.print(x=x + 1, y=y + idx, string=line, fg=fg, bg=color.parchment_bg)



def render_context_hints(console: tcod.Console, hints: list) -> None:
    """Render context-sensitive key hints one row above the bottom HUD."""
    if not hints:
        return
    HINTS_Y = 38  # One row above the bottom UI border (UI_TOP = 39)
    x = 1
    MAX_X = console.width - 2

    for i, (key, action) in enumerate(hints):
        if x >= MAX_X:
            break
        # Separator between entries
        if i > 0:
            sep = " \u25c6 "  # ◆
            if x + len(sep) > MAX_X:
                break
            console.print(x=x, y=HINTS_Y, string=sep, fg=color.bronze_border, bg=color.parchment_dark)
            x += len(sep)
        # Opening bracket
        if x >= MAX_X:
            break
        console.print(x=x, y=HINTS_Y, string="[", fg=color.bronze_border, bg=color.parchment_dark)
        x += 1
        # Key label
        if x + len(key) > MAX_X:
            break
        console.print(x=x, y=HINTS_Y, string=key, fg=color.gold_accent, bg=color.parchment_dark)
        x += len(key)
        # Closing bracket
        if x >= MAX_X:
            break
        console.print(x=x, y=HINTS_Y, string="]", fg=color.bronze_border, bg=color.parchment_dark)
        x += 1
        # Action label
        action_str = " " + action
        available = MAX_X - x
        if available <= 0:
            break
        if len(action_str) > available:
            action_str = action_str[:available]
        console.print(x=x, y=HINTS_Y, string=action_str, fg=color.fantasy_text, bg=color.parchment_dark)
        x += len(action_str)


# ── Minimap / Hints panel constants ────────────────────────────────────────────
_MM_RIGHT_X = 57  # default right-side col
_MM_LEFT_X  = 0   # fallback left-side col
_MM_X = _MM_RIGHT_X  # kept for backward compat
_MM_Y = 0    # top edge
_MM_W = 23   # panel width  (interior: 21 cols)
_MM_H = 15   # panel height (interior: 13 rows)


def get_minimap_origin_x(engine) -> int:
    """Return the left-edge column for the minimap box.

    Normally the box sits in the top-RIGHT corner (col 57).  When the player
    is near the top-right edge of the map the camera clamps and the player
    character appears in that region of the game view, obscured by the box.
    In that case we flip to the top-LEFT corner (col 0).
    """
    if engine is None:
        return _MM_RIGHT_X
    gm = getattr(engine, 'game_map', None)
    player = getattr(engine, 'player', None)
    if gm is None or player is None:
        return _MM_RIGHT_X
    # Game console is 40×20; player screen col = player.x - origin_x
    view_w, view_h = 40, 20
    origin_x, origin_y = engine.get_camera_origin(view_w, view_h)
    gc_x = player.x - origin_x
    gc_y = player.y - origin_y
    # Minimap right box covers roughly gc cols 28-39, gc rows 0-7
    if gc_x >= 27 and gc_y <= 8:
        return _MM_LEFT_X
    return _MM_RIGHT_X


def _render_hints_content(
    console: tcod.Console,
    engine: 'Engine',
    x: int, y: int, w: int, h: int,
) -> None:
    """Fill the interior of the hints box with the current context hints."""
    hints = getattr(engine, 'context_hints', [])
    BG = color.parchment_dark
    for i, (key, action) in enumerate(hints):
        if i >= h:
            break
        bracket_str = f"[{key}]"
        console.print(x, y + i, bracket_str, fg=color.gold_accent, bg=BG)
        kx = x + len(bracket_str) + 1
        available = w - len(bracket_str) - 1
        if available > 0:
            console.print(kx, y + i, action[:available], fg=color.fantasy_text, bg=BG)


# Colour palette for the GPU minimap
# Visible (lit) tiles are intentionally dim so CRT bloom doesn't wash out markers.
_MM_COL_WALL_VIS     = ( 88,  82,  75, 255)  # medium stone
_MM_COL_WALL_EXP     = ( 55,  50,  46, 255)  # dim stone
_MM_COL_FLOOR_VIS    = ( 90,  72,  50, 255)  # warm brown (dim to avoid bloom)
_MM_COL_FLOOR_EXP    = ( 50,  40,  28, 255)  # unlit floor
_MM_COL_WATER_VIS    = ( 55, 140, 185, 255)
_MM_COL_WATER_EXP    = ( 22,  58,  88, 255)
_MM_COL_GRASS_VIS    = ( 55, 145,  55, 255)
_MM_COL_GRASS_EXP    = ( 28,  72,  28, 255)
_MM_COL_DOOR_VIS     = (160, 110,  45, 255)  # warm oak
_MM_COL_DOOR_EXP     = ( 90,  65,  32, 255)
_MM_COL_STAIR_DOWN   = (140,  80, 240, 255)  # purple — bright marker
_MM_COL_STAIR_UP     = (200, 140, 255, 255)  # light purple
_MM_COL_ENEMY        = (240,  40,  40, 255)  # vivid red
_MM_COL_CHEST        = (255, 190,  40, 255)  # chest brown
_MM_COL_ITEM         = (225, 190,  40, 255)  # gold
_MM_COL_PLAYER       = (  0, 240, 100, 255)  # bright green — most important


def render_gpu_minimap_body(
    renderer,
    engine: 'Engine',
    base_tile_w: float,
    base_tile_h: float,
) -> None:
    """Draw a GPU pixel-art minimap into the current render target.

    One pixel per map tile, scaled up to fill the box interior.
    The ASCII border/title are blitted from hud_tex first; this call
    then overlays pure pixel content inside the border.
    """
    if getattr(engine, 'show_minimap', 0) != 0:
        return
    gm = getattr(engine, 'game_map', None)
    if gm is None:
        return

    from entity import Actor

    # Dynamic box position (flips to left when player is near top-right edge)
    box_x = get_minimap_origin_x(engine)

    # Interior tile coords (1-cell inset from box border)
    ix = box_x + 1
    iy = _MM_Y + 1
    iw = _MM_W - 2
    ih = _MM_H - 2

    # Interior pixel bounds on screen
    px0 = int(ix * base_tile_w)
    py0 = int(iy * base_tile_h)
    pw  = int(iw * base_tile_w)
    ph  = int(ih * base_tile_h)
    if pw <= 0 or ph <= 0:
        return

    map_w, map_h = gm.width, gm.height

    # One RGBA pixel per map tile — (map_h, map_w, 4) row-major
    pixels = np.zeros((map_h, map_w, 4), dtype=np.uint8)

    exp      = gm.explored.T    # (H, W)
    vis      = gm.visible.T     # (H, W)
    walkable = gm.tiles['walkable'].T

    # --- Terrain (vectorised) ----------------------------------------
    pixels[exp & ~vis & ~walkable] = _MM_COL_WALL_EXP
    pixels[vis & ~walkable]        = _MM_COL_WALL_VIS
    pixels[exp & ~vis & walkable]  = _MM_COL_FLOOR_EXP
    pixels[vis & walkable]         = _MM_COL_FLOOR_VIS

    # --- Special terrain via name field (water / grass / door) -------
    try:
        names = gm.tiles['name']  # (W, H)
        # Build boolean masks per special type — vectorised string search
        def _name_mask(keyword):
            """Return (H, W) bool mask where tile name contains keyword."""
            vfunc = np.vectorize(lambda n: keyword in str(n).lower())
            return vfunc(names).T  # transpose to (H, W)

        water_m  = _name_mask('water')
        grass_m  = _name_mask('grass') | _name_mask('foliage')
        door_m   = _name_mask('door')

        pixels[exp & water_m & ~vis] = _MM_COL_WATER_EXP
        pixels[vis & water_m]        = _MM_COL_WATER_VIS
        pixels[exp & grass_m & ~vis] = _MM_COL_GRASS_EXP
        pixels[vis & grass_m]        = _MM_COL_GRASS_VIS
        pixels[exp & door_m  & ~vis] = _MM_COL_DOOR_EXP
        pixels[vis & door_m]         = _MM_COL_DOOR_VIS
    except (ValueError, TypeError):
        pass

    # --- Stairs -------------------------------------------------------
    down_loc = getattr(gm, 'downstairs_location', None)
    up_loc   = getattr(gm, 'upstairs_location',   None)
    if down_loc is not None:
        dx, dy = int(down_loc[0]), int(down_loc[1])
        if 0 <= dx < map_w and 0 <= dy < map_h and gm.explored[dx, dy]:
            pixels[dy, dx] = _MM_COL_STAIR_DOWN
    if up_loc is not None:
        ux, uy = int(up_loc[0]), int(up_loc[1])
        if 0 <= ux < map_w and 0 <= uy < map_h and gm.explored[ux, uy]:
            pixels[uy, ux] = _MM_COL_STAIR_UP

    # --- Entities -----------------------------------------------------
    for ent in gm.entities:
        ex, ey = ent.x, ent.y
        if not (0 <= ex < map_w and 0 <= ey < map_h):
            continue
        if ent is engine.player:
            continue
        if isinstance(ent, Actor):
            if ent.fighter and ent.fighter.hp > 0 and gm.visible[ex, ey]:
                pixels[ey, ex] = _MM_COL_ENEMY
        else:
            if gm.visible[ex, ey] or gm.explored[ex, ey]:
                # Distinguish chests (container component) from loose items
                from components.container import Container
                if hasattr(ent, 'container') and ent.container is not None:
                    pixels[ey, ex] = _MM_COL_CHEST
                else:
                    pixels[ey, ex] = _MM_COL_ITEM

    # --- Player (always visible, bright green) -----------------------
    ppx, ppy = engine.player.x, engine.player.y
    if 0 <= ppx < map_w and 0 <= ppy < map_h:
        pixels[ppy, ppx] = _MM_COL_PLAYER

    # --- Upload and blit scaled to interior ---------------------------
    tex = renderer.upload_texture(pixels)
    tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
    renderer.copy(tex, dest=(px0, py0, pw, ph))


def render_gpu_loading_bar(
    renderer,
    progress: float,
    window_w: int,
    window_h: int,
    console_renderer=None,
) -> None:
    """Draw a DOA OS BIOS-style world-gen loading screen matching the initial boot screen."""
    progress = max(0.0, min(1.0, progress))
    pct = int(progress * 100)

    W      = (200, 200, 200)
    DIM    = (100, 100, 100)
    BG     = (0,   0,   0  )
    BAR_BG = (0,   170, 170)
    BAR_FG = (0,   0,   0  )
    SEP    = (160, 160, 160)

    if console_renderer is not None:
        COLS = 80
        ROWS = 50
        con = tcod.console.Console(COLS, ROWS, order="F")

        # Fill background black
        con.draw_rect(0, 0, COLS, ROWS, ch=ord(' '), fg=W, bg=BG)

        # ── Header bar (row 0) ──────────────────────────────────────────────
        con.draw_rect(0, 0, COLS, 1, ord(' '), fg=BAR_FG, bg=BAR_BG)
        con.print(0, 0, " DOA BIOS v18.23.00", fg=BAR_FG, bg=BAR_BG)
        cr = "(C) 1998 Loxen Inc. "
        con.print(COLS - len(cr), 0, cr, fg=BAR_FG, bg=BAR_BG)

        # ── Separator ────────────────────────────────────────────────────────
        con.print(0, 1, chr(0x2550) * COLS, fg=SEP, bg=BG)

        # ── System info block ────────────────────────────────────────────────
        con.print(2, 3, "Dungeons of Aerrok: The Divine Stone", fg=W, bg=BG)
        con.print(2, 4, "BIOS DATE 11/19/98 12:40:36  |  VER: 18.23.00", fg=DIM, bg=BG)
        con.print(2, 5, "CPU: Intel(R) 330 @ 40 MHz  |  SPEED: 40MHz", fg=DIM, bg=BG)

        # ── Separator ────────────────────────────────────────────────────────
        con.print(0, 7, chr(0x2550) * COLS, fg=SEP, bg=BG)

        # ── Floppy read heading ───────────────────────────────────────────────
        _SPINNERS = ["|", "/", "-", "\\"]
        _spin = _SPINNERS[int(time.monotonic() * 6) % 4]
        con.print(2, 9, f"{_spin} Reading A:\\DUNGEON.DAT", fg=W, bg=BG)

        # ── File status list ──────────────────────────────────────────────────
        statuses = [
            (0.05, "A:\\WORLD\\NOISE.DAT"),
            (0.25, "A:\\WORLD\\TERRAIN.DAT"),
            (0.55, "A:\\WORLD\\ENTITIES.DAT"),
            (0.85, "A:\\WORLD\\FINALIZE.DAT"),
        ]
        for i, (threshold, name) in enumerate(statuses):
            done = progress >= threshold
            status_str = "OK" if done else "..."
            fg_col = W if done else DIM
            con.print(4, 11 + i, f"{name:<28} {status_str}", fg=fg_col, bg=BG)

        # ── Progress bar ──────────────────────────────────────────────────────
        BAR_W = 40
        filled_n = int(BAR_W * progress)
        bar = "[" + (chr(0x2588) * filled_n) + ("." * (BAR_W - filled_n)) + f"] {pct:3d}%"
        con.print(4, 17, bar, fg=W, bg=BG)

        # ── Done / cursor ─────────────────────────────────────────────────────
        if progress >= 1.0:
            con.print(4, 19, "Disk read complete. Switching video mode...", fg=W, bg=BG)
        else:
            blink = int(time.monotonic() * 2) % 2
            if blink:
                con.print(4, 19, chr(0x2588), fg=W, bg=BG)

        # ── Footer bar ───────────────────────────────────────────────────────
        con.draw_rect(0, ROWS - 1, COLS, 1, ord(' '), fg=BAR_FG, bg=BAR_BG)
        con.print(0, ROWS - 1, "  Reading from A:\\ ...", fg=BAR_FG, bg=BAR_BG)

        tex = console_renderer.render(con)
        tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
        renderer.copy(tex, dest=(0, 0, window_w, window_h))
    else:
        # Fallback: plain fill_rect bar (no console renderer available)
        bar_w = int(window_w * 0.40)
        bar_h = max(6, int(window_h * 0.018))
        bx = (window_w - bar_w) // 2
        by = (window_h - bar_h) // 2
        filled = int(bar_w * progress)
        renderer.draw_color = (20, 20, 20, 255)
        renderer.fill_rect((bx, by, bar_w, bar_h))
        if filled > 0:
            renderer.draw_color = (200, 200, 200, 255)
            renderer.fill_rect((bx, by, filled, bar_h))
        renderer.draw_color = (255, 255, 255, 255)
        renderer.fill_rect((bx, by, bar_w, 1))
        renderer.fill_rect((bx, by + bar_h - 1, bar_w, 1))
        renderer.fill_rect((bx, by, 1, bar_h))
        renderer.fill_rect((bx + bar_w - 1, by, 1, bar_h))


def render_gpu_reset_bar(
    renderer,
    handler,
    window_w: int,
    window_h: int,
    console_renderer=None,
    hud_dest_h: float = 0,
) -> None:
    """Draw the hold-R reset progress bar directly via the GPU renderer."""
    from input_handlers import MainGameEventHandler
    if not isinstance(handler, MainGameEventHandler):
        return
    press_time = getattr(handler, '_r_press_time', None)
    if press_time is None:
        return
    hold_dur = getattr(handler, '_RESET_HOLD_DURATION', 1.5)
    elapsed = time.monotonic() - press_time
    progress = min(1.0, elapsed / hold_dur)

    # Bar dimensions in pixels
    bar_w = int(window_w * 0.35)
    bar_h = max(6, int(window_h * 0.018))
    bx = (window_w - bar_w) // 2
    # Anchor just above the HUD strip, with a small gap
    hud_top = window_h - int(hud_dest_h)
    gap = max(4, int(window_h * 0.008))
    by = hud_top - bar_h - gap

    filled = int(bar_w * progress)

    # Background strip (dark red)
    bg = np.full((bar_h, bar_w, 4), (60, 10, 10, 200), dtype=np.uint8)
    # Filled portion (bright red)
    if filled > 0:
        bg[:, :filled] = (220, 50, 50, 220)
    # 1-px white border
    bg[0, :] = (200, 200, 200, 180)
    bg[-1, :] = (200, 200, 200, 180)
    bg[:, 0] = (200, 200, 200, 180)
    bg[:, -1] = (200, 200, 200, 180)

    tex = renderer.upload_texture(bg)
    tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
    renderer.copy(tex, dest=(bx, by, bar_w, bar_h))

    # Text label above the bar using a small console + SDLConsoleRender
    if console_renderer is not None:
        label = "SURRENDER THIS WORLD?"
        lbl_cols = len(label) + 2
        lbl_console = tcod.console.Console(lbl_cols, 1, order="F")
        lbl_console.print(1, 0, label, fg=(255, 100, 100), bg=(0, 0, 0))
        lbl_tex = console_renderer.render(lbl_console)
        lbl_tex.blend_mode = tcod.sdl.render.BlendMode.BLEND
        # Scale to 1 tile tall, centred on the bar
        tile_h = window_h // 50  # approximate tile pixel height
        lbl_dest_h = max(10, tile_h)
        lbl_dest_w = lbl_dest_h * lbl_cols  # square tiles
        lbl_dest_x = (window_w - lbl_dest_w) // 2
        lbl_dest_y = by - lbl_dest_h - 2
        renderer.copy(lbl_tex, dest=(lbl_dest_x, lbl_dest_y, lbl_dest_w, lbl_dest_h))


def render_minimap_box(console: tcod.Console, engine: 'Engine') -> None:
    """Render the minimap / hints toggle panel (auto-flips left/right)."""
    # Never render minimap on the overworld
    if getattr(getattr(engine, 'game_map', None), 'type', '') == 'overworld':
        return
    BOX_X = get_minimap_origin_x(engine)
    BOX_Y = _MM_Y
    BOX_W, BOX_H = _MM_W, _MM_H
    IX, IY = BOX_X + 1, BOX_Y + 1  # interior origin
    IW, IH = BOX_W - 2, BOX_H - 2  # interior size

    mode = getattr(engine, 'show_minimap', 0)  # 0=map, 1=keys, 2=minimized, 3=hidden
    if mode == 3:
        return  # Hidden — draw nothing at all, no background or border
    elif mode == 2:
        # Minimized — draw only a single-row tab strip at y=0.
        # Deliberately skip draw_rect/draw_frame so no full-box content
        # exists in the console (prevents popup bbox detector from picking it up).
        _row = BOX_Y
        console.draw_rect(x=BOX_X, y=_row, width=BOX_W, height=1,
                          ch=ord(' '), bg=color.parchment_dark)
        console.print(BOX_X, _row, '\u2570', fg=color.bronze_border, bg=color.parchment_dark)
        console.print(BOX_X + BOX_W - 1, _row, '\u256f', fg=color.bronze_border, bg=color.parchment_dark)
        for _bx in range(BOX_X + 1, BOX_X + BOX_W - 1):
            console.print(_bx, _row, '\u2500', fg=color.bronze_border, bg=color.parchment_dark)
        toggle = "[M]"
        console.print(BOX_X + BOX_W - len(toggle) - 1, _row,
                      toggle, fg=color.bronze_border, bg=color.parchment_dark)
        return

    # Background fill
    console.draw_rect(x=BOX_X, y=BOX_Y, width=BOX_W, height=BOX_H,
                      ch=ord(' '), bg=color.parchment_dark)

    # Border (corners + edges)
    console.draw_frame(x=BOX_X, y=BOX_Y, width=BOX_W, height=BOX_H,
                       fg=color.bronze_border, bg=color.parchment_dark, clear=False)

    if mode == 0:
        title = " Map "
        title_x = BOX_X + (BOX_W - len(title)) // 2
        console.print(title_x, BOX_Y, title, fg=color.gold_accent, bg=color.parchment_dark)
        # Toggle hint in bottom border
        toggle = "[M]"
        console.print(BOX_X + BOX_W - len(toggle) - 1, BOX_Y + BOX_H - 1,
                      toggle, fg=color.bronze_border, bg=color.parchment_dark)
        # Interior is filled by render_gpu_minimap_body — fill with black here
        # so the parchment doesn't bleed through before the GPU pass runs.
        console.draw_rect(x=IX, y=IY, width=IW, height=IH, ch=ord(' '), bg=(0, 0, 0))
    else:  # mode == 1 (keys)
        title = " Keys "
        title_x = BOX_X + (BOX_W - len(title)) // 2
        console.print(title_x, BOX_Y, title, fg=color.gold_accent, bg=color.parchment_dark)
        toggle = "[M]"
        console.print(BOX_X + BOX_W - len(toggle) - 1, BOX_Y + BOX_H - 1,
                      toggle, fg=color.bronze_border, bg=color.parchment_dark)
        _render_hints_content(console, engine, IX, IY, IW, IH)


def render_bottom_ui_border(console: tcod.Console):
    """
    Draw a simple border around the entire bottom UI area with a vertical divider.
    """
    # === ADJUSTABLE COORDINATES ===
    UI_TOP = 39
    UI_BOTTOM = console.height - 1
    UI_LEFT = 0
    UI_RIGHT = console.width - 1
    DIVIDER_X = 20  # Vertical divider between stats and message log
    DIVIDER_X2 = 9
    DIVIDER_X3 = 35
    DIVIDER_X4 = 65
    # ==============================
    
    # Fill the entire HUD block, including the border cells, with parchment.
    console.draw_rect(
        x=UI_LEFT,
        y=UI_TOP,
        width=UI_RIGHT - UI_LEFT + 1,
        height=UI_BOTTOM - UI_TOP + 1,
        ch=ord(' '),
        bg=color.parchment_dark,
    )
    
    # Draw horizontal borders
    for x in range(UI_LEFT, UI_RIGHT + 1):
        console.print(x, UI_TOP, "─", fg=color.bronze_border, bg=color.parchment_dark)  # Top border
        console.print(x, UI_BOTTOM, "─", fg=color.bronze_border, bg=color.parchment_dark)  # Bottom border

    
    
    # Draw vertical borders
    for y in range(UI_TOP + 1, UI_BOTTOM):
        console.print(UI_LEFT, y, "│", fg=color.bronze_border, bg=color.parchment_dark)  # Left border
        console.print(UI_RIGHT, y, "│", fg=color.bronze_border, bg=color.parchment_dark)  # Right border
        if y >= UI_TOP + 4:  # Only draw center divider from the horizontal line down
            console.print(DIVIDER_X, y, "│", fg=color.bronze_border, bg=color.parchment_dark)  # Center divider
        if y <= UI_TOP + 3:  # Draw secondary divider on the left side for the top stats area
            console.print(DIVIDER_X2, y, "│", fg=color.bronze_border, bg=color.parchment_dark)  # Divider between message log and player info
        if y <= UI_TOP + 3:  # Draw vertical line for menu separation in the top section
            console.print(DIVIDER_X3, y, "│", fg=color.bronze_border, bg=color.parchment_dark)  # Divider between message log and player info
        if y <= UI_TOP + 3:  # Draw vertical line for menu separation in the top section
            console.print(DIVIDER_X4, y, "│", fg=color.bronze_border, bg=color.parchment_dark)  # Divider between message log and player info
    
    # Draw corners
    console.print(UI_LEFT, UI_TOP, "┌", fg=color.bronze_border, bg=color.parchment_dark)  # Top-left
    console.print(UI_RIGHT, UI_TOP, "┐", fg=color.bronze_border, bg=color.parchment_dark)  # Top-right  
    console.print(UI_LEFT, UI_BOTTOM, "└", fg=color.bronze_border, bg=color.parchment_dark)  # Bottom-left
    console.print(UI_RIGHT, UI_BOTTOM, "┘", fg=color.bronze_border, bg=color.parchment_dark)  # Bottom-right
    
    # Draw T-junctions where divider meets top/bottom borders
    console.print(DIVIDER_X, UI_TOP + 3, "┬", fg=color.bronze_border, bg=color.parchment_dark)  # Top T-junction at horizontal divider
    console.print(DIVIDER_X, UI_BOTTOM, "┴", fg=color.bronze_border, bg=color.parchment_dark)  # Bottom T-junction
    console.print(DIVIDER_X2, UI_TOP, "┬", fg=color.bronze_border, bg=color.parchment_dark)  # Top T-junction for second divider  
    console.print(DIVIDER_X2, UI_TOP + 3, "┴", fg=color.bronze_border, bg=color.parchment_dark)  # Bottom T-junction for second divider
    console.print(DIVIDER_X3, UI_TOP, "┬", fg=color.bronze_border, bg=color.parchment_dark)  # Top T-junction for third divider
    console.print(DIVIDER_X3, UI_TOP + 3, "┴", fg=color.bronze_border, bg=color.parchment_dark)  # Bottom T-junction for third divider
    console.print(DIVIDER_X4, UI_TOP, "┬", fg=color.bronze_border, bg=color.parchment_dark)  # Top T-junction for fourth divider
    console.print(DIVIDER_X4, UI_TOP + 3, "┴", fg=color.bronze_border, bg=color.parchment_dark)  # Bottom T-junction for fourth divider
    
    # Add left and right T-junctions on the horizontal divider line
    console.print(UI_LEFT, UI_TOP + 3, "├", fg=color.bronze_border, bg=color.parchment_dark)  # Left T-junction
    console.print(UI_RIGHT, UI_TOP + 3, "┤", fg=color.bronze_border, bg=color.parchment_dark)  # Right T-junction



def render_rulers(console: tcod.Console, y: int = 44, horiz_step: int = 5, vert_step: int = 2) -> None:
    """Draw horizontal numbers above `y` and vertical numbers snapped at x=1 (safe from cutoff)."""
    # --- Horizontal numbers above separator line ---
    for x in range(0, console.width, horiz_step):
        num_str = str(x)
        for i, char in enumerate(num_str):
            if x + i < console.width:
                console.print(x=x + i, y=y - 1, string=char, fg=(255, 255, 255), bg=(0, 0, 0))

    # --- Vertical numbers at x=1 ---
    for yy in range(0, console.height, vert_step):
        num_str = str(yy)
        for i, char in enumerate(reversed(num_str)):  # right-align digits
            draw_x = 1 - i  # now anchored at x=1
            if draw_x >= 0:
                console.print(x=draw_x, y=yy, string=char, fg=(255, 255, 255), bg=(0, 0, 0))


def render_names_at_mouse_location(
        console: 'Console', x: int, y: int, engine: 'Engine'
) -> None:
    mouse_x, mouse_y = engine.mouse_location

    names_at_mouse_location = get_names_at_location(
        x=mouse_x, y=mouse_y, game_map=engine.game_map
    )

    #console.print(x=x, y=y, string=names_at_mouse_location)


def render_equipment(
        console: 'Console', x: int, y: int, engine: 'Engine'
) -> None:
    armor_name = engine.player.equipment.equipped_items.get('ARMOR').name if engine.player.equipment.equipped_items.get('ARMOR') else "None"
    # Get grasped items (weapons, shields, etc.)
    grasped_names = []
    for item in engine.player.equipment.grasped_items.values():
        grasped_names.append(item.name)
    held_items = ", ".join(grasped_names) if grasped_names else "None"
    
    backpack_name = engine.player.equipment.equipped_items.get('BACKPACK').name if engine.player.equipment.equipped_items.get('BACKPACK') else "None"
    console.print(x=x, y=y, string="Equipment:")
    console.print(x=x, y=y+1, string=f"Body: {armor_name}")
    console.print(x=x, y=y+2, string=f"Back: {backpack_name}")
    console.print(x=x, y=y+3, string=f"Hands: {held_items}")
    
    
def render_animations(console: tcod.Console, engine: 'Engine') -> None:
    for anim in list(engine.animations):
        # Prefer calling `tick` then `render` style animations if available.
        if hasattr(anim, "tick"):
            try:
                anim.tick(console, engine.game_map)
            except Exception:
                pass
        if hasattr(anim, "render"):
            try:
                anim.render(console)
            except Exception:
                pass
        # Remove expired animations if they expose `frames` or `expired`.
        expired = False
        if hasattr(anim, "frames"):
            expired = getattr(anim, "frames") <= 0
        if hasattr(anim, "expired"):
            try:
                expired = expired or anim.expired()
            except Exception:
                pass
        if expired:
            try:
                engine.animations.remove(anim)
            except ValueError:
                pass
