from numpy import isin
import tcod
import traceback

import color
import exceptions
import input_handlers
import setup_game



def save_game(handler: input_handlers.BaseEventHandler, filename: str) -> None:
    # If current event handler has active engine then save it
    if isinstance(handler, input_handlers.EventHandler):
        handler.engine.save_as(filename)
        print("Game saved.")


def main() -> None:
    screen_width = 80
    screen_height = 50

    tileset = tcod.tileset.load_tilesheet(
        "dejavu16x16_gen1.png", 32, 8, tcod.tileset.CHARMAP_TCOD
    )

    handler: input_handlers.BaseEventHandler = setup_game.MainMenu()

    with tcod.context.new_terminal(
        screen_width,
        screen_height,
        tileset=tileset,
        title="Hello World",
        vsync=True,
    ) as context:
        console = tcod.console.Console(screen_width, screen_height, order="F")
        try:
            while True:
                console.clear()
                handler.on_render(console=console)
                context.present(console)

                try:
                    for event in tcod.event.wait():
                        context.convert_event(event)
                        handler = handler.handle_events(event)
                except Exception: # handles game exceptions
                    traceback.print_exc() #prints error to stderr
                    if isinstance(handler, input_handlers.EventHandler):
                        handler.engine.message_log.add_message(
                            traceback.format_exc(), color.error
                        )

        except exceptions.QuitWithoutSaving:
            raise
        except SystemExit: # save and quit
            save_game(handler, "savegame.sav")
            raise
        except BaseException: # Sacve on any other unexpected exception
            save_game(handler, "savegame.sav")
            raise

main()


