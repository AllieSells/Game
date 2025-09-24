from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import actions
import color
from components.base_component import BaseComponent
from exceptions import Impossible

if TYPE_CHECKING:
    from entity import Actor, Item


class Consumable(BaseComponent):
    parent: Item

    def get_action(self, consumer: Actor) -> Optional[actions.Action]:
        # Try to return action for item
        return actions.ItemAction(consumer, self.parent)
    
    def activate(self, action:actions.ItemAction) -> None:
        #activate ability
        raise NotImplementedError()
    
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
        else:
            raise Impossible(f"Your health is already full.")