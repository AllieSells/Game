from components.ai import (DarkHostileEnemy, Friendly, HostileEnemy, BaseAI, 
                           StatueAI, FollowerAI, AnimalAI, HostileCasterAI, PhasingAI, 
                           RetreatingPhasingAI, SplittingEnemyAI, NoneAI, DragonHeadAI,
                           RangedEnemyAI)
from components import equippable
from components.equipment import Equipment
from components.fighter import Fighter, Receiver
from components.inventory import Inventory
from components import consumable
from components.spells import InflictWoundsSpell
from components.level import Level
from components.container import Container
from components import effect
from components.body_parts import BodyParts, AnatomyType
from entity import Actor, Item
from render_order import RenderOrder
import sounds
from text_utils import blue, cyan, green, purple, red, white, yellow
import copy
import liquid_system
import color
import random
import colorsys
from components.damage_types import DamageType


def hue_shift(rgb_color):
    """Convert RGB to HSV and shift"""
    r, g, b = [x / 255.0 for x in rgb_color]

    h, s, v = colorsys.rgb_to_hsv(r, g, b)


    h = (h + random.uniform(0.1, 0.9)) % 1.0

    r, g, b = colorsys.hsv_to_rgb(h, s, v)

    return int(r * 255), int(g * 255), int(b * 255)



def create_hash(ingredients: list) -> Item:
    hunger_restore = 60
    if ingredients:
        for ing in ingredients:
            if "mushroom" in ing.tags:
                hunger_restore += 5
            elif "meat" in ing.tags:
                hunger_restore += 20
    import sprite_manager
    return Item(
        char=sprite_manager.compose_sprite([0xE0C6, 0xE0C9], layer_tints=[(255, 255, 255), (255, 255, 255)]),
        color=(255, 255, 255),
        name= (ingredients[0].name + " Hash") if ingredients else "Plain Hash",
        description=f"A hash bowl made from {', '.join(ing.name for ing in ingredients)}.",
        value=10,
        weight=0.5,
        consumable=consumable.FoodConsumable(saturation_restore=100, hunger_restore=hunger_restore),
        pickup_sound=sounds.play_equip_glass_sound,
        drop_sound=sounds.play_equip_glass_sound,
        equip_sound=sounds.play_equip_glass_sound,
        unequip_sound=sounds.play_unequip_glass_sound,
        tags = ["hash", "food", "consumable", "meal"]
    )


def create_stew(ingredients: list) -> Item:
    soup_color = (139, 69, 19)  # Default brown
    if ingredients:
        soup_color = (
            sum(ing.color[0] for ing in ingredients) // len(ingredients),
            sum(ing.color[1] for ing in ingredients) // len(ingredients),
            sum(ing.color[2] for ing in ingredients) // len(ingredients),
        )

        spr = None

        # Check for meat in ingredients (change sprite)
        if any("meat" in ing.tags for ing in ingredients):
            spr = 0xE0C8
            # Get first ingredient
            dispname = ingredients[0].name + " Roast"
        
        else:
            dispname = ingredients[0].name + " Stew"

        # Iterate tags to determine saturation of stew
        hunger_restore = 60
        for ing in ingredients:
            if "mushroom" in ing.tags:
                hunger_restore += 5
            elif "meat" in ing.tags:
                hunger_restore += 20


    import sprite_manager
    # Check if meat in any ingredient
    return Item(
        char=sprite_manager.compose_sprite([0xE0C6, 0xE0C7, spr], layer_tints=[(255, 255, 255), soup_color, (255, 255, 255)]),
        color=(255, 255, 255),
        name=dispname if ingredients else "Plain Stew",
        description=f"A hearty stew made from {', '.join(ing.name for ing in ingredients)}.",
        value=5,
        weight=0.5,
        consumable=consumable.FoodConsumable(saturation_restore=100, hunger_restore=hunger_restore),
        pickup_sound=sounds.play_equip_glass_sound,
        drop_sound=sounds.play_equip_glass_sound,
        equip_sound=sounds.play_equip_glass_sound,
        unequip_sound=sounds.play_unequip_glass_sound,
        tags = ["stew", "food", "consumable", "meal"]
    )

poison_potion = Item(
    char="o",
    color=color.dark_green,
    value=10,
    name="Poison Potion",
    consumable=consumable.PoisonConsumables(amount=5, duration=5),
    description="A small vial filled with a pale green liquid.",
    equip_sound=sounds.play_equip_glass_sound,
    unequip_sound=sounds.play_unequip_glass_sound,
    pickup_sound=sounds.pick_up_glass_sound,
    drop_sound=sounds.drop_glass_sound,
    rarity_color=color.poison,
    tags = ["potion", "poison", "glass", "container", "fragile"],
    liquid_type=liquid_system.LiquidType.POISON,
    liquid_amount=5,
    weight=0.5,
    unknown_name="Pale Green Potion",
    identification_level=3,
)

fire_resistance_potion = Item(
    char=chr(0xE0B8),
    value = 15,
    name = "Fire Resistance Potion",
    consumable = consumable.FireResistanceConsumable(duration=50),
    description = "A medium vial filled with an orange liquid.",
    equip_sound=sounds.play_equip_glass_sound,
    unequip_sound=sounds.play_unequip_glass_sound,
    pickup_sound=sounds.pick_up_glass_sound,
    drop_sound=sounds.drop_glass_sound,
    rarity_color=color.rare,
    tags = ["potion", "fire resistance", "glass", "container", "fragile"],
    weight=0.5,
    unknown_name="Orange Potion",
    identification_level=3,
)

lesser_health_potion = Item(
    char=chr(0xE0B0),
    color=(255, 255, 255),
    value=10,
    name="Lesser Health Potion",
    consumable=consumable.HealingConsumables(amount=8),
    description="A small vial filled with a light red liquid.",
    equip_sound=sounds.play_equip_glass_sound,
    unequip_sound=sounds.play_unequip_glass_sound,
    pickup_sound=sounds.pick_up_glass_sound,
    drop_sound=sounds.drop_glass_sound,
    rarity_color=color.common,
    tags = ["potion", "health", "glass", "container", "fragile", "lesser"],
    liquid_type=liquid_system.LiquidType.HEALTHPOTION,
    liquid_amount=8,
    weight=0.5,
    unknown_name="Light Red Potion",
    identification_level=1,
)
health_potion = Item(
    char=chr(0xE0B1),
    color=(255, 255, 255),
    value=15,
    name="Health Potion",
    consumable=consumable.HealingConsumables(amount=20),
    description="A medium vial filled with a light red liquid.",
    equip_sound=sounds.play_equip_glass_sound,
    unequip_sound=sounds.play_unequip_glass_sound,
    pickup_sound=sounds.pick_up_glass_sound,
    drop_sound=sounds.drop_glass_sound,
    rarity_color=color.uncommon,
    tags = ["potion", "health", "glass", "container", "fragile"],
    liquid_type=liquid_system.LiquidType.HEALTHPOTION,
    liquid_amount=15,
    weight=0.75,
    unknown_name="Light Red Potion",
    identification_level=3,
)

