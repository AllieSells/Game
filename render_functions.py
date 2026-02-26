from __future__ import annotations

from typing import Tuple, TYPE_CHECKING
from types import SimpleNamespace

import tcod

import color
import text_utils

# Try to import animation helpers if they exist; fall back gracefully.
try:
    from animations import FireFlicker, FireSmoke, LightningAnimation, FireballAnimation
except Exception:
    FireFlicker = FireSmoke = LightningAnimation = FireballAnimation = None

if TYPE_CHECKING:
    from tcod import Console
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

def status_effect_overlay(console: Console, effects: list) -> None:
    y = 41
    if len(effects) > 0:
        for effect in effects:
            console.print(x=61, y=y, string=f"{effect.name}")
            y -= 1


def render_debug_overlay(console: Console, fps: float, player_pos: Tuple[int, int], handler_name: str, entity_count: int) -> None:          
    x, y = player_pos
    console.print(0, 38, f"Player: ({x}, {y})", fg=(255, 255, 255))
    console.print(0, 39, f"Handler: {handler_name}", fg=(255, 255, 255))
    console.print(0, 40, f"Entities: {entity_count}", fg=(255, 255, 255))
    console.print(0, 41, f"FPS: {fps:.1f}", fg=(255, 255, 255))







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


def status_effect_overlay(console: 'Console', effects: list) -> None:
    y = 41
    if len(effects) > 0:
        for effect in effects:
            console.print(x=61, y=y, string=f"{effect.name}")
            y -= 1



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
    COATING_TEXT_X = 10
    COATING_TEXT_Y = PANEL_Y + 2
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
    # Right part of horizontal line (after second divider at x=20)
    console.draw_rect(x=21, y=PANEL_Y+3, width=PANEL_WIDTH-22, height=1, ch=ord('─'), bg=color.parchment_dark, fg=color.bronze_border)
    # Combat stats on first content line
    dodge_text = f"DDG: {dodge_direction[0].upper() if dodge_direction else 'R'}"
    console.print(x=COMBAT_TEXT_X, y=PANEL_Y + 1, string=dodge_text, fg=color.bronze_text)
    
    # Get attack abbreviation from lookup table
    attack_abbrev = BODY_PART_ABBREV.get(attack_type, attack_type[:3].upper() if attack_type else "Rnd")
    console.print(x=COMBAT_TEXT_X, y=PANEL_Y + 2, string=f"ATK: {attack_abbrev}", fg=color.bronze_text)
    
    # Status conditions and effects on second content line
    status_conditions = []
    
    # Add liquid coating status if player has it
    if player and hasattr(player, 'liquid_coating') and player.liquid_coating:
        for coating in player.liquid_coating:
            try:
                liquid_name = coating.liquid_type.get_display_name()
                status_conditions.append(f"{liquid_name.title()}")
            except Exception:
                pass
    
    # Add other effects
    if player and hasattr(player, 'effects'):
        for effect in player.effects:
            try:
                status_conditions.append(effect.name)
            except Exception:
                pass
    
    # Display status conditions
    if status_conditions:
        status_text = "Effects: " + ", ".join(status_conditions[:6])  # Limit to 6 conditions
        console.print(x=EFFECTS_TEXT_X, y=PANEL_Y + 1, string=status_text[:76], fg=color.fantasy_text)  # Truncate if too long
    else:
        console.print(x=EFFECTS_TEXT_X, y=PANEL_Y + 1, string="Effects: None", fg=color.bronze_text)

    # Display liquid coating status
    coating_text = "Coating: "
    
    if player and hasattr(player, 'body_parts') and player.body_parts:
        # Collect unique coatings from all body parts
        unique_coatings = set()
        for part_type, body_part in player.body_parts.body_parts.items():
            if hasattr(body_part, 'coating') and body_part.coating:
                from liquid_system import LiquidType
                if body_part.coating != LiquidType.NONE:
                    unique_coatings.add(body_part.coating)
        
        if unique_coatings:
            # Display each unique coating with its color and description
            coating_parts = []
            for coating in unique_coatings:
                coat_description = coating.get_coat_string()
                if coat_description:  # Only show coatings with descriptions
                    coating_parts.append((coat_description, coating.get_display_color()))
            
            if coating_parts:
                # Display "Status: " label
                console.print(x=COATING_TEXT_X, y=COATING_TEXT_Y, string=coating_text, fg=color.bronze_text)
                
                # Display coating descriptions with colors
                x_offset = COATING_TEXT_X + len(coating_text)
                for i, (description, coating_color) in enumerate(coating_parts):
                    if i > 0:
                        console.print(x=x_offset, y=COATING_TEXT_Y, string=", ", fg=color.bronze_text)
                        x_offset += 2
                    # Capitalize the first coating description
                    display_desc = description.capitalize() if i == 0 else description
                    console.print(x=x_offset, y=COATING_TEXT_Y, string=display_desc, fg=coating_color)
                    x_offset += len(display_desc)
            else:
                console.print(x=COATING_TEXT_X, y=COATING_TEXT_Y, string=coating_text + "None", fg=color.bronze_text)
        else:
            console.print(x=COATING_TEXT_X, y=COATING_TEXT_Y, string=coating_text + "None", fg=color.bronze_text)
    else:
        console.print(x=COATING_TEXT_X, y=COATING_TEXT_Y, string=coating_text + "None", fg=color.bronze_text)

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

