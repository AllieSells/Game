from __future__ import annotations

from typing import Tuple, TYPE_CHECKING
from animations import Animation


import color

if TYPE_CHECKING:
    from tcod import Console
    from engine import Engine
    from game_map import GameMap



def get_names_at_location(x: int, y: int, game_map: GameMap) -> str:
    x,y = int(x), int(y)
    if not game_map.in_bounds(x, y) or not game_map.visible[x, y]:
        return ""

    names = ", ".join(
        entity.name for entity in game_map.entities if entity.x == x and entity.y == y
    )

    return names.capitalize()



def render_bar(
        console: Console, current_value: int, maximum_value: int, total_width: int
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

def render_dungeon_level(
        console: Console, dungeon_level: int, location: Tuple[int, int]
) -> None:
    # Render the level the player is on, at the given location
    x, y = location

    console.print(x=x+1, y=y, string=f"Dungeon: {dungeon_level}")


def render_player_level(
        console: Console, current_value: int, maximum_value: int, total_value: int, total_width: int
) -> None:
    bar_width = int(float(current_value) / maximum_value * total_width)

    console.draw_rect(x=0, y=44, width=total_width, height=1, ch=1, bg=color.xp_bar_empty)

    if bar_width > 0:
        console.draw_rect(
            x=0, y=44, width=bar_width, height=1, ch=1, bg=color.xp_bar_filled
        )

    console.print(
        x=1, y=44, string=f"Level: {current_value}/{maximum_value} ({total_value})", fg=color.bar_text
    )

import tcod


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
        console: Console, x: int, y: int, engine: Engine
) -> None:
    mouse_x, mouse_y = engine.mouse_location

    names_at_mouse_location = get_names_at_location(
        x=mouse_x, y=mouse_y, game_map=engine.game_map
    )

    console.print(x=x, y=y, string=names_at_mouse_location)

def render_equipment(
        console: Console, x: int, y: int, engine: Engine
) -> None:
    armor_name = engine.player.equipment.armor.name if engine.player.equipment.armor else "None"
    held_name = engine.player.equipment.weapon.name if engine.player.equipment.weapon else "None"
    console.print(x=x, y=y, string="Equipment:")
    console.print(x=x, y=y+1, string=f"Body: {armor_name}")
    console.print(x=x, y=y+2, string=f"Hands: {held_name}")
    
    
def render_animations(console: tcod.Console, engine: Engine) -> None:
    for anim in list(engine.animations):
        anim.render(console)
        if anim.expired():
            engine.animations.remove(anim)