dungeon_key = Item(
    char=chr(0xE0C4),
    color=(255, 215, 0),
    value=100,
    name="Dungeon Key",
    description="A mysterious key. It looks like it could unlock the entrance.",
    pickup_sound=sounds.pickup_coin_sound,
    drop_sound=sounds.play_unequip_coin_sound,
    rarity_color=color.legendary,
    tags = ["key", "dungeon", "metal"],
    weight=0.1
)


campfire = Item(
    char=chr(0xE003),
    color=(255, 255, 255),
    name="Campfire",
    description="A small campfire providing warmth and light.",
    tags = ["fire", "campfire", "light", "wood"]
)

bonfire = Item(
    char="☼",
    color=(255, 140, 0),
    name="Bonfire",
    description="A large bonfire crackling with intense flames.",
    tags = ["fire", "bonfire", "light", "wood"]
)

torch = Item(
    char=chr(0xE0A3),
    equip_sprite_cp=0xE0A2,
    value = 1,
    color=(color.sprite_sheet),
    name="Torch",
    equippable=equippable.Torch(),
    burn_duration=600,
    description="A wooden torch that can be held to provide light.",
    pickup_sound=sounds.pick_up_wood_sound,
    drop_sound=sounds.drop_wood_sound,
    equip_sound=sounds.play_torch_pull_sound,
    unequip_sound=sounds.play_torch_extinguish_sound,
    verb_base="smash",
    verb_present="smashes",
    verb_past="smashed",
    verb_participial="smashing",
    rarity_color=color.common,
    tags = ["torch", "light", "wood", "fire"],
    weight = 1.0,
    damage_type=DamageType.FIRE
)

# Weapons

dagger = Item(
    char=chr(0xE0A1), color=(color.sprite_sheet), name="Dagger",
    value = 5,
    equippable=equippable.Dagger(),
    description="A small sharp blade.",
    pickup_sound=sounds.pick_up_blade_sound,
    drop_sound=sounds.drop_blade_sound,
    equip_sound=sounds.play_equip_blade_sound,
    unequip_sound=sounds.play_unequip_blade_sound,
    verb_base="stab",
    verb_present="stabs",
    verb_past="stabbed",
    verb_participial="stabbing",
    rarity_color=color.common,
    tags = ["dagger", "weapon", "blade", "metal", "light weapon"],
    weight=1.0,
    equip_sprite_cp=0xE0A0,
    damage_type= DamageType.PIERCING
)

mythril_dagger = Item(
    char=chr(0xE0A9),
    color=(color.sprite_sheet),
    name="Mythril Dagger",
    value = 25,
    equippable=equippable.MythrilDagger(),
    description="A dagger forged from mythril.",
    pickup_sound=sounds.pick_up_blade_sound,
    drop_sound=sounds.drop_blade_sound,
    equip_sound=sounds.play_equip_blade_sound,
    unequip_sound=sounds.play_unequip_blade_sound,
    verb_base="stab",
    verb_present="stabs",
    verb_past="stabbed",
    verb_participial="stabbing",
    rarity_color=color.rare,
    tags = ["mythril dagger", "dagger", "weapon", "blade", "metal", "light weapon"],
    weight=1.0,
    equip_sprite_cp=0xE0A8,
    damage_type=DamageType.PIERCING
)

shortsword = Item(
    char=chr(0xE0A5),
    equip_sprite_cp=0xE0A4,
    color=(color.sprite_sheet),
    name="Shortsword",
    value = 15, 
    equippable=equippable.Shortsword(),
    description="A short, single-handed sword.",
    pickup_sound=sounds.pick_up_blade_sound,
    drop_sound=sounds.drop_blade_sound,
    equip_sound=sounds.play_equip_blade_sound,
    unequip_sound=sounds.play_unequip_blade_sound,
    verb_base="slash",
    verb_present="slashes",
    verb_past="slashed",
    verb_participial="slashing",
    rarity_color=color.common,
    tags = ["shortsword", "sword", "weapon", "blade", "metal"],
    weight=2.0,
    damage_type=DamageType.SLASHING
)

longsword = Item(
    char=chr(0xE0A7),
    equip_sprite_cp=0xE0A6, 
    name="Longsword",
    equippable=equippable.Longsword(),
    description="A long, double-handed sword.",
    value = 20,
    pickup_sound=sounds.pick_up_blade_sound,
    drop_sound=sounds.drop_blade_sound,
    equip_sound=sounds.play_equip_blade_sound,
    unequip_sound=sounds.play_unequip_blade_sound,
    verb_base="slash",
    verb_present="slashes",
    verb_past="slashed",
    verb_participial="slashing",
    rarity_color=color.uncommon,
    tags = ["longsword", "sword", "weapon", "blade", "metal", "heavy weapon"],
    weight=4.0,
    damage_type=DamageType.SLASHING
)



bow = Item(
    char=chr(0xE0AB),
    equip_sprite_cp=0xE0AA,
    color=color.sprite_sheet,
    name="Bow",
    equippable=equippable.Bow(),
    description="A simple wooden bow.",
    value = 20,
    pickup_sound=sounds.pick_up_wood_sound,
    drop_sound=sounds.drop_wood_sound,
    equip_sound=sounds.pick_up_wood_sound, # Place holder
    unequip_sound=sounds.drop_wood_sound, # Place holder
    verb_base="shoot",
    verb_present="shoots",
    verb_past="shot",
    verb_participial="shooting",
    rarity_color=color.common,
    tags = ["bow", "weapon", "ranged", "wood"],
    weight=2.0,
    damage_type=DamageType.BLUDGEONING
)

arrow = Item(
    char=chr(0xE0AC),
    color=color.sprite_sheet,
    name="Stone Arrow",
    value = 1,
    equippable=equippable.Arrow(),
    description="A simple wooden arrow, held in the offhand or quiver.",
    pickup_sound=sounds.pick_up_wood_sound,
    drop_sound=sounds.drop_wood_sound,
    equip_sound=sounds.pick_up_wood_sound, # Place holder
    unequip_sound=sounds.drop_wood_sound, # Place holder
    verb_base="shoot",
    verb_present="shoots",
    verb_past="shot",
    verb_participial="shooting",
    rarity_color=color.common,
    tags = ["arrow", "ammunition", "ammo", "ranged", "wood"],
    weight=0.05,
    damage_type=DamageType.PIERCING
)

