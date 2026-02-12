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
            from liquid_system import LiquidType
            liquid_names = {
                LiquidType.WATER: "water",
                LiquidType.BLOOD: "blood",
                LiquidType.OIL: "oil", 
                LiquidType.SLIME: "slime"
            }
            liquid_name = liquid_names.get(coating.liquid_type, "unknown liquid")
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



# HP bar render
def render_bar(
        console: 'Console', current_value: int, maximum_value: int, total_width: int
) -> None:
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
            x=1, y=44, width=bar_width, height=1, ch=1, bg=bar_color
        )

    console.print(
        x=2, y=44, string=f"HP: {current_value}/{maximum_value}", fg=color.fantasy_text
    )

# Lucidity bar render
def render_lucidity_bar(
        console: 'Console', current_value: int, maximum_value: int, total_width: int
) -> None:
    bar_width = int(float(current_value) / maximum_value * (total_width - 2))  # Account for border

    if bar_width > 0:
        console.draw_rect(
            x=1, y=45, width=bar_width, height=1, ch=1, bg=(80, 80, 140)
        )

    console.print(
        x=2, y=45, string=f"Lucidity: {current_value}/{maximum_value}", fg=color.fantasy_text
    )

def render_player_level(
        console: 'Console', current_value: int, maximum_value: int, total_value: int, total_width: int
) -> None:
    bar_width = int(float(current_value) / maximum_value * (total_width - 2))  # Account for border
    
    if bar_width > 0:
        console.draw_rect(
            x=1, y=46, width=bar_width, height=1, ch=1, bg=(120, 60, 200)
        )

    console.print(
        x=2, y=46, string=f"Level: {current_value}/{maximum_value} ({total_value})", fg=color.fantasy_text
    )



def render_dungeon_level(
        console: 'Console', dungeon_level: int, map: GameMap = None,
) -> None:
    # Render the level the player is on, at the given location
    x = 0
    y = 48

    console.print(x=x+2, y=y, string=f"Dungeon: {dungeon_level}", fg=color.bronze_text)

def render_gold(
        console: 'Console', gold_amount: int,
) -> None:
    # Render the player's gold amount at the given location
    x = 0
    y = 47

    console.print(x=x+2, y=y, string=f"Gold: {gold_amount}", fg=color.gold_accent)

# Render dodge direction
def render_combat_stats(
        console: 'Console', dodge_direction: str = "North", attack_type: str = "Random", 
) -> None:
    text = f"Dodging: {dodge_direction.title() if dodge_direction else 'Random'} Targeting: {attack_type.title() if attack_type else 'Random'}"
    text_utils.print_colored_markup(console=console, x=1, y=40, text=text)

# Status effect render
def render_effects(console: 'Console', effects: list) -> None:
    # Display a single lighting status word on the right-hand panel.
    effect_display = "Effects: "
    for effect in effects:
        try:
            effect_display += effect.name + " "
        except Exception:
            pass
    text_utils.print_colored_markup(console=console, x=1, y=41, text=effect_display, default_color=color.bronze_text)



def render_bottom_ui_border(console: tcod.Console):
    """
    Draw a simple border around the entire bottom UI area with a vertical divider.
    """
    # Bottom UI starts at y=42 and goes to bottom of screen
    ui_top = 42
    ui_bottom = console.height - 1
    ui_left = 0
    ui_right = console.width - 1
    divider_x = 20  # Vertical divider between stats and message log
    
    # Fill entire interior with parchment background
    console.draw_rect(x=ui_left+1, y=ui_top+1, width=ui_right-ui_left-1, height=ui_bottom-ui_top-1, ch=ord(' '), bg=color.parchment_dark)
    
    # Draw horizontal borders
    for x in range(ui_left, ui_right + 1):
        console.print(x, ui_top, "─", fg=color.bronze_border)  # Top border
        console.print(x, ui_bottom, "─", fg=color.bronze_border)  # Bottom border
    
    # Draw vertical borders
    for y in range(ui_top + 1, ui_bottom):
        console.print(ui_left, y, "│", fg=color.bronze_border)  # Left border
        console.print(ui_right, y, "│", fg=color.bronze_border)  # Right border
        console.print(divider_x, y, "│", fg=color.bronze_border)  # Center divider
    
    # Draw corners
    console.print(ui_left, ui_top, "┌", fg=color.bronze_border)  # Top-left
    console.print(ui_right, ui_top, "┐", fg=color.bronze_border)  # Top-right  
    console.print(ui_left, ui_bottom, "└", fg=color.bronze_border)  # Bottom-left
    console.print(ui_right, ui_bottom, "┘", fg=color.bronze_border)  # Bottom-right
    
    # Draw T-junctions where divider meets top/bottom borders
    console.print(divider_x, ui_top, "┬", fg=color.bronze_border)  # Top T-junction
    console.print(divider_x, ui_bottom, "┴", fg=color.bronze_border)  # Bottom T-junction



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
    armor_name = engine.player.equipment.armor.name if engine.player.equipment.armor else "None"
    held_name = engine.player.equipment.weapon.name if engine.player.equipment.weapon else "None"
    offhand_name = engine.player.equipment.offhand.name if getattr(engine.player.equipment, 'offhand', None) else "None"
    back_name = engine.player.equipment.backpack.name if engine.player.equipment.backpack else "None"
    console.print(x=x, y=y, string="Equipment:")
    console.print(x=x, y=y+1, string=f"Body: {armor_name}")
    console.print(x=x, y=y+2, string=f"Back: {back_name}")
    console.print(x=x, y=y+3, string=f"Hands: {held_name}")
    console.print(x=x, y=y+4, string=f"Offhand: {offhand_name}")
    
    
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
