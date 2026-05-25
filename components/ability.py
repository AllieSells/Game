from __future__ import annotations

from typing import TYPE_CHECKING

import exceptions

if TYPE_CHECKING:
    from actions import AbilityAction

class Ability():
    def __init__(self, name: str, description: str, cooldown: int, *args):
        self.name = name
        self.description = description
        self.cooldown = cooldown
        self.current_cooldown = 0
        self.requires_target = False
        self.args = args

    def can_perform(self) -> bool:
        return self.current_cooldown == 0

    def tick_cooldown(self, amount: int = 1) -> None:
        """Reduce cooldown by a fixed amount, clamped at zero."""
        if amount <= 0:
            return
        self.current_cooldown = max(0, int(self.current_cooldown) - int(amount))
    
    def activate(self, action: 'AbilityAction') -> None:
        if not self.can_perform():
            action.engine.message_log.add_message(f"You must wait {self.current_cooldown} more turns!")
            return
        # Placeholder for actual ability logic
        action.engine.message_log.add_message(f"You use {self.name}!")
        self.current_cooldown = self.cooldown


class Charge(Ability):
    def __init__(self):
        super().__init__(
            name="Charge",
            description="Crash towards your target.",
            cooldown=150,
        )
        self.requires_target = True
        self.max_range = 5

    def activate(self, action: 'AbilityAction') -> None:
        if not self.can_perform():
            action.engine.message_log.add_message(f"You must wait {self.current_cooldown} more turns!")
            return

        if not action.target_xy:
            action.engine.message_log.add_message("Select an enemy to charge.")
            return

        from actions import MeleeAction, MovementAction

        entity = action.entity
        tx, ty = action.target_xy
        target = action.engine.game_map.get_actor_at_location(tx, ty)


        ddx = tx - entity.x
        ddy = ty - entity.y
        distance = max(abs(ddx), abs(ddy))
        if distance < 1 or distance > self.max_range:
            action.engine.message_log.add_message("Too far to charge.")
            return

        # Move toward the target, recalculating each step.
        for _ in range(self.max_range):
            if max(abs(tx - entity.x), abs(ty - entity.y)) <= 1:
                break

            step_dx = 0 if tx == entity.x else (1 if tx > entity.x else -1)
            step_dy = 0 if ty == entity.y else (1 if ty > entity.y else -1)

            try:
                MovementAction(entity, step_dx, step_dy).perform()
            except exceptions.Impossible:
                action.engine.message_log.add_message("Your charge is blocked!")
                return

        if max(abs(tx - entity.x), abs(ty - entity.y)) > 1:
            action.engine.message_log.add_message("You can't reach that target!")
            return

        final_dx = tx - entity.x
        final_dy = ty - entity.y

        try:
            MeleeAction(entity, final_dx, final_dy).perform()
        except exceptions.Impossible:
            action.engine.message_log.add_message("Your charge misses its opening.")
            return

        action.engine.message_log.add_message("You charge forward!")
        self.current_cooldown = self.cooldown
        