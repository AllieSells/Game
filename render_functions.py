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
    
    # If no entities, show tile name instead
    if not names:
        names = tile
    else:
        names = f"{names} ({tile})"
    
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
    bar_width = int(float(current_value) / maximum_value * total_width)

    console.draw_rect(x=0, y=43, width=total_width, height=1, ch=1, bg=color.bar_empty)

    if bar_width > 0:
        console.draw_rect(
            x=0, y=43, width=bar_width, height=1, ch=1, bg=color.bar_filled
        )

    console.print(
        x=1, y=43, string=f"HP: {current_value}/{maximum_value}", fg=color.bar_text
    )

# Lucidity bar render
def render_lucidity_bar(
        console: 'Console', current_value: int, maximum_value: int, total_width: int
) -> None:
    bar_width = int(float(current_value) / maximum_value * total_width)

    console.draw_rect(x=0, y=44, width=total_width, height=1, ch=1, bg=color.lucidity_bar_empty)

    if bar_width > 0:
        console.draw_rect(
            x=0, y=44, width=bar_width, height=1, ch=1, bg=color.lucidity_bar_filled
        )

    console.print(
        x=1, y=44, string=f"Lucidity: {current_value}/{maximum_value}", fg=color.bar_text
    )

def render_player_level(
        console: 'Console', current_value: int, maximum_value: int, total_value: int, total_width: int
) -> None:
    bar_width = int(float(current_value) / maximum_value * total_width)

    console.draw_rect(x=0, y=45, width=total_width, height=1, ch=1, bg=color.xp_bar_empty)

    if bar_width > 0:
        console.draw_rect(
            x=0, y=45, width=bar_width, height=1, ch=1, bg=color.xp_bar_filled
        )

    console.print(
        x=1, y=45, string=f"Level: {current_value}/{maximum_value} ({total_value})", fg=color.bar_text
    )



def render_dungeon_level(
        console: 'Console', dungeon_level: int, map: GameMap = None,
) -> None:
    # Render the level the player is on, at the given location
    x = 0
    y = 47

    console.print(x=x+1, y=y, string=f"Dungeon: {dungeon_level}")

def render_gold(
        console: 'Console', gold_amount: int,
) -> None:
    # Render the player's gold amount at the given location
    x = 0
    y = 46

    console.print(x=x+1, y=y, string=f"Gold: {gold_amount}")

# Status effect render
def render_effects(console: 'Console', effects: list) -> None:
    # Display a single lighting status word on the right-hand panel.
    effect_display = "Effects: "
    for effect in effects:
        try:
            effect_display += effect.name + " "
        except Exception:
            pass
    text_utils.print_colored_markup(x=2, y=41, console=console, text=effect_display)



def render_separator(console: tcod.Console, y: int = 42, vline_xs: list[int] = [20, 60], vline_height: int = 7):
    """
    Draw a horizontal separator with vertical bars forming T junctions.
    vline_xs: list of x positions for vertical bars
    """
    # Draw horizontal line
    console.hline(0, y, console.width, ord('─'))

    max_y = console.height

    for vline_x in vline_xs:
        # Clamp vertical line height
        height = min(vline_height, max_y - (y + 1))

        # Draw vertical line
        console.vline(vline_x, y + 1, height, ord('│'))

        # Draw T junction at intersection
        console.print(vline_x, y, "┬")

        # Apply colors along vertical line
        for yy in range(y + 1, y + 1 + height):
            console.fg[vline_x, yy] = color.white
            console.bg[vline_x, yy] = color.black

        # Apply colors to T junction
        console.fg[vline_x, y] = color.white
        console.bg[vline_x, y] = color.black

    # Apply colors for horizontal line
    for x in range(console.width):
        console.fg[x, y] = color.white
        console.bg[x, y] = color.black



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
