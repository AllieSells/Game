import arcade
import tcod

TILE_SIZE = 16

class RenderConsole:
    def __init__(self, tileset, width, height):
        self.width = width
        self.height = height
        self.tileset = tileset

        self.grid = [[[] for _ in range(height)] for _ in range(width)]
        
        # Create a tcod console for compatibility with context.present()
        self._tcod_console = tcod.Console(width, height, order="F")

    def clear(self):
        for x in range(self.width):
            for y in range(self.height):
                self.grid[x][y].clear()
        self._tcod_console.clear()

    def print(self, x, y, text=None, fg=(255, 255, 255), bg=None, string=None, alignment=None):
        # Support both 'text' and 'string' parameter names for compatibility
        content = text if text is not None else string
        if content is None:
            return
            
        # Convert single characters to string
        if isinstance(content, int):
            content = chr(content)
        elif not isinstance(content, str):
            content = str(content)
        
        # Handle alignment
        if alignment is not None:
            import tcod
            if alignment == tcod.CENTER:
                x = x - len(content) // 2
            elif alignment == tcod.RIGHT:
                x = x - len(content)
            # LEFT alignment uses x as-is
            
        for i, char in enumerate(content):
            if x + i < self.width and y < self.height and x + i >= 0 and y >= 0:
                index = ord(char)
                self.grid[x + i][y].append((index, fg, bg))
                
                # Also update tcod console for compatibility
                if alignment is not None:
                    # For tcod console, pass the original x,y and alignment
                    if i == 0:  # Only call once for the whole string
                        original_x = x + len(content) // 2 if alignment == tcod.CENTER else (x + len(content) if alignment == tcod.RIGHT else x)
                        self._tcod_console.print(original_x, y, content, fg=fg, bg=bg, alignment=alignment)
                else:
                    self._tcod_console.print(x + i, y, char, fg=fg, bg=bg)

    def print_box(self, x, y, width, height, text, fg=(255, 255, 255), bg=None, alignment=None):
        """Print text in a box with text wrapping and alignment support."""
        # For simplicity, just delegate to tcod console for print_box
        # In the future, this could be implemented for arcade rendering
        self._tcod_console.print_box(x, y, width, height, text, fg=fg, bg=bg, alignment=alignment)

    def draw_rect(self, x, y, width, height, ch=ord(' '), fg=(255, 255, 255), bg=None):
        """Draw a rectangle filled with the given character."""
        if isinstance(ch, str):
            ch = ord(ch)
        char = chr(ch)
        
        for dy in range(height):
            for dx in range(width):
                if 0 <= x + dx < self.width and 0 <= y + dy < self.height:
                    self.grid[x + dx][y + dy].append((ch, fg, bg))
        
        # Also update tcod console for compatibility
        self._tcod_console.draw_rect(x, y, width, height, ch=ch, fg=fg, bg=bg)

    def draw_frame(self, x, y, width, height, title=None, clear=True, fg=(255, 255, 255), bg=None):
        """Draw a frame border with optional title."""
        if clear:
            # Clear the interior
            for dy in range(1, height - 1):
                for dx in range(1, width - 1):
                    if 0 <= x + dx < self.width and 0 <= y + dy < self.height:
                        self.grid[x + dx][y + dy].clear()
                        if bg is not None:
                            self.grid[x + dx][y + dy].append((ord(' '), fg, bg))

        # Draw corners
        if x >= 0 and y >= 0 and x < self.width and y < self.height:
            self.grid[x][y].append((ord('┌'), fg, bg))  # Top-left
        if x + width - 1 >= 0 and y >= 0 and x + width - 1 < self.width and y < self.height:
            self.grid[x + width - 1][y].append((ord('┐'), fg, bg))  # Top-right
        if x >= 0 and y + height - 1 >= 0 and x < self.width and y + height - 1 < self.height:
            self.grid[x][y + height - 1].append((ord('└'), fg, bg))  # Bottom-left
        if x + width - 1 >= 0 and y + height - 1 >= 0 and x + width - 1 < self.width and y + height - 1 < self.height:
            self.grid[x + width - 1][y + height - 1].append((ord('┘'), fg, bg))  # Bottom-right

        # Draw horizontal borders
        for dx in range(1, width - 1):
            if 0 <= x + dx < self.width:
                if y >= 0 and y < self.height:
                    self.grid[x + dx][y].append((ord('─'), fg, bg))  # Top
                if y + height - 1 >= 0 and y + height - 1 < self.height:
                    self.grid[x + dx][y + height - 1].append((ord('─'), fg, bg))  # Bottom

        # Draw vertical borders
        for dy in range(1, height - 1):
            if 0 <= y + dy < self.height:
                if x >= 0 and x < self.width:
                    self.grid[x][y + dy].append((ord('│'), fg, bg))  # Left
                if x + width - 1 >= 0 and x + width - 1 < self.width:
                    self.grid[x + width - 1][y + dy].append((ord('│'), fg, bg))  # Right

        # Draw title if provided
        if title and len(title) > 0:
            title_x = x + 2  # Start after the left border
            if 0 <= title_x < self.width and 0 <= y < self.height:
                self.print(title_x, y, title, fg=fg, bg=bg)
                
        # Also update tcod console for compatibility
        self._tcod_console.draw_frame(x, y, width, height, title=title, clear=clear, fg=fg, bg=bg)

    def blit(self, destination, dest_x, dest_y):
        """Blit this console onto another console.""" 
        if hasattr(destination, 'grid'):
            # Copy from this console to destination RenderConsole
            for x in range(self.width):
                for y in range(self.height):
                    dest_x_pos = dest_x + x
                    dest_y_pos = dest_y + y
                    if (0 <= dest_x_pos < destination.width and 
                        0 <= dest_y_pos < destination.height and
                        self.grid[x][y]):
                        destination.grid[dest_x_pos][dest_y_pos].extend(self.grid[x][y])
            
            # Also blit tcod console for compatibility
            if hasattr(destination, '_tcod_console'):
                self._tcod_console.blit(destination._tcod_console, dest_x, dest_y)

    # Add tcod compatibility properties
    @property
    def tiles_rgb(self):
        """Access to tcod console's tiles_rgb for compatibility."""
        return self._tcod_console.tiles_rgb
    
    @property
    def bg(self):
        """Access to tcod console's background colors for compatibility."""
        return self._tcod_console.bg
    
    @property
    def fg(self):
        """Access to tcod console's foreground colors for compatibility."""
        return self._tcod_console.fg
        
    @property
    def rgb(self):
        """Access to tcod console's rgb arrays for compatibility."""
        return self._tcod_console.rgb
    
    def __getattr__(self, name):
        """Delegate any other attribute access to the tcod console for compatibility."""
        if hasattr(self._tcod_console, name):
            return getattr(self._tcod_console, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    
    def draw(self):
        """Draw the arcade version (if needed in the future)."""
        self.sprite_list = arcade.SpriteList()

        for x in range(self.width):
            for y in range(self.height):
                stack = self.grid[x][y]

                if not stack:
                    continue

                px = x * TILE_SIZE
                py = (self.height - y) * TILE_SIZE

                # Draw everything in order
                for char, fg, bg in stack:
                    if bg:
                        bg_sprite = arcade.SpriteSolidColor(TILE_SIZE, TILE_SIZE, bg)
                        bg_sprite.center_x = px
                        bg_sprite.center_y = py
                        self.sprite_list.append(bg_sprite)

                    if isinstance(char, int):
                        index = char
                    else:
                        index = ord(char)

                    sprite = arcade.Sprite()
                    sprite.texture = self.tileset[index]
                    sprite.color = fg
                    sprite.center_x = px
                    sprite.center_y = py
                    self.sprite_list.append(sprite)

        self.sprite_list.draw()
    
    # Compatibility methods that delegate to tcod console
    def __getattr__(self, name):
        """Delegate unknown attributes to the internal tcod console."""
        return getattr(self._tcod_console, name)

    
    def draw(self):
        self.sprite_list = arcade.SpriteList()

        for x in range(self.width):
            for y in range(self.height):
                stack = self.grid[x][y]

                if not stack:
                    continue

                px = x * TILE_SIZE
                py = (self.height - y) * TILE_SIZE

                # Draw everything in order
                for char, fg, bg in stack:
                    if bg:
                        bg_sprite = arcade.SpriteSolidColor(TILE_SIZE, TILE_SIZE, bg)
                        bg_sprite.center_x = px
                        bg_sprite.center_y = py
                        self.sprite_list.append(bg_sprite)

                    if isinstance(char, int):
                        index = char
                    else:
                        index = ord(char)

                    sprite = arcade.Sprite()
                    sprite.texture = self.tileset[index]
                    sprite.color = fg
                    sprite.center_x = px
                    sprite.center_y = py
                    self.sprite_list.append(sprite)

        self.sprite_list.draw()
