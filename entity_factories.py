from re import T
from components.ai import DarkHostileEnemy, Friendly, HostileEnemy
from components import consumable, equippable
from components.effect import Effect
from components.equipment import Equipment
from components.fighter import Fighter
from components.inventory import Inventory
from components.level import Level
from components.container import Container
from components.body_parts import BodyParts, AnatomyType
from entity import Actor, Item
from render_order import RenderOrder
import components.names as names
import sounds
from text_utils import *

player = Actor(
    char="☺",
    color=(52, 222, 235),
    name = "Player",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=30, base_defense=2, base_power=5),
    inventory=Inventory(capacity=26),
    level=Level(level_up_base=200),
    body_parts=BodyParts(AnatomyType.HUMANOID),
    # Temporary demo effect so the status-effects panel shows during testing
    effects = [],
    lucidity = 100,
    max_lucidity = 100,
    hunger = 100.0,
    speed=100,  # Normal/base speed
    dodge_chance=0.15,  # 15% chance to dodge attacks
    preferred_dodge_direction="north",  # Tendency to dodge towards the north (for flavor)

)

shade = Actor(
    char="S",
    sight_radius=1000,
    color=(100, 100, 100),
    name = "Shade",
    description="A dark figure, barely visible in the dim light. Stories say they wait for you in the shadows, but cannot cross into the light.",
    ai_cls=DarkHostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=2, base_power=5, leave_corpse=False),
    inventory=Inventory(capacity=5),
    level=Level(xp_given=0),
    speed=130,  # Very fast - supernatural creature
    opinion=0,
)

orc = Actor(
    char="o",
    color=(63, 127, 90),
    name = "Orc",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=3),
    inventory=Inventory(capacity=0),
    level=Level(xp_given=35),
    speed=120,  # Fast enough to sometimes act before player
    body_parts=BodyParts(AnatomyType.HUMANOID),
    verb_base="claw",
    verb_present="claws",
    verb_past="clawed",
    verb_participial="clawing",
    dodge_chance=0.05, 
    )

troll = Actor(
    char="T",
    color=(63, 127, 90),
    name = "Troll",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=16, base_defense=1, base_power=4),
    inventory=Inventory(capacity=0),
    level=Level(xp_given=100),
    speed=80,  # Slower than normal - big and lumbering
    body_parts=BodyParts(AnatomyType.HUMANOID),
    verb_base="smash",
    verb_present="smashes",
    verb_past="smashed",
    verb_participial="smashing",
    dodge_chance=0.01,  
    )

lesser_health_potion = Item(
    char="!",
    color=(127,0,255),
    name="Lesser Health Potion",
    consumable=consumable.HealingConsumables(amount=8),
    description="A small vial filled with a red liquid.",
    equip_sound=sounds.play_equip_glass_sound,
    unequip_sound=sounds.play_unequip_glass_sound,
    pickup_sound=sounds.pick_up_glass_sound,
    drop_sound=sounds.drop_glass_sound,
)
lightning_scroll = Item(
    char="~",
    color=(255,255,0),
    name="Lightning Scroll",
    consumable=consumable.LightningDamageConsumable(damage=20, maximum_range=5),
    description="A tattered scroll crackling with electricity.",
    equip_sound=sounds.play_equip_paper_sound,
    unequip_sound=sounds.play_unequip_paper_sound,
    pickup_sound=sounds.pick_up_paper_sound,
    drop_sound=sounds.drop_paper_sound,
)

confusion_scroll = Item(
    char="~",
    color=(207, 63, 255),
    name="Confusion Scroll",
    consumable=consumable.ConfusionConsumable(number_of_turns=10),
    description="A worn scroll that seems to distort the mind.",
    equip_sound=sounds.play_equip_paper_sound,
    unequip_sound=sounds.play_unequip_paper_sound,
    pickup_sound=sounds.pick_up_paper_sound,
    drop_sound=sounds.drop_paper_sound,
)

