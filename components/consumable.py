from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import actions
import color
from animations import LightningAnimation

import tcod
from tcod import libtcodpy


from components import effect
from components import effect
import components.inventory
from components.base_component import BaseComponent
from exceptions import Impossible
from input_handlers import (
    ActionOrHandler,
    AreaRangedAttackHandler, 
    SingleRangedAttackHandler,
)

if TYPE_CHECKING:
    from entity import Actor, Item

import sounds


class Consumable(BaseComponent):
    parent: Item

    def get_action(self, consumer: Actor) -> Optional[ActionOrHandler]:
        # Try to return action for item
        return actions.ItemAction(consumer, self.parent)
    
    def activate(self, action:actions.ItemAction) -> None:
        #activate ability
        raise NotImplementedError()
    
    def consume(self) -> None:
        #removes consumed item from inventory
        entity = self.parent
        inventory = entity.parent
        print("Inventory:", inventory, type(inventory), entity)
        if isinstance(inventory, components.inventory.Inventory):
            print("Consuming item:", entity.name)
            inventory.items.remove(entity)

class ConfusionConsumable(Consumable):
    def __init__(self, number_of_turns: int):
        self.number_of_turns = number_of_turns

    def get_action(self, consumer: Actor) -> SingleRangedAttackHandler:
        self.engine.message_log.add_message(
            "Select a target location.", color.needs_target
        )

        return SingleRangedAttackHandler(
            self.engine,
            callback = lambda xy: actions.ItemAction(consumer, self.parent, xy)
        )
    
    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        target = action.target_actor

        if not self.engine.game_map.visible[action.target_xy]:
            raise Impossible("You cannot target an area you cannot see")
        if not target:
            raise Impossible("You must select an enemy to target.")
        if target is consumer:
            raise Impossible("You cannot confuse yourself!")
        
        self.engine.message_log.add_message(
            f"You have confused the {target.name}!", color.status_effect_applied
        )
        
        target.ai = components.ai.ConfusedEnemy(
            entity=target, previous_ai=target.ai, turns_remaining=self.number_of_turns,
        )
        self.consume()
        sounds.confusion_sound.play()
class PoisonConsumables(Consumable):
    def __init__(self, amount: int, duration: int):
        self.amount = amount
        self.duration = duration

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        
        poison = effect.PoisonEffect(amount=self.amount, duration=self.duration)
        consumer.add_effect(poison)
        self.consume()

class HealingConsumables(Consumable):
    def __init__(self, amount: int):
        self.amount = amount

    def activate(self, action: actions.ItemAction) -> None:
        consumer = action.entity
        amount_recovered = consumer.fighter.heal(self.amount)

        if amount_recovered > 0:
            self.engine.message_log.add_message(
                f"You consume the {self.parent.name}, and recover {amount_recovered}!",
                color.health_recovered
            )
            self.consume()
        else:
            raise Impossible(f"Your health is already full.")
        
class LightningDamageConsumable(Consumable):
    def __init__(self, damage: int, maximum_range: int):
        self.damage = damage
        self.maximum_range = maximum_range

    def activate(self, action: actions.ItemAction) -> None:

        consumer = action.entity
        target = None
        closest_distance = self.maximum_range + 1.0

        for actor in self.engine.game_map.actors:
            if actor is not consumer and self.parent.gamemap.visible[actor.x, actor.y]:
                distance = consumer.distance(actor.x, actor.y)
                #print(distance)
                if distance < closest_distance:
                    target = actor
                    closest_distance = distance

        if target:

            # Animation queuer

            path = list(tcod.los.bresenham((consumer.x, consumer.y), (target.x, target.y)).tolist())

            self.engine.animation_queue.append(LightningAnimation(path))

            self.engine.message_log.add_message(
                f"A lightning bolt strikes the {target.name} for {self.damage} damage!"
            )
            
            target.fighter.take_damage(self.damage)
            self.consume()
            sounds.lightning_sound.play()
        else:

            raise Impossible("No enemy is close enough to strike!") 
        
class FireballDamageConsumable(Consumable):
    def __init__(self, damage: int, radius: int):
        self.damage = damage
        self.radius = radius

    def get_action(self, consumer: Actor) -> AreaRangedAttackHandler:
        self.engine.message_log.add_message(
            "Select target location.", color.needs_target
        )
        return AreaRangedAttackHandler(
            self.engine,
            radius=self.radius,
            callback=lambda xy: actions.ItemAction(consumer, self.parent, xy),
        )
    
    def activate(self, action: actions.ItemAction) -> None:
        target_xy = action.target_xy

        if not self.engine.game_map.visible[target_xy]:
            raise Impossible("You cannot target an area you cannot see!")
        
        targets_hit = False
        for actor in self.engine.game_map.actors:
            if actor.distance(*target_xy) <= self.radius:
                self.engine.message_log.add_message(
                    f"The {actor.name} is engulfed in an explosion, taking {self.damage} damage!"
                )
                actor.fighter.take_damage(self.damage)
                targets_hit = True

        if not targets_hit:
            raise Impossible("There are no targets in the radius")
        
        self.consume()