steel_arrow = Item(
    char=chr(0xE0AD),
    color=color.sprite_sheet,
    name="Steel Arrow",
    value = 3,
    equippable=equippable.SteelArrow(),
    description="A steel arrow, sharper than a wooden one.",
    pickup_sound=sounds.play_plate_sound,
    drop_sound=sounds.play_plate_sound,
    equip_sound=sounds.play_plate_sound,
    unequip_sound=sounds.play_plate_sound,
    verb_base="shoot",
    verb_present="shoots",
    verb_past="shot",
    verb_participial="shooting",
    rarity_color=color.uncommon,
    tags = ["steel arrow", "arrow", "ammunition", "ammo", "ranged", "metal"],
    weight=0.1,
    damage_type=DamageType.PIERCING
)


leather_cap = Item(
    char=chr(0xE070),
    color=color.sprite_sheet,
    name="Leather Cap",
    equippable=equippable.LeatherCap(),
    value = 5,
    description="A simple leather cap.",
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.pick_up_leather_sound,
    drop_sound=sounds.drop_leather_sound,
    rarity_color=color.common,
    tags = ["leather", "armor", "headgear", 'light armor'],
    weight=0.5,
    equip_sprite_cp=0xE080
)

leather_armor = Item(
    char=chr(0xE071),
    color=color.sprite_sheet,
    name="Leather Armor",
    equippable=equippable.LeatherArmor(),
    description="A simple chestpiece offering basic protection.",
    value = 15,
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.pick_up_leather_sound,
    drop_sound=sounds.drop_leather_sound,
    rarity_color=color.common,
    tags = ["leather", "armor", "body armor", "light armor"],
    weight=5.0,
    equip_sprite_cp=0xE081
)

leather_leggings = Item(
    char=chr(0xE072),
    color=color.sprite_sheet,
    name="Leather Leggings",
    value = 10,
    equippable=equippable.LeatherLeggings(),
    description="A simple pair of leg protection.",
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.pick_up_leather_sound,
    drop_sound=sounds.drop_leather_sound,
    rarity_color=color.common,
    tags = ["leather", "armor", "leggings", "light armor"],
    weight=3.0,
    equip_sprite_cp=0xE082
)

leather_boot = Item(
    char=chr(0xE073),
    color=color.sprite_sheet,
    name="Leather Boots",
    equippable=equippable.LeatherBoot(),
    description="A simple pair of boots offering basic foot protection.",
    value = 10,
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.pick_up_leather_sound,
    drop_sound=sounds.drop_leather_sound,
    rarity_color=color.common,
    tags = ["leather", "armor", "boots", "light armor"],
    weight=1.0,
    equip_sprite_cp=0xE083
)


chain_mail_helmet = Item(
    char=chr(0xE074), color=(color.sprite_sheet),
    name="Mail Coif",
    equippable=equippable.ChainMailHelmet(),
    description="A flexible hood of interlocking metal rings.",
    value = 10,
    equip_sound=sounds.play_chain_sound,
    unequip_sound=sounds.play_chain_sound,
    pickup_sound=sounds.play_chain_sound,
    drop_sound=sounds.play_chain_sound,
    rarity_color=color.uncommon,
    tags = ["chain mail", "armor", "headgear", "medium armor"],
    weight=2.0,
    equip_sprite_cp=0xE084
)

chain_mail_armor = Item(
    char=chr(0xE075),
    color=(color.sprite_sheet),
    equippable=equippable.ChainMailArmor(),
    name="Chain Mail Shirt",
    description="A shirt of interlocking metal rings.",
    value = 30,
    equip_sound=sounds.play_chain_sound,
    unequip_sound=sounds.play_chain_sound,
    pickup_sound=sounds.play_chain_sound,
    drop_sound=sounds.play_chain_sound,
    rarity_color=color.uncommon,
    tags = ["chain mail", "armor", "body armor", "medium armor"],
    weight=10.0,
    equip_sprite_cp=0xE085
)

chain_mail_leggings = Item(
    char=chr(0xE076),
    color=(color.sprite_sheet),
    equippable=equippable.ChainMailLeggings(),
    name="Chain Mail Leggings",
    description="A pair of leggings made from interlocking metal rings.",
    value = 20,
    equip_sound=sounds.play_chain_sound,
    unequip_sound=sounds.play_chain_sound,
    pickup_sound=sounds.play_chain_sound,
    drop_sound=sounds.play_chain_sound,
    rarity_color=color.uncommon,
    tags = ["chain mail", "armor", "leggings", "medium armor"],
    weight=5.0,
    equip_sprite_cp=0xE086
)

plate_helmet = Item(
    char=chr(0xE077),
    color=(color.sprite_sheet),
    equippable=equippable.PlateHelmet(),
    name="Plate Helmet",
    description="A solid helmet forged from pieces of metal.",
    value = 50,
    equip_sound=sounds.play_plate_sound,
    unequip_sound = sounds.play_plate_sound,
    pickup_sound=sounds.play_plate_sound,
    drop_sound=sounds.play_plate_sound,
    rarity_color=color.rare,
    tags = ["plate", "armor", "headgear", "heavy armor"],
    weight=5.0,
    equip_sprite_cp=0xE087
)

plate_armor = Item(
    char=chr(0xE078),
    color=(color.sprite_sheet),
    equippable=equippable.PlateArmor(),
    name="Plate Armor",
    description="Solid armor forged from pieces of metal.",
    value = 100,
    equip_sound=sounds.play_plate_sound,
    unequip_sound=sounds.play_plate_sound,
    pickup_sound=sounds.play_plate_sound,
    drop_sound=sounds.play_plate_sound,
    rarity_color=color.rare,
    tags = ["plate", "armor", "body armor", "heavy armor"],
    weight=20.0,
    equip_sprite_cp=0xE088
)

apprentice_robe = Item(
    char=chr(0xE079),
    color=(color.sprite_sheet),
    equippable=equippable.ApprenticeRobe(),
    name="Apprentice Robe",
    description="A robe worn by mage apprentices.",
    value = 20,
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.play_equip_leather_sound,
    drop_sound=sounds.play_unequip_leather_sound,
    rarity_color=color.uncommon,
    tags = ["robe", "light armor"],
    weight=3.0,
    equip_sprite_cp=0xE089
)

scholar_robe = Item(
    char=chr(0xE07A),
    color=(color.sprite_sheet),
    equippable=equippable.ScholarRobe(),
    name="Scholar Robe",
    description="A robe worn by learned mages.",
    value = 40,
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.play_equip_leather_sound,
    drop_sound=sounds.play_unequip_leather_sound,
    rarity_color=color.rare,
    tags = ["robe", "light armor"],
    weight=4.0,
    equip_sprite_cp=0xE08A
)

