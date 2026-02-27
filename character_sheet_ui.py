from __future__ import annotations
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

import tcod
import color
from equipment_types import EquipmentType
from input_handlers import AskUserEventHandler
from render_functions import MenuRenderer
import actions

if TYPE_CHECKING:
    from engine import Engine
    from entity import Item
import sounds
import trait_xp_system


class CharacterScreen(AskUserEventHandler):

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.selected_slot = 0
        self.selected_category = 0
        self.expanded_categories = set([0])  # Start with first category expanded
        
        # Define stat categories
        self.categories = [
            {
                'name': 'Physical Traits────',
                'stats': ['strength', 'dexterity', 'constitution'],
                'display': ['STR', 'DEX', 'CON']
            },
            {
                'name': 'Combat Stats', 
                'stats': ['base_power', 'base_defense', 'hp'],
                'display': ['Power', 'Defense', 'HP']
            },
            {
                'name': 'Character Info',
                'stats': ['level', 'gold'],
                'display': ['Level', 'Gold']
            }
        ]
        
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        # Calculate window size and position
        window_width = 40
        window_height = 25
        x = (console.width - window_width) // 2
        y = (console.height - window_height) // 2

        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Character Sheet")
        self.render_portrait(console, preview_x = 22, preview_y = 14)
        
        # Calculate stats position and selected category position first
        stats_x, stats_y = x + 8, y + 2
        selected_y = self._get_selected_category_y(stats_y)
        
        # Draw selection bar BEHIND the text
        if selected_y is not None:
            self.render_bar(console, stats_x, selected_y, total_width=30, fg_color=(120, 60, 200), bg_color=(80, 60, 30))
        
        # Render stats on top of the bar
        self.render_stats(console, stats_x, stats_y)
        
        # Show controls at bottom
        controls_y = y + window_height - 3
        console.print(x=x + 2, y=controls_y, string="↑↓: Navigate  SPACE: Expand/Collapse  ESC: Close", fg=color.dark_gray)

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[AskUserEventHandler]:
        if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.C:
            # Return to main game handler to close character sheet
            from input_handlers import MainGameEventHandler
            return MainGameEventHandler(self.engine)
        elif event.sym == tcod.event.KeySym.UP:
            # Move to previous category
            self.selected_category = (self.selected_category - 1) % len(self.categories)
            self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.DOWN:
            # Move to next category
            self.selected_category = (self.selected_category + 1) % len(self.categories)
            self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.SPACE:
            # Toggle category expansion
            if self.selected_category in self.expanded_categories:
                self.expanded_categories.remove(self.selected_category)
            else:
                self.expanded_categories.add(self.selected_category)
            self._play_ui_sound()
        
        # Always return self to stay in this handler (except for ESC/C above)
        return self
    
    def _play_ui_sound(self):
        """Play UI navigation sound if available."""
        try:
            sounds.play_ui_move_sound()
        except:
            try:
                sounds.play_menu_move_sound()
            except:
                pass  # Silent fail if no sound available

    def render_stats(self, console: tcod.Console, x: int, y: int) -> None:
        import trait_xp_system
        from trait_xp_system import TraitType
        
        player = self.engine.player
        current_line = y
        
        for i, category in enumerate(self.categories):
            # Show expand/collapse indicator
            is_expanded = i in self.expanded_categories
            indicator = "▼" if is_expanded else "►"
            
            # Draw category header (all in normal color)
            console.print(x=x, y=current_line, string=f"{indicator} {category['name']}", 
                         fg=color.fantasy_text)
            current_line += 1
            
            # Show category contents if expanded
            if is_expanded:
                for stat_name, stat_display in zip(category['stats'], category['display']):
                    stats = self._get_stat_text(player, stat_name, trait_xp_system)
                    
                    # Format the stat display based on what data is available
                    if 'level' in stats and 'xp' in stats and 'needed' in stats:
                        # Trait with level progression - show level and XP bar
                        level_text = f"{stat_display}: {stats['level']}"
                        console.print(x=x + 2, y=current_line, string=level_text, fg=color.fantasy_text)
                        # Render XP progress bar
                        bar_x = x + 2 + len(level_text) + 1
                        self.render_xp_bar(console, bar_x, current_line, stats['xp'], stats['needed'])
                    elif 'value' in stats and 'max' in stats:
                        # HP with current/max
                        stat_text = f"{stat_display}: {stats['value']}/{stats['max']}"
                        console.print(x=x + 2, y=current_line, string=stat_text, fg=color.fantasy_text)
                    elif 'value' in stats:
                        # Simple value display
                        stat_text = f"{stat_display}: {stats['value']}"
                        console.print(x=x + 2, y=current_line, string=stat_text, fg=color.fantasy_text)
                    else:
                        stat_text = f"{stat_display}: ???"
                        console.print(x=x + 2, y=current_line, string=stat_text, fg=color.fantasy_text)
                    current_line += 1
                current_line += 1  # Extra space after expanded category
    
    def _get_selected_category_y(self, start_y: int) -> int:
        """Calculate the Y position of the selected category without rendering."""
        current_line = start_y
        
        for i, category in enumerate(self.categories):
            # Return Y position if this is the selected category
            if i == self.selected_category:
                return current_line
            
            current_line += 1  # Category header line
            
            # Account for expanded content
            if i in self.expanded_categories:
                current_line += len(category['stats'])  # Stat lines
                current_line += 1  # Extra space after category
        
        return None
    
    def _get_stat_text(self, player, stat_name: str, trait_xp_system) -> str:
        """Get formatted text for a specific stat."""
        from trait_xp_system import TraitType
        
        if stat_name == 'strength':
            level = player.level.get_trait_level(TraitType.STRENGTH)
            xp = player.level.get_trait_xp(TraitType.STRENGTH)
            needed = trait_xp_system.get_trait_xp_to_next_level(player, TraitType.STRENGTH)
            return {
                'level': level,
                'xp': xp,
                'needed': needed
            }
        elif stat_name == 'dexterity':
            level = player.level.get_trait_level(TraitType.DEXTERITY)
            xp = player.level.get_trait_xp(TraitType.DEXTERITY)
            needed = trait_xp_system.get_trait_xp_to_next_level(player, TraitType.DEXTERITY)
            return {
                'level': level,
                'xp': xp,
                'needed': needed
            }
        elif stat_name == 'constitution':
            level = player.level.get_trait_level(TraitType.CONSTITUTION)
            xp = player.level.get_trait_xp(TraitType.CONSTITUTION)
            needed = trait_xp_system.get_trait_xp_to_next_level(player, TraitType.CONSTITUTION)
            return {
                'level': level,
                'xp': xp,
                'needed': needed
            }
        elif stat_name == 'base_power':
            return {
                'value': player.fighter.base_power
            }
        elif stat_name == 'base_defense':
            return {
                'value': player.fighter.base_defense
            }
        elif stat_name == 'hp':
            return {
                'value': player.fighter.hp,
                'max': player.fighter.max_hp
            }
        elif stat_name == 'level':
            return {
                'value': player.level.current_level
            }
        elif stat_name == 'gold':
            return {
                'value': getattr(player, 'gold', 0)
            }
        else:
            return {
                'value': f"???"
            }

    def render_bar(self, console: tcod.Console, x: int, y: int, total_width: int, fg_color: Tuple[int, int, int], bg_color: Tuple[int, int, int]) -> None:
        console.draw_rect(x=x, y=y, width=total_width, height=1, ch=1, fg=fg_color, bg=bg_color)
    
    def render_xp_bar(self, console: tcod.Console, x: int, y: int, current_xp: int, max_xp: int, bar_width: int = 8) -> None:
        """Render a small XP progress bar."""
        if max_xp <= 0:
            filled_width = 0
        else:
            filled_width = int((current_xp / max_xp) * bar_width)
        
        # Draw the filled portion
        if filled_width > 0:
            console.draw_rect(
                x=x, y=y, width=filled_width, height=1,
                ch=ord('▄'), fg=color.gold_accent, bg=color.parchment_bg
            )
        
        # Draw the empty portion
        empty_width = bar_width - filled_width
        if empty_width > 0:
            console.draw_rect(
                x=x + filled_width, y=y, width=empty_width, height=1,
                ch=ord('▄'), fg=(100, 100, 100), bg=color.parchment_bg
            )



    def render_portrait(self, console: tcod.Console, preview_x: int, preview_y: int) -> None:
        preview_size = 3
        frame_x = preview_x
        frame_y = preview_y

        # Draw frame 
        console.draw_frame(
            x=frame_x, y=frame_y,
            width=preview_size + 2, height=preview_size + 2,
            title="YOU", clear=True,
            fg=(139, 120, 60), bg=(45, 35, 25)
            )
        
        # Draw character in center of frame
        char = self.engine.player.char
        char_x = frame_x + 1 + preview_size // 2
        char_y = frame_y + 1 + preview_size // 2
        console.print(x=char_x, y=char_y, string=char, fg=self.engine.player.color)
        


