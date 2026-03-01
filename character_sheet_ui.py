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
import components.level


class CharacterScreen(AskUserEventHandler):

    def __init__(self, engine: Engine):
        super().__init__(engine)
        self.selected_slot = 0
        self.selected_category = 0
        self.expanded_categories = set([0])  # Start with first category expanded
        self.scroll_offset = 0  # For scrolling through categories
        self.max_visible_lines = 22  # Maximum lines to show before scrolling
    
    @property
    def categories(self) -> List[Dict]:
        """Dynamically generate categories from the level system."""
        from components.level import Level
        
        result = []
        
        # Add trait-based categories
        for category_trait, subcategories in Level.TRAIT_CATEGORIES.items():
            result.append({
                'name': self._format_stat_name(category_trait),
                'category_trait': category_trait,  # The main trait for this category
                'stats': subcategories
            })
        
        # Add standalone traits (traits not used as categories or subcategories)
        used_traits = set(Level.TRAIT_CATEGORIES.keys())
        for subcategories in Level.TRAIT_CATEGORIES.values():
            used_traits.update(subcategories)
        
        standalone_traits = [trait for trait in Level.TRAITS if trait not in used_traits]
        if standalone_traits:
            result.append({
                'name': 'Other Skills',
                'stats': standalone_traits
            })
        
        # Add special stats
        if Level.SPECIAL_STATS:
            result.append({
                'name': 'Character Info',
                'stats': Level.SPECIAL_STATS
            })
        
        return result
    
    def _format_stat_name(self, stat_name: str) -> str:
        """Convert stat name to display format."""
        return stat_name.replace('_', ' ').title()
    
    def _get_stat_abbreviation(self, stat_name: str) -> str:
        """Get abbreviated name for a stat."""
        from components.level import Level
        return Level.TRAIT_ABBREVIATIONS.get(stat_name, self._format_stat_name(stat_name))
        
    def on_render(self, console: tcod.Console) -> None:
        super().on_render(console)

        # Calculate window size and position
        window_width = 34
        window_height = 30
        x = (console.width - window_width) // 2
        y = (console.height - window_height -4) // 2

        MenuRenderer.draw_parchment_background(console, x, y, window_width, window_height)
        MenuRenderer.draw_ornate_border(console, x, y, window_width, window_height, "Character Sheet")
        self.render_portrait(console, preview_x = 25, preview_y = 14)
        
        # Calculate stats position and selected category position first
        stats_x, stats_y = x + 9, y + 2
        selected_y = self._get_selected_category_y(stats_y)
        
        # Draw selection bar BEHIND the text
        if selected_y is not None:
            self.render_bar(console, stats_x, selected_y, total_width=20, fg_color=(120, 60, 200), bg_color=(80, 60, 30))
        
        # Render stats on top of the bar
        self.render_stats(console, stats_x, stats_y)
        
        # Show controls at bottom
        controls_y = y + window_height - 4
        console.print(x=x + 2, y=controls_y, string="↑↓: Navigate  Shift+↑↓: Scroll ", fg=color.dark_gray)
        console.print(x=x + 2, y=controls_y + 1, string="SPACE: Expand  ESC: Close", fg=color.dark_gray)

    def ev_keydown(self, event: tcod.event.KeyDown) -> Optional[AskUserEventHandler]:
        if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.C:
            # Return to main game handler to close character sheet
            from input_handlers import MainGameEventHandler
            return MainGameEventHandler(self.engine)
        elif event.sym == tcod.event.KeySym.UP:
            if event.mod & (tcod.event.Modifier.LSHIFT | tcod.event.Modifier.RSHIFT):
                # Shift+Up: Scroll up
                self.scroll_offset = max(0, self.scroll_offset - 1)
                self._play_ui_sound()
            else:
                # Move to previous category
                self.selected_category = (self.selected_category - 1) % len(self.categories)
                self._adjust_scroll()
                self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.DOWN:
            if event.mod & (tcod.event.Modifier.LSHIFT | tcod.event.Modifier.RSHIFT):
                # Shift+Down: Scroll down
                max_scroll = max(0, self._calculate_total_lines() - self.max_visible_lines)
                self.scroll_offset = min(max_scroll, self.scroll_offset + 1)
                self._play_ui_sound()
            else:
                # Move to next category
                self.selected_category = (self.selected_category + 1) % len(self.categories)
                self._adjust_scroll()
                self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.PAGEUP:
            # Scroll up
            self.scroll_offset = max(0, self.scroll_offset - 5)
            self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.PAGEDOWN:
            # Scroll down
            max_scroll = max(0, self._calculate_total_lines() - self.max_visible_lines)
            self.scroll_offset = min(max_scroll, self.scroll_offset + 5)
            self._play_ui_sound()
        elif event.sym == tcod.event.KeySym.SPACE:
            # Toggle category expansion
            if self.selected_category in self.expanded_categories:
                self.expanded_categories.remove(self.selected_category)
            else:
                self.expanded_categories.add(self.selected_category)
            self._adjust_scroll()
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
    
    def _calculate_total_lines(self) -> int:
        """Calculate total lines needed for all categories."""
        total_lines = 0
        for i, category in enumerate(self.categories):
            total_lines += 1  # Category header
            if i in self.expanded_categories:
                total_lines += len(category['stats'])  # Stat lines
                total_lines += 1  # Extra space after category
        return total_lines
    
    def _adjust_scroll(self) -> None:
        """Adjust scroll position to keep selected category visible."""
        selected_y = self._calculate_selected_line()
        if selected_y is not None:
            # Ensure selected category is visible
            if selected_y < self.scroll_offset:
                self.scroll_offset = selected_y
            elif selected_y >= self.scroll_offset + self.max_visible_lines:
                self.scroll_offset = selected_y - self.max_visible_lines + 1
            
            # Clamp scroll to valid range
            max_scroll = max(0, self._calculate_total_lines() - self.max_visible_lines)
            self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))
    
    def _calculate_selected_line(self) -> Optional[int]:
        """Calculate which line the selected category is on."""
        current_line = 0
        for i, category in enumerate(self.categories):
            if i == self.selected_category:
                return current_line
            current_line += 1  # Category header
            if i in self.expanded_categories:
                current_line += len(category['stats'])  # Stat lines
                current_line += 1  # Extra space after category
        return None

    def render_stats(self, console: tcod.Console, x: int, y: int) -> None:
        
        player = self.engine.player
        current_line = y
        logical_line = 0  # Track logical line position for scrolling
        bar_x_position = x + 15  # Fixed position for all progress bars
        
        for i, category in enumerate(self.categories):
            # Check if this category header should be visible
            if logical_line >= self.scroll_offset and logical_line < self.scroll_offset + self.max_visible_lines:
                # Show expand/collapse indicator
                is_expanded = i in self.expanded_categories
                indicator = "▼" if is_expanded else "►"
                
                # Draw category header
                console.print(x=x, y=current_line, string=f"{indicator} {category['name']}", 
                             fg=color.fantasy_text)
                
                # If this category has a main trait, show its stats on the same line
                if 'category_trait' in category:
                    main_trait = category['category_trait']
                    stats = self._get_stat_text(player, main_trait)
                    if 'level' in stats and 'xp' in stats and 'needed' in stats:
                        level_text = f"Lv.{stats['level']}"
                        # Position level text to end right before the XP bar
                        level_x = bar_x_position - len(level_text)
                        console.print(x=level_x, y=current_line, string=level_text, fg=color.gold_accent)
                        # Render XP progress bar at fixed position
                        self.render_xp_bar(console, bar_x_position, current_line, stats['xp'], stats['needed'])
                
                current_line += 1
            
            logical_line += 1  # Category header line
            
            is_expanded = i in self.expanded_categories
            # Show category contents if expanded
            if is_expanded:
                for stat_name in category['stats']:
                    # Check if this stat line should be visible
                    if logical_line >= self.scroll_offset and logical_line < self.scroll_offset + self.max_visible_lines:
                        stats = self._get_stat_text(player, stat_name)
                        stat_display = self._get_stat_abbreviation(stat_name)
                        
                        # Format the stat display based on what data is available
                        if 'level' in stats and 'xp' in stats and 'needed' in stats:
                            # Trait with level progression - show abbreviation and level
                            console.print(x=x+1, y=current_line, string=f"  {stat_display}:", fg=color.fantasy_text)
                            
                            # Position level text to end right before the XP bar
                            level_text = f"Lv.{stats['level']}"
                            level_x = bar_x_position - len(level_text)
                            console.print(x=level_x, y=current_line, string=level_text, fg=color.fantasy_text)
                            
                            # Render XP progress bar at fixed position
                            self.render_xp_bar(console, bar_x_position, current_line, stats['xp'], stats['needed'])
                        elif 'value' in stats and 'max' in stats:
                            # HP with current/max
                            stat_text = f"  {stat_display}: {stats['value']}/{stats['max']}"
                            console.print(x=x , y=current_line, string=stat_text, fg=color.fantasy_text)
                        elif 'value' in stats:
                            # Simple value display
                            stat_text = f"  {stat_display}: {stats['value']}"
                            console.print(x=x , y=current_line, string=stat_text, fg=color.fantasy_text)
                        else:
                            stat_text = f"  {stat_display}: ???"
                            console.print(x=x , y=current_line, string=stat_text, fg=color.fantasy_text)
                        
                        current_line += 1
                    
                    logical_line += 1  # Stat line
                
                # Extra space after expanded category
                if logical_line >= self.scroll_offset and logical_line < self.scroll_offset + self.max_visible_lines:
                    current_line += 1
                logical_line += 1

    
    def _get_selected_category_y(self, start_y: int) -> int:
        """Calculate the Y position of the selected category without rendering."""
        selected_logical_line = self._calculate_selected_line()
        if selected_logical_line is None:
            return None
        
        # Check if selected category is visible in current scroll window
        if selected_logical_line < self.scroll_offset or selected_logical_line >= self.scroll_offset + self.max_visible_lines:
            return None
        
        # Calculate screen position
        visible_line_index = selected_logical_line - self.scroll_offset
        return start_y + visible_line_index
    
    def _get_stat_text(self, player, stat_name: str) -> Dict[str, int]:
        """Get formatted data for a specific stat."""
        # Handle special non-trait stats
        if stat_name == 'level':
            return {'value': player.level.current_level}
        elif stat_name == 'gold':
            return {'value': player.gold}
        elif stat_name == 'hp':
            return {'value': player.fighter.hp, 'max': player.fighter.max_hp}
        
        # Handle traits from the level system
        elif stat_name in player.level.traits:
            trait_data = player.level.traits[stat_name]
            current_level = trait_data['level']
            current_xp = trait_data['xp']
            

            
            # Use the corrected xp_to_next method
            xp_needed = player.level.xp_to_next(stat_name)
            
            return {
                'level': current_level,
                'xp': current_xp, 
                'needed': xp_needed
            }
        
        # Fallback for unknown stats
        return {'value': '?'}

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
                ch=ord('■'), fg=color.gold_accent, bg=color.parchment_bg
            )
        
        # Draw the empty portion
        empty_width = bar_width - filled_width
        if empty_width > 0:
            console.draw_rect(
                x=x + filled_width, y=y, width=empty_width, height=1,
                ch=ord('²'), fg=(100, 100, 100), bg=color.parchment_bg
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
        