master_robe = Item(
    char=chr(0xE07B),
    color=(color.sprite_sheet),
    equippable=equippable.MasterRobe(),
    name="Master Robe",
    description="A robe worn by master mages.",
    value = 80,
    equip_sound=sounds.play_equip_leather_sound,
    unequip_sound=sounds.play_unequip_leather_sound,
    pickup_sound=sounds.play_equip_leather_sound,
    drop_sound=sounds.play_unequip_leather_sound,
    rarity_color=color.legendary,
    tags = ["robe", "light armor"],
    weight=5.0,
    equip_sprite_cp=0xE08B
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

quiver = Item(
    char=chr(0xE0AE),
    color=(color.sprite_sheet),
    name="Quiver",
    equippable=equippable.Quiver(),
    description="A back-worn quiver that stores arrows for bow attacks.",
    value=12,
    tags=["quiver", "ammunition"],
    weight=1.0,
)
quiver.arrow_count = 20
quiver.arrow_capacity = 60
quiver.ammo_counts = {"arrow": 20}
quiver.selected_ammo_type = "arrow"

coin = Item(
    char=chr(0xE0C0),
    color=(255, 223, 0),
    name="Coin",
    description="A shiny gold coin.",
    value=1,
    weight=0.01,
    rarity_color=color.coins,
)

fungus = Item(
    char="%",
    color=(0, 255, 0),
    name="Fungus",
    description="",
)



test_ring = Item(
    char=chr(0xE0AF),
    color=(255, 0, 255),
    name="Test Ring",
    equippable=equippable.Ring(),
    description="You feel like you shouldn't see this item",
    value=999,
    pickup_sound=sounds.pick_up_coin_sound,
    drop_sound=sounds.pick_up_coin_sound,
    equip_sound=sounds.pick_up_coin_sound,
    unequip_sound=sounds.pick_up_coin_sound,
)



# =====================================================
# FUNCTIONS
# =====================================================

def create_illusion(source: Actor) -> Actor:
    illusion = copy.deepcopy(source)
    if illusion.is_player:
        illusion.name = f"Image of {source.name}"
        illusion.color = (0, 230, 230)
    
    # Make it NOT the player so enemies can target it
    illusion.is_player = False
    illusion.is_decoy = True  # Flag for enemy AI to recognize as decoy
    
    # Create new components and set their parent
    illusion.fighter = Fighter(hp=1, base_defense=0, base_power=0, leave_corpse=False, can_bleed=False)
    illusion.fighter.parent = illusion

    illusion.ai = FollowerAI(illusion, target=source)
    illusion.ai.parent = illusion
    
    illusion.body_parts = BodyParts(AnatomyType.SIMPLE, max_hp = 1)
    illusion.body_parts.parent = illusion

    illusion.blocks_movement = False  # Player can walk through illusions
    
    return illusion


def get_scroll(spell_name: str) -> Item:
    import sprite_manager
    key = str(spell_name or "").strip().lower()
    scroll_specs = {
        "fireball": ((255, 69, 0), lambda: consumable.FireballConsumable(damage=15, radius=2)),
        "lightning": ((255, 255, 0), lambda: consumable.LightningConsumable(damage=20, maximum_range=5)),
        "darkvision": ((128, 0, 128), lambda: consumable.DarkvisionConsumable(duration=10)),
        "confusion": ((0, 255, 255), lambda: consumable.ConfusionConsumable(duration=5)),
    }
    if key not in scroll_specs:
        raise ValueError(f"Unknown scroll spell: {spell_name!r}")

    tint, consumable_factory = scroll_specs[key]
    scroll = Item(
        char = sprite_manager.compose_sprite([0xE0B4, 0xE0B5], layer_tints=[None, tint]),
        color=(color.sprite_sheet),
        name = f"Scroll of {key.title()}",
        description = "A tattered fabric inscribed with arcane symbols.",
        value = 20,
        consumable=consumable_factory(),
        pickup_sound=sounds.pick_up_paper_sound,
        drop_sound=sounds.drop_paper_sound,
        equip_sound=sounds.play_equip_paper_sound,
        unequip_sound=sounds.play_unequip_paper_sound,
        rarity_color=color.uncommon,
        tags = ["scroll", "consumable", "paper", key],
    )
    pass_scroll = copy.deepcopy(scroll)
    return pass_scroll


# Lazy getters for scrolls - these create fresh instances on demand
def get_darkvision_scroll() -> Item:
    return get_scroll("darkvision")

def get_confusion_scroll() -> Item:
    return get_scroll("confusion")

def get_fireball_scroll() -> Item:
    return get_scroll("fireball")

def get_lightning_scroll() -> Item:
    return get_scroll("lightning")

# For backward compatibility - these are now callables
darkvision_scroll = get_darkvision_scroll
confusion_scroll = get_confusion_scroll
fireball_scroll = get_fireball_scroll
lightning_scroll = get_lightning_scroll


def get_ring(
    effect_type: type[effect.Effect] | None = None,
    cooldown: int | None = None,
    duration: int | None = None,
) -> Item:
    """Create a ring that periodically applies an effect while equipped.

    Args:
        effect_type: Effect class to bind to the ring. Random when None.
        cooldown: Optional turns between applications. If None, a sensible
            default is selected per effect.
        duration: Optional effect duration. If None, a default is used.
    """
    possible_effects = [effect.InvisibilityEffect, effect.DarkvisionEffect, effect.LightEffect, effect.FireResistanceEffect]
    effect_cls = effect_type or random.choice(possible_effects)

    default_durations = {
        effect.InvisibilityEffect: 6,
        effect.DarkvisionEffect: 20,
        effect.FireResistanceEffect: 20,
    }
    default_cooldowns = {
        effect.InvisibilityEffect: 18,  # Keeps stealth strong but not permanent.
        effect.DarkvisionEffect: 0,
        effect.FireResistanceEffect: 20,
    }
    names = {
        effect.InvisibilityEffect: "Invisibility",
        effect.DarkvisionEffect: "Darkvision",
        effect.LightEffect: "Light",
        effect.FireResistanceEffect: "Fire Resistance",
    }

    effect_duration = default_durations.get(effect_cls, 10) if duration is None else int(duration)
    effect_cooldown = default_cooldowns.get(effect_cls, 0) if cooldown is None else max(0, int(cooldown))
    ring_name = names.get(effect_cls, effect_cls.__name__.replace("Effect", ""))

    return Item(
        char=chr(0xE0AF),
        color=(color.sprite_sheet),
        name=f"Ring of {ring_name}",
        equippable=equippable.Ring(
            effect=effect_cls,
            effect_cooldown=effect_cooldown,
            effect_duration=effect_duration,
        ),
        description=(
            f"A ring that periodically grants {ring_name}. "
            f"Cooldown: {effect_cooldown} turns."
        ),
        value=120,
        pickup_sound=sounds.pick_up_coin_sound,
        drop_sound=sounds.pick_up_coin_sound,
        equip_sound=sounds.pick_up_coin_sound,
        unequip_sound=sounds.pick_up_coin_sound,
        rarity_color=color.rare,
        tags=["ring", "jewelry", "magic"],
        weight=0.1,
    )


# Deterministic ring refs for profession starting kits.
ring_of_darkvision = get_ring(effect_type=effect.DarkvisionEffect, cooldown=0, duration=20)



def spawn_phase_spider() -> Actor:
    """Factory function to spawn a Phase Spider with initial phasing effect.
    
    Creates a deep copy of the base phase_spider template and applies the
    invisibility effect to simulate phasing. This keeps the phasing behavior
    modular and reusable.
    
    Returns:
        A Phase Spider actor with active phasing effect ready for combat.
    """
    spider = copy.deepcopy(phase_spider)
    spider.ai = PhasingAI(spider)
    
    # Import here to avoid circular imports
    from components.ai import apply_phasing_effect
    
    # Apply initial phasing effect (long duration to stay hidden while approaching)
    apply_phasing_effect(spider, duration=999)
    
    return spider


def spawn_retreating_phase_spider(retreat_distance: int = 4) -> Actor:
    """Factory function to spawn a Phase Spider with retreat tactics.
    
    Variant that attacks then retreats and re-phases. Easy to customize.
    
    Args:
        retreat_distance: How far the spider moves away after attacking (default 4)
        
    Returns:
        A Phase Spider actor with RetreatingPhasingAI and initial phasing effect.
    """
    spider = copy.deepcopy(phase_spider)
    spider.ai = RetreatingPhasingAI(spider)  # Swap to retreating AI
    spider.ai.retreat_distance = retreat_distance  # Customize retreat behavior
    
    # Import here to avoid circular imports
    from components.ai import apply_phasing_effect
    
    # Apply initial phasing effect
    apply_phasing_effect(spider, duration=999)
    
    return spider


def get_bread(type: str) -> Item:
    if type == "Moldy":
        sprite = chr(0xE0CB)
        hunger_restore = 20
        saturation_restore = 5
    else:
        hunger_restore = 30
        saturation_restore = 10
        sprite = chr(0xE0CC)

    bread = Item(
        char=sprite,
        color=(255, 255, 255),
        name=f"{type} Bread",
        description=f"A piece of {type} bread.",
        value=5,
        weight=0.5,
        consumable=consumable.FoodConsumable(saturation_restore=saturation_restore, hunger_restore=hunger_restore),
        pickup_sound=sounds.play_vegetation_sound,
        drop_sound=sounds.play_vegetation_sound,
        equip_sound=sounds.play_vegetation_sound,
        unequip_sound=sounds.play_vegetation_sound,
        tags = ["bread", "ingredient", "food"]
    )
    return bread

def get_meat(type: str, hp: int) -> Item:
    """Generates meat corresponding to slain creature"""
    meat_amount = max(1, hp // 5)
    if "spider" in type.lower():
        sprite = chr(0xE0CA)
    else:
        sprite = chr(0xE0C5)
    meat = Item(
        char=sprite,
        color=(255, 255, 255),
        name=f"{type} Meat",
        description=f"Cut from a {type}.",
        value=meat_amount,
        weight=meat_amount * 0.1,
        pickup_sound=sounds.play_meat_sound,
        drop_sound=sounds.play_meat_sound,
        equip_sound=sounds.play_meat_sound,
        unequip_sound=sounds.play_meat_sound,
        tags = ["meat", "ingredient"]
    )
    return meat

def generate_spellbook() -> Item:
    spell_entries = consumable.get_spellbook_entries()
    if not spell_entries:
        raise ValueError("No spell entries available for spellbook generation.")

    spell_entry = random.choice(spell_entries)
    spell_name = spell_entry["name"]
    #spell_name = "Fireball" # Debug setter
    
    # After changing spell_name, look up the correct entry for that spell
    spell_entry = next((e for e in spell_entries if e["name"].lower() == spell_name.lower()), spell_entry)
    
    desc = spell_entry["description"] or "An ancient tome of arcane knowledge."
    item_color = spell_entry["color"]
    import sprite_manager as _sm
    _item = Item(
        char = _sm.compose_sprite([0xE0B6, 0xE0B7], layer_tints=[None, item_color]),
        color=(color.sprite_sheet),
        name=f"{spell_name} Spell Tome",
        description=desc,
        value=30,
        consumable=consumable.SpellbookConsumable(unlock_name=spell_name),
        pickup_sound=sounds.pick_up_paper_sound,
        drop_sound=sounds.drop_paper_sound,
        equip_sound=sounds.play_equip_paper_sound,
        unequip_sound=sounds.play_unequip_paper_sound,
        rarity_color=color.uncommon,
        tags = ["spellbook", "consumable", "paper", spell_name],
        weight=0.5
    )
    pass_book = copy.deepcopy(_item)
    return pass_book




def get_random_potion() -> Item:
    # Use current random state
    potion_types = [poison_potion, lesser_health_potion, health_potion]
    return random.choice(potion_types)

def get_random_scroll() -> Item:
    # Use current random state
    scroll_types = ["darkvision", "confusion", "fireball", "lightning"]
    return get_scroll(random.choice(scroll_types))

def get_random_fungus() -> Item:
    # Use current random state
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
    elif "Blood" in prefix:
        color = (255, max(color[1]-100, 75), max(color[2]-100, 75))

    elif "Green" in prefix:
        color = (max(color[0]-50, 75), 255, max(color[2]-50, 75))
    elif "Yellow" in prefix:
        color = (255, 255, max(color[2]-100, 75))
    elif "Purple" in prefix:
        color = (255, max(color[1]-100, 75), 255)
    elif "Black" in prefix:
        color = (60, 60, 60)
    elif "White" in prefix:
        color = (255, 255, 255)

    if "cap" in suffix or "cup" in suffix or "-agaric" in suffix or "puff" in suffix:
        char = random.choice([chr(0xE100), chr(0xE101), chr(0xE102), chr(0xE103), chr(0xE104), chr(0xE105), chr(0xE106), chr(0xE107)])
    else:
        char = random.choice([chr(0xE108), chr(0xE109), chr(0xE10A), chr(0xE10B), chr(0xE10C), chr(0xE10D), chr(0xE10E), chr(0xE10F)])
    if name == "Capcap":
        name = blue("L")+red("e")+green("g")+yellow("e")+purple("n")+white("d")+green("a")+cyan("r")+red("y") + " " + purple("C")+yellow("a")+white("p")+cyan("c")+purple("a")+green("p")
        
    
    return Item(
        char=char,
        color=color,
        name=name,
        description=description,
        value=1,
        weight=0.1,
        tags = ["mushroom", "ingredient"],
        consumable=consumable.FoodConsumable(saturation_restore=5),
        pickup_sound=sounds.play_vegetation_sound,
        drop_sound=sounds.play_vegetation_sound,
        equip_sound=sounds.play_vegetation_sound,
        unequip_sound=sounds.play_vegetation_sound,
    )

def get_random_coins(min_amount: int, max_amount: int) -> Item:
    amount = random.randint(min_amount, max_amount)
    character = None
    if amount == 1:
        character = chr(0xE0C0)
        def_name = "Coin (1)"
        def_description = "A shiny gold coin."
    else:
        character = random.choice([chr(0xE0C1), chr(0xE0C2), chr(0xE0C3)])
        def_name = "Pile of Coins (" + str(amount) + ")"
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
        char=character,
        color=(255, 223, 0),    
        name=def_name,
        description=def_description,
        value=amount,
        weight=0.01 * amount,
        equip_sound=def_equip_sound,
        unequip_sound=def_unequip_sound,
        pickup_sound=def_pickup_sound,
        drop_sound=def_drop_sound,
        rarity_color=color.coins
    )

# =====================================================
# EQUIPMENT GENERATORS
# =====================================================

    





# Attach a Container component to a chest template (not an Actor constructor arg
# since the Actor expects certain component types). We'll create a light-weight
# chest_entity factory that will 'spawn' and then attach a Container to it when
# placed on the map via code elsewhere.
def make_chest_with_loot(items: list, capacity: int = 10) -> Actor:
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

basic_entity_levelling = Level(
    level_up_base=50
)

def create_levelling_with_traits(**trait_levels):
    """Create a Level instance with custom trait levels.
    
    Example:
        level=create_levelling_with_traits(agility=3, strength=2)
    """
    lvl = copy.deepcopy(basic_entity_levelling)
    for trait_name, level_value in trait_levels.items():
        if trait_name in lvl.traits:
            lvl.traits[trait_name]['level'] = level_value
    return lvl



# =====================================================
# ACTORS - All actor definitions grouped together
# =====================================================



player = Actor(
    char=chr(0xE030),
    travel_char = chr(0xE03B),
    color=(255, 255, 255),
    name = "Player",
    is_player=True,
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=30, base_defense=2, base_power=5),
    inventory=Inventory(capacity=26),
    level=copy.deepcopy(basic_entity_levelling),
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=30),
    speed=100,  # Base speed
    # Temporary demo effect so the status-effects panel shows during testing
    effects = [],
    lucidity = 100,
    max_lucidity = 100,
    hunger = 100.0,
    dodge_chance=0.15,  # 15% chance to dodge attacks
    preferred_dodge_direction="north",  # Tendency to dodge towards the north (for flavor)
)



