"""
Example of how to add new enemies to the simple spawning system.
Much easier and cleaner than the previous complex approach.
"""
from enemy_spawning import add_enemy_to_floor, enemy_spawner
from components.ai import HostileEnemy
from components.equipment import Equipment
from components.fighter import Fighter
from components.inventory import Inventory
from components.body_parts import BodyParts, AnatomyType
from entity import Actor
import copy
import entity_factories


def create_orc():
    """Factory function to create an orc enemy."""
    return Actor(
        char="O",
        color=(60, 120, 60),
        name="Orc",
        ai_cls=HostileEnemy,
        equipment=Equipment(),
        fighter=Fighter(hp=14, base_defense=2, base_power=6),
        inventory=Inventory(capacity=0),
        level=copy.deepcopy(entity_factories.basic_entity_levelling),
        speed=95,
        body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=14),
        description="A brutish humanoid with green skin and tusks.",
        verb_base="slash",
        verb_present="slashes", 
        verb_past="slashed",
        verb_participial="slashing",
        dodge_chance=0.05
    )

def create_skeleton():
    """Factory function to create a skeleton enemy."""
    return Actor(
        char="s",
        color=(200, 200, 200),
        name="Skeleton",
        ai_cls=HostileEnemy,
        equipment=Equipment(),
        fighter=Fighter(hp=12, base_defense=1, base_power=5),
        inventory=Inventory(capacity=0),
        level=copy.deepcopy(entity_factories.basic_entity_levelling),
        speed=100,
        body_parts=BodyParts(AnatomyType.HUMANOID, max_hp=12),
        description="The animated bones of some long-dead warrior.",
        verb_base="claw",
        verb_present="claws",
        verb_past="clawed", 
        verb_participial="clawing",
        dodge_chance=0.20
    )

def create_dragon_wyrmling():
    """Factory function for a powerful late-game enemy.""" 
    return Actor(
        char="D",
        color=(150, 50, 50),
        name="Dragon Wyrmling",
        ai_cls=HostileEnemy,
        equipment=Equipment(),
        fighter=Fighter(hp=30, base_defense=4, base_power=12),
        inventory=Inventory(capacity=0),
        level=copy.deepcopy(entity_factories.basic_entity_levelling),
        speed=120,
        body_parts=BodyParts(AnatomyType.QUADRUPED, max_hp=30),
        description="A young dragon, still dangerous despite its size.",
        verb_base="bite",
        verb_present="bites",
        verb_past="bit",
        verb_participial="biting", 
        dodge_chance=0.15
    )

def add_example_enemies():
    """
    Add example enemies to the spawning system.
    Call this function to add these enemies to the game.
    """
    
    # Add Orc starting at floor 5 with weight 25
    add_enemy_to_floor(5, lambda: copy.deepcopy(create_orc()), 25)
    
    # Add Skeleton starting at floor 4 with weight 30  
    add_enemy_to_floor(4, lambda: copy.deepcopy(create_skeleton()), 30)
    
    # Add Dragon Wyrmling starting at floor 15 with low weight (rare)
    add_enemy_to_floor(15, lambda: copy.deepcopy(create_dragon_wyrmling()), 5)
    
    # You can also add multiple entries for the same enemy at different floors
    # to change spawn rates over time
    add_enemy_to_floor(10, lambda: copy.deepcopy(create_orc()), 40)  # More common later
    add_enemy_to_floor(20, lambda: copy.deepcopy(create_dragon_wyrmling()), 15)  # Much more common

# Uncomment to add these enemies:
# add_example_enemies()

"""
Usage Notes:

1. Super Simple: Just create a factory function and call add_enemy_to_floor()

2. Floor System: 
   - Enemies unlock at specific floors
   - All previous floor enemies remain available
   - Higher floors = previous + new enemies

3. Weight System:
   - Higher weight = more likely to spawn
   - Weight is relative to other available enemies
   - You can add the same enemy at multiple floors with different weights

4. Factory Functions:
   - Must return a new Actor instance each time
   - Use copy.deepcopy() to avoid sharing objects between instances
   - Lambda functions work great: lambda: copy.deepcopy(my_enemy)

5. Infinite Floors:
   - System works at any floor depth
   - Enemy count gradually increases (every 5 floors)
   - Max 8 enemies per room

Example of how simple it is:
```python
def my_new_enemy():
    return Actor(char="X", name="My Enemy", ...)

add_enemy_to_floor(10, lambda: copy.deepcopy(my_new_enemy()), 50)
```

That's it! Your enemy will start spawning at floor 10 with a weight of 50.
"""