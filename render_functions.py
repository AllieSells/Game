from __future__ import annotations

from typing import Tuple, TYPE_CHECKING

import tcod

import color
import text_utils
import time

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


def _player_has_bloody_coating(player) -> bool:
    if player is None:
        return False
    try:
        body_parts = getattr(player, "body_parts", None)
        parts_map = getattr(body_parts, "body_parts", {}) if body_parts else {}
        for body_part in parts_map.values():
            coating = getattr(body_part, "coating", None)
            if coating is None:
                continue

            # Support either LiquidType-like values or LiquidCoating-like objects.
            liquid_type = getattr(coating, "liquid_type", coating)
            name = ""
            try:
                name = liquid_type.get_display_name().lower()
            except Exception:
                name = str(getattr(liquid_type, "name", "")).lower()

            if name == "blood":
                return True
    except Exception:
        return False
    return False


def _collect_effect_display_entries(player) -> list:
    from components.effect import BloodyEffect

    effects = list(getattr(player, "effects", []) or [])

    # Display-only grouping: represent blood coating as a real effect object.
    has_bloody_effect = any(getattr(effect, "name", "") == "Bloody" for effect in effects)
    if _player_has_bloody_coating(player) and not has_bloody_effect:
        effects.append(BloodyEffect(duration=None))

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

    hover_effects = hovered_effect is not None

    if not hover_effects:
        return

    lines = []

    if hover_effects:
        try:
            display = hovered_effect.get_display() if hasattr(hovered_effect, "get_display") else None
            duration = getattr(hovered_effect, "duration", None)
            turns_text = "indefinite" if duration is None else f"{duration}t"
            title = ((getattr(display, "label", None) if display else None) or getattr(hovered_effect, "name", "Unknown")) + (f" ({turns_text})")
            lines.append(title)
            desc = getattr(hovered_effect, "description", "") or "No description."
            lines.append(f"{desc}")
        except Exception:
            lines.append("Unknown")

    if not lines:
        return

    max_width = max(24, min(console.width - 4, max(len(line) for line in lines) + 2))
    # Main game view only blits HUD rows (y >= 39), so keep tooltip compact.
    max_body_lines = min(len(lines), 8)
    draw_lines = []
    for line in lines[:max_body_lines]:
        draw_lines.append(line[: max_width - 2])

    width = max_width
    height = len(draw_lines) + 2

    x = max(1, min(mouse_ui_x + 1, console.width - width - 1))

    # Restrict tooltip entirely to HUD strip so it remains visible after HUD-only blit.
    hud_top = 39
    hud_bottom = console.height - 1
    max_height_in_hud = max(3, hud_bottom - hud_top + 1)
    if height > max_height_in_hud:
        height = max_height_in_hud
        draw_lines = draw_lines[: max(1, height - 2)]

    y = max(hud_top, min(mouse_ui_y - height, hud_bottom - height + 1))

    console.draw_rect(x=x, y=y, width=width, height=height, ch=ord(" "), bg=color.parchment_bg)
    console.draw_frame(x=x, y=y, width=width, height=height, fg=color.bronze_border, bg=color.parchment_bg)

    for idx, line in enumerate(draw_lines, start=1):
        fg = color.fantasy_text if idx == 1 else color.bronze_text
        console.print(x=x + 1, y=y + idx, string=line, fg=fg, bg=color.parchment_bg)



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