giant_spider = Actor(
    char=chr(0xE032),
    color=(color.sprite_sheet),
    name = "Giant Spider",
    description="A large arachnid",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=3),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=120,  # Faster than player to make them more threatening
    body_parts=BodyParts(AnatomyType.ARACHNID, max_hp=10),
    verb_base="bite",
    verb_present="bites",
    verb_past="bit",
    verb_participial="biting",
    dodge_chance=0.10,  # 10% chance to dodge attacks
    damage_resistances=[
        (DamageType.POISON, 0.0),
        (DamageType.FIRE, 2.0),
        (DamageType.PSYCHIC, 0.0)
    ],
    equipment_table={
        "meat": {
            get_meat("Spider", 10): 100,
        },
        "potion": {
            poison_potion: 20,
            None: 80
        }
    
    }
)



kobold = Actor(
    char= chr(0xE033),
    color = color.sprite_sheet,
    name = "Kobold",
    description="A small reptillian humanoid, commonly found in caves.",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=6, base_defense=0, base_power=5),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=150,
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=6),
    verb_base="scratch",
    verb_present="scratches",
    verb_past="scratched",
    verb_participial="scratching",
    dodge_chance=0.10, 
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
    level=copy.deepcopy(basic_entity_levelling),
    speed=130,  # Very fast - supernatural creature
    opinion=0,
)

