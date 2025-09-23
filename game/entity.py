from __future__ import annotations
import copy
from typing import Optional, Tuple, Type, TypeVar, TYPE_CHECKING

"""Entity module for game characters and objects."""

if TYPE_CHECKING:
    from game_map import GameMap
    from components.ai import BaseAI
    from components.fighter import Fighter

T = TypeVar("T", bound="Entity")


class Entity:

    gamemap: GameMap

    def __init__(
       self,
       gamemap: Optional[GameMap] = None,
        x: int = 0,
        y: int = 0,
        char: str = "?",
        color: Tuple[int, int, int] = (255, 255, 255),
        name: str = "<Unnamed>",
        blocks_movement: bool = False,
        ):
        self.x = x
        self.y = y
        self.char = char
        self.color = color
        self.name = name
        self.blocks_movement = blocks_movement
        if gamemap:
            self.gamemap = gamemap
            gamemap.entities.add(self)

    def place(self, x: int, y: int, gamemap: Optional[GameMap] = None) -> None:
        """Place this entity at a new location. Handles moving across GameMaps."""
        self.x = x
        self.y = y
        if gamemap:
            if hasattr(self, "gamemap"):
                self.gamemap.entities.remove(self)
            self.gamemap = gamemap
            gamemap.entities.add(self)
    
    def spawn(self: T, gamemap: GameMap, x: int, y: int) -> T:
        clone = copy.deepcopy(self)
        clone.x = x
        clone.y = y
        clone.gamemap = gamemap
        gamemap.entities.add(clone)
        return clone

    def move(self, dx: int, dy: int) -> None:
        #movement controls

        self.x += dx
        self.y += dy
class Actor(Entity):
    def __init__(
        self,
        *,
        x: int = 0,
        y: int = 0,
        char: str = "?",
        color: Tuple[int, int, int] = (255, 255, 255),
        name: str = "<Unnamed>",
        ai_cls: Type[BaseAI],
        fighter: Fighter,
        blocks_movement: bool = True,
    ):
        super().__init__(
            x=x,
            y=y,
            char=char,
            color=color,
            name=name, 
            blocks_movement=blocks_movement,
        )

        self.ai: Optional[BaseAI] = ai_cls(self)

        self.fighter = fighter
        self.fighter.entity = self

    @property
    def is_alive(self) -> bool:
        return bool(self.ai)