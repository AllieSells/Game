from __future__ import annotations
import copy
import math
from typing import Optional, Tuple, Type, TypeVar, TYPE_CHECKING, Union

from render_order import RenderOrder

"""Entity module for game characters and objects."""

if TYPE_CHECKING:
    from components.ai import BaseAI
    from components.consumable import Consumable
    from components.equipment import Equipment
    from components.equippable import Equippable
    from components.fighter import Fighter
    from components.inventory import Inventory
    from components.level import Level
    from components.effect import Effect
    from game_map import GameMap

T = TypeVar("T", bound="Entity")


class Entity:

    parent: Union[GameMap, Inventory]

    def __init__(
            # DEFAULTS
       self,
       parent: Optional[GameMap] = None,
        x: int = 0,
        y: int = 0,
        char: str = "?",
        color: Tuple[int, int, int] = (255, 255, 255),
        name: str = "<Unnamed>",
        blocks_movement: bool = False,
        render_order: RenderOrder = RenderOrder.CORPSE
        ):
        self.x = x
        self.y = y
        self.char = char
        self.color = color
        self.name = name
        self.blocks_movement = blocks_movement
        self.render_order = render_order
        if parent:
            self.parent = parent
            parent.entities.add(self)

    @property
    def gamemap(self) -> GameMap:
        return self.parent.gamemap

    def place(self, x: int, y: int, gamemap: Optional[GameMap] = None) -> None:
        """Place this entity at a new location. Handles moving across GameMaps."""
        self.x = x
        self.y = y
        if gamemap:
            if hasattr(self, "parent"):
                if self.parent is self.gamemap:
                    self.gamemap.entities.remove(self)
            self.parent = gamemap
            gamemap.entities.add(self)
    
    def distance(self, x: int, y: int) -> float:
        # returns the distance between current entity and given x,y

        return math.sqrt((x-self.x) ** 2 + (y - self.y) ** 2)

    def spawn(self: T, gamemap: GameMap, x: int, y: int) -> T:
        clone = copy.deepcopy(self)
        clone.x = x
        clone.y = y
        clone.parent = gamemap
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
        ai_cls: Optional[Type[BaseAI]] = None,
        equipment: Optional[Equipment] = None,
        fighter: Optional[Fighter] = None,
        inventory: Optional[Inventory] = None,
        level: Optional[Level] = None,
        effects: Optional[list] = None,
        lucidity: int = None,
        max_lucidity: int = None,
        type: str = "None",
    ):
        super().__init__(
            x=x,
            y=y,
            char=char,
            color=color,
            name=name, 
            blocks_movement=True,
            render_order=RenderOrder.ACTOR
        )

        # Initialize AI if provided
        self.ai: Optional[BaseAI] = ai_cls(self) if ai_cls is not None else None

        # Attach optional components and set their parent links when present
        self.equipment: Optional[Equipment] = None
        if equipment is not None:
            self.equipment = equipment
            self.equipment.parent = self

        self.fighter: Optional[Fighter] = None
        if fighter is not None:
            self.fighter = fighter
            self.fighter.parent = self

        self.inventory: Optional[Inventory] = None
        if inventory is not None:
            self.inventory = inventory
            self.inventory.parent = self

        self.level: Optional[Level] = None
        if level is not None:
            self.level = level
            self.level.parent = self

        # Effects: a list of Effect instances applied to this actor
        # Initialize inside __init__ to avoid circular import issues at module top-level
        self.effects = effects if effects is not None else []
        self.lucidity = lucidity if lucidity is not None else 100
        self.max_lucidity = max_lucidity if max_lucidity is not None else 100
        self.type = type

    def add_effect(self, effect: 'Effect') -> None:
        """Attach an Effect to this actor."""
        if not hasattr(self, "effects"):
            self.effects = []
        self.effects.append(effect)

    def remove_effect(self, effect: 'Effect') -> None:
        """Remove an Effect from this actor if present."""
        try:
            self.effects.remove(effect)
        except ValueError:
            pass

    @property
    def is_alive(self) -> bool:
        return bool(self.ai)
    
class Item(Entity):
    def __init__(
            self,
            *,
            x: int = 0,
            y: int = 0,
            char: str = "?",
            color: Tuple[int, int, int] = (255,255,255),
            name: str = "<Unnamed>",
            consumable: Optional[Consumable] = None,
        equippable: Optional[Equippable] = None,
        burn_duration: Optional[int] = None,

    ):
        super().__init__(
            x=x,
            y=y,
            char=char,
            color=color,
            name=name,
            blocks_movement=False,
            render_order=RenderOrder.ITEM,
        )
        
        self.consumable = consumable

        if self.consumable:
            self.consumable.parent = self

        self.equippable = equippable

        if self.equippable:
            self.equippable.parent = self

        # Optional burn duration (in player turns) for items like torches.
        # When the value reaches 0 the item should be consumed/removed.
        self.burn_duration = burn_duration

        