gelatinous_cube = Actor(
    char=chr(0xE044),
    color=(color.sprite_sheet),
    name="Gelatinous Cube",
    ai_cls=SplittingEnemyAI,
    equipment=Equipment(),
    fighter=Fighter(hp=50, base_defense=1, base_power=10, can_bleed=False, leave_corpse=False),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=50,
    body_parts=BodyParts(AnatomyType.SIMPLE, max_hp=40),
    verb_base="ooze",
    verb_present="oozes",
    verb_past="oozed",
    verb_participial="oozing",
    dodge_chance=0.05,
    equipment_table={},
)

goblin_archer = Actor(
    char=chr(0xE04A),
    color=(color.sprite_sheet),
    name = "Goblin Archer",
    ai_cls=RangedEnemyAI,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=6),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=110,
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=10),
    verb_base="shoot",
    verb_present="shoots",
    verb_past="shot",
    verb_participial="shooting",
    dodge_chance=0.10,
)

goblin = Actor(
    char=chr(0xE031),
    color=(255, 255, 255),
    name = "Goblin",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=6),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=110,  # Fast enough to sometimes act before player
    equipment_scale=0.75,
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=10),
    description="",
    verb_base="claw",
    verb_present="claws",
    verb_past="clawed",
    verb_participial="clawing",
    dodge_chance=0.15, 
    equipment_table={
        "coins": {
            get_random_coins(1,5): 30,
            None: 70

        },
        "potion": {
            lesser_health_potion: 10,
            None: 90
        },
        "weapon": {
            dagger: 20,
            None: 80
        },
        "head_armor": {
            leather_cap: 25,
            None: 75
        },
        "chest_armor": {
            leather_armor: 25,
            None: 75
        },
        'leg_armor': {
            leather_leggings: 25,
            None: 75
        },
        'foot_armor': {
            leather_boot: 25,
            None: 75
        },
        'bag': {
            get_bread("Moldy"): 50,
            None: 50
        }
    }
)



