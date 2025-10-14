"""Handle the loading and initialization of game sessions."""
from __future__ import annotations

import copy
import lzma
import pickle
from tempfile import TemporaryFile
import traceback
from typing import Optional

import tcod

import color
from engine import Engine
import entity_factories
from game_map import GameWorld
import input_handlers



# Load the background image and remove the alpha channel.
background_image = tcod.image.load("image.png")[:, :, :3]


def new_game() -> Engine:
    """Return a brand new game session as an Engine instance."""
    map_width = 80
    map_height = 40

    room_max_size = 10
    room_min_size = 6
    max_rooms = 30


    player = copy.deepcopy(entity_factories.player)

    engine = Engine(player=player)
    print(engine)

    engine.game_world = GameWorld(
        engine=engine,
        max_rooms=max_rooms,
        room_min_size=room_min_size,
        room_max_size=room_max_size,
        map_width=map_width,
        map_height=map_height,
    )

    engine.game_world.generate_floor()
    engine.update_fov()

    engine.message_log.add_message("Press ? For Controls")
    engine.message_log.add_message(
        "You enter the dungeon. Haunted figures move in the dark...", color.welcome_text
    )

    dagger = copy.deepcopy(entity_factories.dagger)
    leather_armor = copy.deepcopy(entity_factories.leather_armor)


    dagger.parent = player.inventory
    leather_armor.parent = player.inventory

    player.inventory.items.append(dagger)
    player.equipment.toggle_equip(dagger, add_message=False)

    player.inventory.items.append(leather_armor)
    player.equipment.toggle_equip(leather_armor, add_message=False)


    return engine

def load_game(filename: str) -> Engine:
    # Load engine instance from file
    with open(filename, "rb") as f:
        engine = pickle.loads(lzma.decompress(f.read()))
    assert isinstance(engine, Engine)
    return engine 

class MainMenu(input_handlers.BaseEventHandler):
    """Handle the main menu rendering and input."""

    def on_render(self, console: tcod.Console) -> None:
        """Render the main menu on a background image."""
        console.draw_semigraphics(background_image, 0, 0)

        console.print(
            console.width // 2,
            console.height // 2 - 4,
            "WORK IN PROGRESS TITLE?",
            fg=color.menu_title,
            bg=color.black,
            alignment=tcod.CENTER,
            bg_blend=tcod.BKGND_ALPHA(64),
        )
        console.print(
            console.width // 2,
            console.height - 3,
            "oxenfree\n2025\nVersion 0.11 Pre-Alpha",
            fg=color.menu_title,
            alignment=tcod.CENTER,
        )

        menu_width = 24
        for i, text in enumerate(
            ["[N] Play a new game", "[C] Continue last game", "[Q] Quit"]
        ):
            console.print(
                console.width // 2,
                console.height // 2 - 2 + i,
                text.ljust(menu_width),
                fg=color.menu_text,
                bg=color.black,
                alignment=tcod.CENTER,
                bg_blend=tcod.BKGND_ALPHA(64),
            )

    def ev_keydown(
        self, event: tcod.event.KeyDown
    ) -> Optional[input_handlers.BaseEventHandler]:
        if event.sym in (tcod.event.KeySym.Q, tcod.event.K_ESCAPE):
            raise SystemExit()
        elif event.sym == tcod.event.KeySym.C:
            print("TEST")
            try:
                return input_handlers.MainGameEventHandler(load_game("savegame.sav"))
            except FileNotFoundError:
                return input_handlers.PopupMessage(self, "No saved game to load.")
            except Exception as exc:
                traceback.print_exc() # print to stderr
                return input_handlers.PopupMessage(self, f"Failed to load save :\n{exc}")
            pass
        elif event.sym == tcod.event.KeySym.N:
            return input_handlers.MainGameEventHandler(new_game())

        return None