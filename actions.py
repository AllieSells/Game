from __future__ import annotations

from typing import Optional, Tuple, TYPE_CHECKING

import color
import exceptions
import copy 

if TYPE_CHECKING:
    from engine import Engine
    from entity import Actor, Entity, Item
    from components.container import Container


class Action:
    def __init__(self, entity: Actor) -> None:
        super().__init__()
        self.entity = entity

    @property
    def engine(self) -> Engine:
        return self.entity.gamemap.engine
    
    def perform(self) -> None:
        """Perform this action with the objects needed to determine its scope.
        
        `self.engine` is the scope this action is being performed in.

        `self.entity` is the object performing the action.

        This method must be overridden by Action subclasses.
        """
        raise NotImplementedError()

class PickupAction(Action):
    #pick up item and put in inventory IF ROOM

    def __init__(self, entity: Actor):
        super().__init__(entity)

    def perform(self) -> None:
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y
        inventory = self.entity.inventory

        for item in self.engine.game_map.items:
            if actor_location_x == item.x and actor_location_y == item.y:
                if len(inventory.items) >= inventory.capacity:
                    raise exceptions.Impossible("Your inventory is full IDIOT")
            
                self.engine.game_map.entities.remove(item)
                item.parent = self.entity.inventory
                inventory.items.append(item)
                # Special-case picking up a campfire: convert to a Torch with a flavor message
                try:
                    from entity_factories import torch 
                except Exception:
                    _torch_template = None

                if item.name == "Campfire" and torch is not None:
                    inventory.items.pop()
                    new_torch = copy.deepcopy(torch)
                    new_torch.parent = self.entity.inventory
                    inventory.items.append(new_torch)

                    self.engine.message_log.add_message("You pull a burning log from the fire")
                    return

                self.engine.message_log.add_message(f"You picked up the {item.name}!")
                return
        raise exceptions.Impossible("There is nothing here to pick up.")

class ItemAction(Action):
    def __init__(
            self, entity: Actor, item: Item, target_xy: Optional[Tuple[int, int]] = None
    ):
        super().__init__(entity)
        self.item = item
        if not target_xy:
            target_xy = entity.x, entity.y
        self.target_xy = target_xy

    @property
    def target_actor(self) -> Optional[Actor]:
        # Returns actor at this actions destination
        return self.engine.game_map.get_actor_at_location(*self.target_xy)
    
    def perform(self) -> None:
        # Invoke item, action will be given context
        if self.item.consumable:
            self.item.consumable.activate(self)


class DropItem(ItemAction):
    def perform(self) -> None:
        if self.entity.equipment.item_is_equipped(self.item):
            self.entity.equipment.toggle_equip(self.item)
        
        self.entity.inventory.drop(self.item) 
class OpenAction(Action):
    def perform(self) -> None:
        # Open a container (chest) on the map and present its contents to the player.
        actor_location_x = self.entity.x
        actor_location_y = self.entity.y

class EquipAction(Action):
    def __init__(self, entity: Actor, item: Item):
        super().__init__(entity)

        self.item = item

    def perform(self) -> None:
        self.entity.equipment.toggle_equip(self.item)

class WaitAction(Action):
    def perform(self) -> None:
        pass

class TakeStairsAction(Action):
    def perform(self) -> None:
        # Take the stairs, if they exist at its location

        if (self.entity.x, self.entity.y) == self.engine.game_map.downstairs_location:
            self.engine.game_world.generate_floor()
            self.engine.message_log.add_message(
                "You descend the staircase.", color.descend
            )

        else:
            raise exceptions.Impossible("There are no stairs here.")

class ActionWithDirection(Action):
    def __init__(self, entity: Actor, dx: int, dy: int):
        super().__init__(entity)
        
        self.dx = dx
        self.dy = dy

    @property # destination
    def dest_xy(self) -> Tuple[int, int]:
        """Return the destination coordinates after this action."""
        return self.entity.x + self.dx, self.entity.y + self.dy

    @property # is blocking?
    def blocking_entity(self) -> Optional[Entity]:
        """Return the blocking entity at this action's destination."""
        return self.engine.game_map.get_blocking_entity_at_location(*self.dest_xy)

    @property
    def target_actor(self) -> Optional[Actor]:
        #Return the actor at actions dest.
        return self.engine.game_map.get_actor_at_location(*self.dest_xy)

    def perform(self) -> None:
        raise NotImplementedError()
    
class MeleeAction(ActionWithDirection):
    def perform(self) -> None:
        target = self.target_actor

        if not target:
            raise exceptions.Impossible("Nothing to attack.")

        damage = self.entity.fighter.power - target.fighter.defense

        attack_desc = f"{self.entity.name.capitalize()} attacks {target.name}"

        if self.entity is self.engine.player:
            attack_color = color.player_atk
        else:
            attack_color = color.enemy_atk

        if damage > 0:
            self.engine.message_log.add_message(
                f"{attack_desc} for {damage} hit points.", attack_color
                )
            target.fighter.hp -= damage
        else:
            self.engine.message_log.add_message(
                f"{attack_desc}, but does no damage.", attack_color
            )

class MovementAction(ActionWithDirection):

    def perform(self) -> None:
        dest_x, dest_y = self.dest_xy

        if not self.engine.game_map.in_bounds(dest_x, dest_y):
            raise exceptions.Impossible("That way is blocked.")  # Destination is out of bounds.
        
        if not self.engine.game_map.tiles["walkable"][dest_x, dest_y]:
            raise exceptions.Impossible("That way is blocked.")  # Destination is not walkable.
        if self.engine.game_map.get_blocking_entity_at_location(dest_x, dest_y):
            raise exceptions.Impossible("That way is blocked.")  # Destination is blocked by an entity.
        
        self.entity.move(self.dx, self.dy)

class BumpAction(ActionWithDirection):
    def perform(self) -> None:
        if self.target_actor:
            return MeleeAction(self.entity, self.dx, self.dy).perform()
        else:
            return MovementAction(self.entity, self.dx, self.dy).perform()
        
