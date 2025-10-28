from __future__ import annotations
import copy
import math
import random
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

# Import names
from components import names


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
        dialogue_context: list = [],
        knowledge: dict = None,
        description: str = "",
        unknown_name: Optional[str] = None,
        is_known : bool = True,
        opinion: int = 50,
        sentient: bool = False,
        sight_radius: int = 6,
        gold: int = 0,
        hunger: float = 100.0,
        saturation: float = 100.0,
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
        self.dialogue_context = []
        self.knowledge = {
            "name": self.name,
        }
        self.description = description
        self.unknown_name = unknown_name
        self.is_known = is_known
        self.opinion = opinion
        self.sentient = sentient
        self.sight_radius = sight_radius
        self.gold = gold
        self.hunger = hunger
        self.saturation = saturation

    def add_effect(self, effect: 'Effect') -> None:
        """Attach an Effect to this actor."""
        if not hasattr(self, "effects"):
            self.effects = []
        self.effects.append(effect)

    def remove_effect(self, effect_type: str) -> None:
        """Remove an Effect based on type"""
        self.effects = [e for e in self.effects if e.type != effect_type]
        
    @property
    def is_alive(self) -> bool:
        return bool(self.ai)
    
    def generate_villager(self) -> None:
        print("Generating villager attributes...")
        # Generate villager-specific attributes or behaviors

        self.opinion += random.randint(-10, 10)

        gender_noun = {
            "man": 50,
            "woman": 50,
            "person": 5,
        }
        self.knowledge["gendered_noun"] = random.choices(list(gender_noun.keys()), weights=list(gender_noun.values()), k=1)[0]

        # Pronouns based on gendered noun
        if self.knowledge["gendered_noun"] == "man":
            self.knowledge["pronouns"] = {
                "subject": "he",
                "object": "him",
                "possessive_adjective": "his",
                "possessive": "his",
            }
            self.knowledge["gender"] = "Male"
        elif self.knowledge["gendered_noun"] == "woman":
            self.knowledge["pronouns"] = {
                "subject": "she",
                "object": "her",
                "possessive_adjective": "her",
                "possessive": "hers",
            }
            self.knowledge["gender"] = "Female"
        else:
            self.knowledge["pronouns"] = {
                "subject": "they",
                "object": "them",
                "possessive_adjective": "their",
                "possessive": "theirs",
            }
            self.knowledge["gender"] = "Androgynous"
        # Get name

        # Get age
        age = random.randint(16, 80)
        self.knowledge["age"] = age

        # Get hair color
        if age < 50:
            self.knowledge["age_group"] = "young"
            # Dict hair color weights
            hair_colors = {
                "black": 30,
                "brown": 40,
                "blonde": 20,
                "red": 10,
            }
            self.knowledge["hair_color"] = random.choices(list(hair_colors.keys()), weights=list(hair_colors.values()), k=1)[0]
        elif age >= 50:
            self.knowledge["age_group"] = "older"
            # Dict hair color weights for older villagers
            hair_colors = {
                "gray": 50,
                "black": 10,
                "brown": 20,
                "blonde": 10,
                "white": 10,
                "bald": 10,
            }
            self.knowledge["hair_color"] = random.choices(list(hair_colors.keys()), weights=list(hair_colors.values()), k=1)[0]
        elif age >= 70:
            self.knowledge["age_group"] = "elderly"
            # Dict hair color weights for elderly villagers
            hair_colors = {
                "gray": 40,
                "white": 40,
                "bald": 20,
            }
            self.knowledge["hair_color"] = random.choices(list(hair_colors.keys()), weights=list(hair_colors.values()), k=1)[0]
        else:
            hair_colors = {
                "hairless": 100}
            self.knowledge["hair_color"] = None
        if self.knowledge["hair_color"] == "bald" or self.knowledge["hair_color"] == "hairless":
            self.knowledge["hair_style"] = ""
        else:
            # Get hair style
            hair_styles = [
                "short",
                "long",
                "curly",
                "straight",
                "wavy",
            ]
            self.knowledge["hair_style"] = random.choice(hair_styles)

        # Facial hair
        if self.knowledge["gender"] == "Male" and age >= 18 or self.knowledge["gender"] == "Androgynous" and age >= 18:
            if random.random() <= .30:
                facial_hair_styles = [
                    "bearded",
                    "mustached",
                    "goateed",
                    "stubbled",
                ]
                self.knowledge["facial_hair"] = random.choice(facial_hair_styles)
            else:
                self.knowledge["facial_hair"] = None
        else:
            self.knowledge["facial_hair"] = None
        
        # Get complexion from dictionary (nested dicts with realistic weights)
        complexions = {
            "skin_tone": {
                "very pale": 5,
                "pale": 15,
                "fair": 25,
                "light olive": 10,
                "tan": 20,
                "brown": 15,
                "dark": 8,
                "very dark": 2,
            },
            "build": {
                " very slim": 8,
                " slim": 22,
                "n average": 40,
                "n athletic": 15,
                " muscular": 8,
                " heavyset": 7,
            },
            "marks": {
                None: 65,
                "freckles": 10,
                "scars": 8,
                "tattoos": 10,
                "birthmarks": 7,
            },
            "posture": {
                "slouched": 15,
                "commandingly" : 5,
                None: 70,
                "upright": 15,
            },
            "eye_color": {
                "brown": 40,
                "blue": 25,
                "green": 15,
                "gray": 10,
                "hazel": 10,
            },
        }

        # Pick skin tone
        skin_choices = list(complexions["skin_tone"].keys())
        skin_weights = list(complexions["skin_tone"].values())
        self.knowledge["skin_tone"] = random.choices(skin_choices, weights=skin_weights, k=1)[0]

        # Pick build
        build_choices = list(complexions["build"].keys())
        build_weights = list(complexions["build"].values())
        self.knowledge["build"] = random.choices(build_choices, weights=build_weights, k=1)[0]

        # Pick marks (store None when the chosen key is actually None)
        marks_choices = list(complexions["marks"].keys())
        marks_weights = list(complexions["marks"].values())
        marks_pick = random.choices(marks_choices, weights=marks_weights, k=1)[0]
        self.knowledge["marks"] = marks_pick

        # Pick posture
        posture_choices = list(complexions["posture"].keys())
        posture_weights = list(complexions["posture"].values())
        self.knowledge["posture"] = random.choices(posture_choices, weights=posture_weights, k=1)[0]

        # Pick eye color
        eye_choices = list(complexions["eye_color"].keys())
        eye_weights = list(complexions["eye_color"].values())
        self.knowledge["eye_color"] = random.choices(eye_choices, weights=eye_weights, k=1)[0]

        # Clothing style
        clothing_styles = {
            "casual": 20,
            "formal": 5,
            "ragged": 50,
        }
        clothing_choices = list(clothing_styles.keys())
        clothing_weights = list(clothing_styles.values())
        self.knowledge["clothing_style"] = random.choices(clothing_choices, weights=clothing_weights, k=1)[0]

        # clothing generation
        if self.knowledge["clothing_style"] == "casual":
            clothing_options = {
                "head": {
                    "thread cap": 30,
                    "leather cap": 20,
                    "cloth hood": 50,
                    None: 50,
                },
                "torso": {
                    "linen tunic": 40,
                    "thread tunic": 30,
                    "cloth tunic": 30,
                    None: 10,
                },
                "legs": {
                    "linen trousers": 40,
                    "thread trousers": 30,
                    "cloth trousers": 30,
                },
                "feet": {
                    "leather boots": 50,
                    "cloth shoes": 50,
                    None: 50,
                },
                "accessories": {
                    "leather belts": 40,
                    "cloth belts": 30,
                    "simple necklaces": 20,
                    None: 90,
                },
            }
        elif self.knowledge["clothing_style"] == "formal":
            clothing_options = {
                "head": {
                    "silk hat": 50,
                    "felt hat": 30,
                    None: 70,
                },
                "torso": {
                    "silk robe": 50,
                    "velvet robe": 30,
                    None: 70,
                },
                "legs": {
                    "silk trousers": 50,
                    "velvet trousers": 30,
                },
                "feet": {
                    "silk shoes": 50,
                    "leather shoes": 30,
                    None: 70,
                },
                "accessories": {
                    "gold necklaces": 40,
                    "silver rings": 30,
                    None: 70,
                },
            }
        elif self.knowledge["clothing_style"] == "ragged":
            clothing_options = {
                "head": {
                    "torn cloth hood": 70,
                    "dirty leather cap": 30,
                    None: 80,
                },
                "torso": {
                    "ragged tunic": 70,
                    "dirty cloth tunic": 30,
                    None: 20,
                },
                "legs": {
                    "torn trousers": 70,
                    "dirty cloth trousers": 30,
                },
                "feet": {
                    "worn leather boots": 70,
                    "dirty cloth shoes": 30,
                    None: 60,
                },
                "accessories": {
                    "broken neckalces": 50,
                    "frayed belts": 50,
                    None: 80,
                },
            }
        clothing_colors = {
            "white": 20,
            "black": 20,
            "brown": 20,
            "gray": 10,
            "blue": 15,
            "red": 5,
            "green": 15,
            "yellow": 1,
            "purple": 2,
        }
        for slot, options in clothing_options.items():
            option_choices = list(options.keys())
            option_weights = list(options.values())
            picked_item = random.choices(option_choices, weights=option_weights, k=1)[0]
            if picked_item is None:
                self.knowledge[slot] = None
            else:
                color_choices = list(clothing_colors.keys())
                color_weights = list(clothing_colors.values())
                picked_color = random.choices(color_choices, weights=color_weights, k=1)[0]
                self.knowledge[slot] = f"{picked_color} {picked_item}"



        # Description generation
        # Hair
        self.knowledge["description"] = f"The {self.knowledge['age_group']} {self.knowledge['gendered_noun']}"
        if self.knowledge["hair_color"] == "bald" or self.knowledge["hair_color"] == "hairless":
            if self.knowledge["facial_hair"]:
                self.knowledge["description"] += f" is bald, with a {self.knowledge['facial_hair']} face."
            else:
                self.knowledge["description"] += f" is bald."
        else:
            self.knowledge["description"] += f" has {self.knowledge['hair_style']} {self.knowledge['hair_color']} hair"
            if self.knowledge["facial_hair"]:
                self.knowledge["description"] += f" and a {self.knowledge['facial_hair']} face."
            else:
                self.knowledge["description"] += f"."

        # Eyes
        self.knowledge["description"] += f" {self.knowledge['pronouns']['possessive_adjective'].capitalize()} eyes are {self.knowledge['eye_color']}."
        # Build
        if self.knowledge["gender"] != "Androgynous":
            self.knowledge["description"] += f" {self.knowledge['pronouns']['subject'].capitalize()} has {self.knowledge['skin_tone']} skin, and a{self.knowledge['build']} build."
        else:
            self.knowledge["description"] += f" {self.knowledge['pronouns']['subject'].capitalize()} have {self.knowledge['skin_tone']} skin, and a{self.knowledge['build']} build."
        # Marks
        if self.knowledge["marks"]:
            self.knowledge["description"] += f" {self.knowledge['pronouns']['possessive_adjective'].capitalize()} skin has {self.knowledge['marks']}."
        # Posture
        if self.knowledge["posture"]:
            self.knowledge["description"] += f" {self.knowledge['pronouns']['subject'].capitalize()} stands {self.knowledge['posture']}."
        
        if self.knowledge["clothing_style"] == "ragged":
            self.knowledge["description"] += f" {self.knowledge['pronouns']['possessive_adjective'].capitalize()} clothes are ragged and worn."
        elif self.knowledge["clothing_style"] == "formal":
            self.knowledge["description"] += f" {self.knowledge['pronouns']['possessive_adjective'].capitalize()} clothes are formal and well-kept."
        else:
            # Nothing extra for casual
            pass

        # Clothing details
        clothing_slots = ["head", "torso", "legs", "feet", "accessories"]
        subject = self.knowledge['pronouns']['subject'].capitalize()
        # Start the clothing clause without a presumptive article; handle articles per case below.
        if self.knowledge["gender"] != "Androgynous":
            self.knowledge["description"] += f" {subject} is wearing a "
        else:
            self.knowledge["description"] += f" {subject} are wearing a "
        items = [self.knowledge.get(slot) or "" for slot in clothing_slots]
        # Treat None as blank and filter out empty strings
        items = [item for item in items if item]
        if not items:
            self.knowledge["description"] += "nothing"
        elif len(items) == 1:
            item = items[0]
            # If the item already begins with an article, use it; otherwise add "a" or "an" appropriately.
            first_word = item.split()[0].lower() if item else ""
            if first_word in ("a", "an", "the"):
                self.knowledge["description"] += item
            else:
                article = "an " if item and item[0].lower() in "aeiou" else "a "
                self.knowledge["description"] += article + item
        elif len(items) == 2:
            self.knowledge["description"] += f"{items[0]} and {items[1]}"
        else:
            self.knowledge["description"] += ", ".join(items[:-1]) + ", and " + items[-1]

        self.knowledge["description"] += "."


        return self.knowledge["description"]
                


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
            description: str = "<No description>",
            equippable: Optional[Equippable] = None,
            burn_duration: Optional[int] = None,
            value: int = 0,
            weight: float = 0.0,

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
        self.description = description
        self.value = value
        self.weight = weight
        