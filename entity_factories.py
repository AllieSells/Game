from re import T
from components.ai import DarkHostileEnemy, Friendly, HostileEnemy
from components import consumable, equippable
from components.effect import Effect
from components.equipment import Equipment
from components.fighter import Fighter
from components.inventory import Inventory
from components.level import Level
from components.container import Container
from entity import Actor, Item
from render_order import RenderOrder
import components.names as names

player = Actor(
    char="@",
    color=(52, 222, 235),
    name = "Player",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=30, base_defense=2, base_power=5),
    inventory=Inventory(capacity=26),
    level=Level(level_up_base=200),
    # Temporary demo effect so the status-effects panel shows during testing
    effects = [],
    lucidity = 100,
    max_lucidity = 100,

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
    )

health_potion = Item(
    char="!",
    color=(127,0,255),
    name="Health Potion",
    consumable=consumable.HealingConsumables(amount=4),
    description="A small vial filled with a red liquid.",
)
lightning_scroll = Item(
    char="~",
    color=(255,255,0),
    name="Lightning Scroll",
    consumable=consumable.LightningDamageConsumable(damage=20, maximum_range=5),
    description="A tattered scroll crackling with electricity.",
)

confusion_scroll = Item(
    char="~",
    color=(207, 63, 255),
    name="Confusion Scroll",
    consumable=consumable.ConfusionConsumable(number_of_turns=10),
    description="A worn scroll that seems to distort the mind.",
)

fireball_scroll = Item(
    char="~",
    color=(255,0,0),
    name="Fireball Scroll",
    consumable=consumable.FireballDamageConsumable(damage=12, radius=3),
    description="A singed scroll radiating intense heat.",
)

campfire = Item(
    char="x",
    color=(255, 140, 0),
    name="Campfire",
    description="A small campfire providing warmth and light.",
)

bonfire = Item(
    char="X",
    color=(255, 140, 0),
    name="Bonfire",
    description="A large bonfire crackling with intense flames.",
)

torch = Item(
    char="!",
    color=(255, 200, 50),
    name="Torch",
    equippable=equippable.Torch(),
    burn_duration=300,
    description="A wooden torch that can be carried to provide light.",
)

dagger = Item(
    char="/", color=(0, 191, 255), name="Dagger",
    equippable=equippable.Dagger()

)

sword = Item(
    char="/", color=(0, 191, 255), name="Sword",
    equippable=equippable.Sword()
)

leather_armor = Item(
    char="[",
    color=(139, 69, 19),
    name="Leather Armor",
    equippable=equippable.LeatherArmor(),
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
    char="@",
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
)

quest_giver = Actor(
    char="@",
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