fireball_scroll = Item(
    char="~",
    color=(255,0,0),
    name="Fireball Scroll",
    consumable=consumable.FireballDamageConsumable(damage=12, radius=3),
    description="A singed scroll radiating intense heat.",
    equip_sound=sounds.play_equip_paper_sound,
    unequip_sound=sounds.play_unequip_paper_sound,
    pickup_sound=sounds.pick_up_paper_sound,
    drop_sound=sounds.drop_paper_sound,
)

campfire = Item(
    char="☼",
    color=(255, 140, 0),
    name="Campfire",
    description="A small campfire providing warmth and light.",
)

bonfire = Item(
    char="☼",
    color=(255, 140, 0),
    name="Bonfire",
    description="A large bonfire crackling with intense flames.",
)

torch = Item(
    char="!",
    color=(255, 200, 50),
    name="Torch",
    equippable=equippable.Torch(),
    burn_duration=600,
    description="A wooden torch that can be carried to provide light.",
    pickup_sound=sounds.pick_up_wood_sound,
    drop_sound=sounds.drop_wood_sound,
    equip_sound=sounds.play_torch_pull_sound,
    unequip_sound=sounds.play_torch_extinguish_sound,
    verb_base="smash",
    verb_present="smashes",
    verb_past="smashed",
    verb_participial="smashing",
)

dagger = Item(
    char="/", color=(0, 191, 255), name="Dagger",
    equippable=equippable.Dagger(),
    pickup_sound=sounds.pick_up_blade_sound,
    drop_sound=sounds.drop_blade_sound,
    equip_sound=sounds.play_equip_blade_sound,
    unequip_sound=sounds.play_unequip_blade_sound,
    verb_base="stab",
    verb_present="stabs",
    verb_past="stabbed",
    verb_participial="stabbing",

)

sword = Item(
    char="/", color=(0, 191, 255), name="Sword",
    equippable=equippable.Sword(),
    pickup_sound=sounds.pick_up_blade_sound,
    drop_sound=sounds.drop_blade_sound,
    equip_sound=sounds.play_equip_blade_sound,
    unequip_sound=sounds.play_unequip_blade_sound,
    verb_base="slash",
    verb_present="slashes",
    verb_past="slashed",
    verb_participial="slashing",
)

leather_armor = Item(
    char="[",
    color=(139, 69, 19),
    name="Leather Armor",
    equippable=equippable.LeatherArmor(),
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.pick_up_leather_sound,
    drop_sound=sounds.drop_leather_sound,
)

chain_mail = Item(
    char="[", color=(139, 69, 19),
    name="Chain Mail",
    equippable=equippable.ChainMail(),
)

dev_tool = Item(
    char="&", 
    color=(173, 0, 255),
    name="DevSword",
    equippable=equippable.devtool(),
)

backpack = Item(
    char="D",
    color=(139,69,19),
    name="Backpack",
    equippable=equippable.Backpack(),
)

chest = Actor(
    char="C",
    color=(222, 153, 52),
    name="Chest",
    # No AI for static container
    ai_cls=None,
    equipment=None,
    fighter=None,
    inventory=Inventory(capacity=0),
    level=Level(xp_given=0),
)

villager = Actor(
    char="☺",
    color=(255, 255, 0),
    name="Villager",
    ai_cls=Friendly,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=0),
    inventory=Inventory(capacity=26),
    level=Level(xp_given=10),
    sentient=True,
    is_known=False,
    type = "NPC",
    body_parts=BodyParts(AnatomyType.HUMANOID),
)

quest_giver = Actor(
    char="☺",
    color=(255, 0, 243),
    name="Quest Giver",
    ai_cls=Friendly,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=0),
    inventory=Inventory(capacity=26),
    level=Level(xp_given=50),
    is_known=False,
    sentient=True,
    type = "NPC",
    body_parts=BodyParts(AnatomyType.HUMANOID),
)

coin = Item(
    char="$",
    color=(255, 223, 0),
    name="Coin",
    description="A shiny gold coin.",
    value=1,
    weight=0.01,
)

fungus = Item(
    char="%",
    color=(0, 255, 0),
    name="Fungus",
    description="",
)

