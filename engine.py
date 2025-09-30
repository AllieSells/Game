from __future__ import annotations

import lzma
import pickle
from typing import TYPE_CHECKING

from tcod.console import Console
from tcod.map import compute_fov
from collections import deque

import exceptions
import game_map
from message_log import MessageLog
import render_functions

if TYPE_CHECKING:
    from entity import Actor
    from game_map import GameMap, GameWorld




class Engine:

    game_map: GameMap
    game_world: GameWorld

    def __init__(self, player: Actor):
        self.message_log = MessageLog()
        self.mouse_location = (0,0)
        self.player = player
        
        self.animation_queue = deque()
        self.animations_enabled = True


    def tick(self, console: Console):
        expired = []
        for anim in list(self.animation_queue):
            anim.tick(console, self.game_map)  # pass the console here
            if anim.frames <= 0:
                expired.append(anim)

        for anim in expired:
            self.animation_queue.remove(anim)

    def process_animations(self):
        if not self.animation_queue:
            return
        
        for animation in list(self.animation_queue):
            animation.tick()
            if animation.frames <= 0:
                self.animation_queue.remove(animation)

    def save_as(self, filename: str) -> None:
        # save this engine instance as a compressed file
        save_data = lzma.compress(pickle.dumps(self))
        with open(filename, "wb") as f:
            f.write(save_data)
    
    def handle_enemy_turns(self) -> None:
        for entity in set(self.game_map.actors) - {self.player}:
            if entity.ai:
                try:
                    entity.ai.perform()
                except exceptions.Impossible:
                    pass # Ignore


    def update_fov(self) -> None:
        self.game_map.visible[:] = compute_fov(
            self.game_map.tiles["transparent"],
            (self.player.x, self.player.y),
            radius=10,
        )
        self.game_map.explored |= self.game_map.visible
            
    def render(self, console: Console) -> None:
        self.game_map.render(console)

        self.message_log.render(console=console, x=21, y=43, width=39, height=4)

        render_functions.render_bar(
            console=console,
            current_value=self.player.fighter.hp,
            maximum_value=self.player.fighter.max_hp,
            total_width=20
        )

        render_functions.render_dungeon_level(
            console=console,
            dungeon_level=self.game_world.current_floor,
            location=(0, 45),
        )

        render_functions.render_player_level(
            console=console,
            current_value=self.player.level.current_xp,
            maximum_value=self.player.level.experience_to_next_level,
            total_value=self.player.level.current_level,
            total_width=20,

        )

        render_functions.render_names_at_mouse_location(
            console=console, x=1, y=43, engine=self
            )
        
        render_functions.render_separator(
            console=console,
        )
        
        render_functions.render_equipment(
            console=console, x=61, y=43, engine=self
        )