# Status effect render - now handled in render_combat_stats
def render_effects(console: 'Console', effects: list) -> None:
    # This function is now integrated into render_combat_stats for better organization
    # Keeping this stub for compatibility
    pass



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
    # ==============================
    
    # Fill entire interior with parchment background
    console.draw_rect(x=UI_LEFT+1, y=UI_TOP+1, width=UI_RIGHT-UI_LEFT-1, height=UI_BOTTOM-UI_TOP-1, ch=ord(' '), bg=color.parchment_dark)
    
    # Draw horizontal borders
    for x in range(UI_LEFT, UI_RIGHT + 1):
        console.print(x, UI_TOP, "─", fg=color.bronze_border)  # Top border
        console.print(x, UI_BOTTOM, "─", fg=color.bronze_border)  # Bottom border

    
    
    # Draw vertical borders
    for y in range(UI_TOP + 1, UI_BOTTOM):
        console.print(UI_LEFT, y, "│", fg=color.bronze_border)  # Left border
        console.print(UI_RIGHT, y, "│", fg=color.bronze_border)  # Right border
        if y >= UI_TOP + 4:  # Only draw center divider from the horizontal line down
            console.print(DIVIDER_X, y, "│", fg=color.bronze_border)  # Center divider
        if y <= UI_TOP + 3:  # Draw secondary divider on the left side for the top stats area
            console.print(DIVIDER_X2, y, "│", fg=color.bronze_border)  # Divider between message log and player info
    
    # Draw corners
    console.print(UI_LEFT, UI_TOP, "┌", fg=color.bronze_border)  # Top-left
    console.print(UI_RIGHT, UI_TOP, "┐", fg=color.bronze_border)  # Top-right  
    console.print(UI_LEFT, UI_BOTTOM, "└", fg=color.bronze_border)  # Bottom-left
    console.print(UI_RIGHT, UI_BOTTOM, "┘", fg=color.bronze_border)  # Bottom-right
    
    # Draw T-junctions where divider meets top/bottom borders
    console.print(DIVIDER_X, UI_TOP + 3, "┬", fg=color.bronze_border)  # Top T-junction at horizontal divider
    console.print(DIVIDER_X, UI_BOTTOM, "┴", fg=color.bronze_border)  # Bottom T-junction
    console.print(DIVIDER_X2, UI_TOP, "┬", fg=color.bronze_border)  # Top T-junction for second divider  
    console.print(DIVIDER_X2, UI_TOP + 3, "┴", fg=color.bronze_border)  # Bottom T-junction for second divider
    
    # Add left and right T-junctions on the horizontal divider line
    console.print(UI_LEFT, UI_TOP + 3, "├", fg=color.bronze_border, bg=(0, 0, 0))  # Left T-junction
    console.print(UI_RIGHT, UI_TOP + 3, "┤", fg=color.bronze_border, bg=(0, 0, 0))  # Right T-junction



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