naga = Actor(
    char=chr(0xE037),
    color=(hue_shift(color.sprite_sheet)),
    name="Naga",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=25, base_defense=1, base_power=10),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=70,
    body_parts=BodyParts(AnatomyType.SNAKE, max_hp=25),
    verb_base="strike",
    verb_present="strikes",
    verb_past="struck",
    verb_participial="striking",
    dodge_chance=0.25,
    damage_resistances=[
        (DamageType.POISON, 0.0),
    ],
    equipment_table={
        "potion": {
            get_random_potion(): 15,
            None: 85
        }
    }
)
troll = Actor(
    char=chr(0xE034),
    color=(color.sprite_sheet),
    name="Troll",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=24, base_defense=1, base_power=8),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=80,
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=24),
    verb_base="smash",
    verb_present="smashes",
    verb_past="smashed",
    verb_participial="smashing",
    dodge_chance=0.05,
    equipment_table={
        "weapon": {
            dagger: 5,
            None: 95
        }
    }
)

dummy = Actor(
    char=chr(0xE036),
    color= (203, 123, 160),
    name="ERR",
    description="You feel like you shouldn't be seeing this...",
    ai_cls=BaseAI,
    equipment=Equipment(),
    fighter=Fighter(hp=9999999, base_defense=0, base_power=0, can_bleed=False, leave_corpse=False),
    inventory=Inventory(capacity=0),
    level=None,
    sentient=False,
)

ogre = Actor(
    char=chr(0xE03F),
    color=(color.sprite_sheet),
    name="Ogre",
    description="A brutish humanoid",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=30, base_defense=2, base_power=12),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=60,
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=30),
    verb_base="smash",
    verb_present="smashes",
    verb_past="smashed",
    verb_participial="smashing",
    dodge_chance=0.05,
    equipment_table={
        "weapon": {
            dagger: 10,
            None: 90
        },
        "potion": {
            get_random_potion(): 10,
            None: 90
        }
    }
)

phase_spider = Actor(
    char=chr(0xE043),
    color=(color.sprite_sheet),
    name="Phase Spider",
    description="A large, extra-dimensional arachnid that phases in and out of reality, striking from invisibility.",
    ai_cls=RetreatingPhasingAI,
    equipment=Equipment(),
    fighter=Fighter(hp=15, base_defense=2, base_power=6),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=120,
    body_parts=BodyParts(AnatomyType.ARACHNID, max_hp=15),
    verb_base="bite",
    verb_present="bites",
    verb_past="bit",
    verb_participial="biting",
    dodge_chance=0.10,
    equipment_table=None,
    damage_resistances=[
        (DamageType.POISON, 0.0),
    ]
)

# =====================================================
# MULTI-PART BOSS - Stone Colossus
# =====================================================

def create_dragon(gamemap, x: int, y: int) -> Actor:
    dragon = Actor(
        char=chr(0xE049),
        color=(color.sprite_sheet),
        name="Dragon",
        description="A powerful and magical creature.",
        ai_cls=HostileEnemy,
        equipment=Equipment(),
        fighter=Fighter(hp=200, base_defense=5, base_power=20),
        inventory=Inventory(capacity=0),
        level=copy.deepcopy(basic_entity_levelling),
        speed=100,  # Slow but powerful
        body_parts=BodyParts(AnatomyType.DRAGON, max_hp=200),
        verb_base="slash",
        verb_present="slashes",
        verb_past="slashed",
        verb_participial="slashing",
        dodge_chance=0.0,  # Too large to dodge
        base_hit_chance=1.2,  # High accuracy due to massive attacks
        evasion=0.1,  # Easy to hit due to size
        damage_resistances=[
            (DamageType.PHYSICAL, 0.5),  # 50% physical resistance
            (DamageType.FIRE, 0.0),     # Immune to fire
        ]
    )
    
    # Spawn the main entity (legs at ground level)
    dragon.x = x
    dragon.y = y
    dragon.parent = gamemap
    gamemap.entities.add(dragon)
    
    # Create the top part (head/upper body)
    top_part = Actor(
        char=chr(0xE048),
        color=(color.sprite_sheet),
        name="Dragon",
        description="A powerful and magical creature",
        ai_cls=DragonHeadAI,  # Head can cast spells independently
        equipment=Equipment(),
        fighter=Fighter(hp=200, base_defense=5, base_power=20, leave_corpse=False, can_bleed=False),
        inventory=Inventory(capacity=0),
        level=None,
        speed=100,
        body_parts=None,
        dodge_chance=0.0,
        mana=100,  # Give head mana to cast spells
        mana_max=100,
    )
    
    # Link the fighter components so damage to either part affects the same HP pool
    top_part.fighter = dragon.fighter
    
    # Spawn the top part
    top_part.x = x
    top_part.y = y - 1  # One tile above the legs
    top_part.parent = gamemap
    gamemap.entities.add(top_part)
    
    # Link the parts together
    dragon.child_parts.append(top_part)
    top_part.parent_entity = dragon
    
    return dragon


lunatic_mage = Actor(
    char=chr(0xE040),
    color=(color.sprite_sheet),
    name="Lunatic Mage",
    description="A mage driven mad by the influence of the sigil stone.",
    ai_cls=HostileCasterAI,
    equipment=Equipment(),
    fighter=Fighter(hp=15, base_defense=0, base_power=4),
    inventory=Inventory(capacity=5),
    level=copy.deepcopy(basic_entity_levelling),
    speed=100,
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=15),
    verb_base="strike",
    verb_present="strikes",
    verb_past="struck",
    verb_participial="striking",
    dodge_chance=0.10,
    equipment_table={
        "tome": {
            generate_spellbook: 30,  # Callable - will generate fresh tome each spawn
            None: 70
        }
    },
    known_spells=[InflictWoundsSpell()],
    mana=20,
    mana_max=20,
    damage_resistances=[
        (DamageType.PSYCHIC, 0.0),
    ]
    
)
lunatic_mage.level.traits["arcana"]["level"] = 3
lunatic_mage.level.traits["necromancy"]["level"] = 3
lunatic_mage.level.resync_derived_stats()

animated_armor = Actor(
    char=chr(0xE039),
    color=(color.sprite_sheet),
    name="Animated Armor",
    description="A suit of possessed armor.",
    ai_cls=HostileEnemy,
    equipment=Equipment(),
    fighter=Fighter(hp=20, base_defense=4, base_power=6, can_bleed=False, leave_corpse=False),
    inventory=Inventory(capacity=0),
    level=copy.deepcopy(basic_entity_levelling),
    speed=50,
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=20),
    verb_base="slash",
    verb_present="slashes",
    verb_past="slashed",
    verb_participial="slashing",
    dodge_chance=0.10,
    equipment_table= None,
    damage_resistances=[
        (DamageType.PHYSICAL, 0.5),
        (DamageType.FIRE, 0.0),
        (DamageType.POISON, 0.0),
        (DamageType.PSYCHIC, 0.0),
    ]
)