def get_random_fungus() -> Item:
    import random
    fungus_types = {
            "prefix": ["Cap", "Spot", "Gill", "Twist", "Iron", "Glow", "Silent", "Blood", "Red", "Blue", "Yellow",
                       "Purple", "Green", "Black", "White", "Silver", "Golden", "Shiny", "Smoke", "Dust", "Oak", "Pine", "Birch", "Maple",
                       "Dark"],
            "suffix": ["cap", "cap", "cap", "cap", "cup", "stem", "sprout", "spore", "bloom", "shroom", "-agaric", "root", "stalk", "puff"]
        }

    prefix = random.choice(fungus_types["prefix"])
    suffix = random.choice(fungus_types["suffix"])
    name = f"{prefix}{suffix}"
    description = "Placeholder"
    color = (random.randint(100, 255), random.randint(100, 255), random.randint(100, 255))

    # Color calibration based on name
    if "Blue" in prefix:
        color = (max(color[0]-50, 75), max(color[1]-50, 75), 255)
    elif "Red" in prefix:
        color = (255, max(color[1]-50, 75), max(color[2]-50, 75))

    elif "Green" in prefix:
        color = (max(color[0]-50, 75), 255, max(color[2]-50, 75))
    elif "Yellow" in prefix:
        color = (255, 255, max(color[2]-100, 75))
    elif "Purple" in prefix:
        color = (255, max(color[1]-100, 75), 255)
    elif "Black" in prefix:
        color = (0, 0, 0)
    elif "White" in prefix:
        color = (255, 255, 255)

    if "cap" in suffix or "cup" in suffix or "-agaric" in suffix or "puff" in suffix:
        char = ","
    else:
        char = "."
    if name == "Capcap":
        name = blue("L")+red("e")+green("g")+yellow("e")+purple("n")+white("d")+green("a")+cyan("r")+red("y") + " " + purple("C")+yellow("a")+white("p")+cyan("c")+purple("a")+green("p")
        
    
    return Item(
        char=char,
        color=color,
        name=name,
        description=description,
    )

def get_random_coins(min_amount: int, max_amount: int) -> Item:
    import random
    amount = random.randint(min_amount, max_amount)
    if amount == 1:
        def_name = "Coin"
        def_description = "A shiny gold coin."
    else:
        def_name = "Pile of Coins"
        def_description = f"A pile of {amount} gold coins."

    if amount == 1:
        def_equip_sound = sounds.play_equip_coin_sound
        def_unequip_sound = sounds.play_unequip_coin_sound
        def_pickup_sound = sounds.pick_up_coin_sound
        def_drop_sound = sounds.drop_coin_sound
    else:
        def_equip_sound = sounds.pick_up_manycoins_sound
        def_unequip_sound = sounds.pick_up_manycoins_sound
        def_pickup_sound = sounds.pick_up_manycoins_sound
        def_drop_sound = sounds.drop_manycoins_sound
    return Item(
        char="$",
        color=(255, 223, 0),    
        name=def_name,
        description=def_description,
        value=amount,
        weight=0.01 * amount,
        equip_sound=def_equip_sound,
        unequip_sound=def_unequip_sound,
        pickup_sound=def_pickup_sound,
        drop_sound=def_drop_sound,
    )




# Attach a Container component to a chest template (not an Actor constructor arg
# since the Actor expects certain component types). We'll create a light-weight
# chest_entity factory that will 'spawn' and then attach a Container to it when
# placed on the map via code elsewhere.
def make_chest_with_loot(items: list, capacity: int = 10) -> Actor:
    c = chest.spawn  # This is the Actor.spawn method; we want a template clone
    # Instead we'll build a fresh Actor instance based on the chest template
    new_chest = Actor(
        char=chest.char,
        color=chest.color,
        name=chest.name,
        ai_cls=None,
        equipment=Equipment(),
        fighter=None,
        inventory=Inventory(capacity=0),
        level=Level(xp_given=0),
        description="A sturdy chest.",
        sentient=False,
    )
    # Attach a Container component and populate it
    cont = Container(capacity=capacity)
    cont.parent = new_chest
    for it in items:
        cont.add(it)
    # Make chest block movement so it occupies a tile
    new_chest.blocks_movement = False
    new_chest.render_order = RenderOrder.CHEST  # Below actors, above items
    # Expose the container on the actor for easy checks
    new_chest.container = cont
    return new_chest