rat = Actor(
    char=chr(0xE03E),
    color=(color.sprite_sheet),
    name="Rat",
    description="A wretched vermin.",
    ai_cls=AnimalAI,
    equipment=Equipment(),
    fighter=Fighter(hp=3, base_defense=0, base_power=1),
    inventory=Inventory(capacity=5),
    level=copy.deepcopy(basic_entity_levelling),
    speed=90,
    body_parts=BodyParts(AnatomyType.QUADRUPED, max_hp=3),
    verb_base="bite",
    verb_present="bites",
    verb_past="bit",
    verb_participial="biting",
    dodge_chance=0.05,
    equipment_table={
        "meat": {
            get_meat("Rat", 3): 100
        }
    },
    harvestable=True,
)


        

statue = Actor(
    char=chr(0xE038),
    color=(color.sprite_sheet),
    name="Statue",
    description="A statue, worn by time.",
    ai_cls=StatueAI,
    equipment=Equipment(),
    fighter=Fighter(hp=999999999, base_defense=999, base_power=0, can_bleed=False, leave_corpse=False),
    inventory=Inventory(capacity=0),
    level=Level(xp_given=0),
    sentient=False,
    is_known=True,
    type = "Statue",
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=999999999),
)

chest = Actor(
    char=chr(0xE002),
    color=(222, 153, 52),
    name="Chest",
    # No AI for static container
    ai_cls=None,
    equipment=None,
    fighter=None,
    inventory=Inventory(capacity=0),
    level=Level(xp_given=0),
)

oil_barrel = Actor(
    char=chr(0xE046),
    color=(color.sprite_sheet),
    name="Oil Barrel",
    description="A barrel filled with flammable oil.",
    ai_cls=NoneAI,
    equipment=None,
    fighter=Receiver(hp=3, base_defense=0, base_power=0, can_bleed=False, leave_corpse=False),
    inventory=Inventory(capacity=0),
    level=Level(xp_given=0),
    body_parts=BodyParts(AnatomyType.OBJECT, max_hp=3),
)

altar = Actor(
    char="=",
    color = (150, 0, 150),
    name = "Altar",
    ai_cls=None,
    equipment=None,
    fighter=None,
    inventory=Inventory(capacity=0),
    level=Level(xp_given=0),
)

training_dummy = Actor(
    char=chr(0xE036),
    color=(255, 255, 255),
    name="Training Dummy",
    ai_cls=BaseAI,
    equipment=Equipment(),
    fighter=Fighter(hp=30, base_defense=0, base_power=0, can_bleed=False, leave_corpse=False),
    inventory=Inventory(capacity=0),
    level=None,
    sentient=False,
    is_known=True,
    type = "Training Dummy",
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=30),
)

tutorial_guide = Actor(
    char=chr(0xE035),
    color=(255, 255, 255),
    name="The Guide",
    ai_cls=Friendly,
    equipment=Equipment(),
    fighter=Fighter(hp=999999999999, base_defense=0, base_power=0),
    inventory=Inventory(capacity=26),
    level=Level(xp_given=0),
    sentient=True,
    is_known=True,
    type = "Guide",
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=999999999999),
)

villager = Actor(
    char=chr(0xE03D),
    color=(255, 255, 255),
    name="Villager",
    ai_cls=Friendly,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=0),
    inventory=Inventory(capacity=26),
    level=Level(xp_given=10),
    sentient=True,
    is_known=False,
    type = "NPC",
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=10),
)

quest_giver = Actor(
    char=chr(0xE03D),
    color=(255, 255, 255),
    name="Quest Giver",
    ai_cls=Friendly,
    equipment=Equipment(),
    fighter=Fighter(hp=10, base_defense=0, base_power=0),
    inventory=Inventory(capacity=26),
    level=Level(xp_given=50),
    is_known=False,
    sentient=True,
    type = "NPC",
    body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=10),
)

light_orb = Actor(
    char=chr(0xE03A),
    color=(color.sprite_sheet),
    name="Orb of Light",
    description="A floating orb of light.",
    ai_cls=FollowerAI,
    equipment=Equipment(),
    fighter=Fighter(hp=20, base_defense=0, base_power=0, can_bleed=False, leave_corpse=False),
    inventory=Inventory(capacity=0),
    level=Level(xp_given=0),
    sentient=False,
    is_known=True,
    type = "Orb",
    body_parts=BodyParts(AnatomyType.ORB, max_hp=10),
)
light_orb.blocks_movement = False   # Orb floats — player can walk through it
light_orb.render_order = RenderOrder.ITEM  # Renders under actors (players, enemies)

# =====================================================
# LOOT POOLS - items grouped by rarity tier
# Each LootEntry holds an item template (or factory callable) and a relative weight.
# Higher weight = more likely to be selected when rolling from the pool.
# =====================================================

class LootEntry:
    """A weighted entry in a loot pool."""
    def __init__(self, item_factory, weight: float):
        self.item_factory = item_factory  # Item instance or zero-arg callable
        self.weight = weight


COMMON_POOL = [
    LootEntry(torch,                10),
    LootEntry(dagger,                8),
    LootEntry(shortsword,            6),
    LootEntry(bow,                   5),
    LootEntry(leather_cap,           8),
    LootEntry(leather_armor,         8),
    LootEntry(leather_leggings,      8),
    LootEntry(leather_boot,          8),
    LootEntry(lesser_health_potion,  10),
    LootEntry(lambda: get_scroll("confusion"),      6),
    LootEntry(lambda: get_scroll("darkvision"),     6),
]

UNCOMMON_POOL = [
    LootEntry(health_potion,         10),
    LootEntry(longsword,              7),
    LootEntry(chain_mail_helmet,      8),
    LootEntry(chain_mail_armor,       8),
    LootEntry(chain_mail_leggings,    8),
    LootEntry(lambda: get_scroll("lightning"),       6),
    LootEntry(lambda: get_scroll("fireball"),        5),
    LootEntry(apprentice_robe,         8),
    LootEntry(generate_spellbook,      8),
]

RARE_POOL = [
    LootEntry(mythril_dagger,          10),
    LootEntry(plate_helmet,            10),
    LootEntry(plate_armor,             10),
    LootEntry(scholar_robe,            10),
    LootEntry(lambda: get_ring(),      10),
    LootEntry(fire_resistance_potion,  10),
]

LEGENDARY_POOL = [
    LootEntry(master_robe,             10),
]

AMMO_POOL = [
    LootEntry(arrow,                  20),
    LootEntry(steel_arrow,            10),
]

