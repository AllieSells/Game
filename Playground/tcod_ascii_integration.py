"""
TCOD Integration Helper for ASCII Art
====================================

Shows how to display converted GLB ASCII art in your TCOD game.
"""

import tcod
import json
from typing import List, Tuple, Dict, Any
from glb_to_ascii import GLBToASCII, AsciiArtConfig, load_ascii_for_tcod


class AsciiArtRenderer:
    """Renders ASCII art in TCOD console with various display options"""
    
    def __init__(self):
        self.ascii_cache = {}
    
    def load_ascii_art(self, json_path: str) -> Dict[str, Any]:
        """Load and cache ASCII art from JSON file"""
        if json_path not in self.ascii_cache:
            ascii_lines, metadata = load_ascii_for_tcod(json_path)
            self.ascii_cache[json_path] = {
                'lines': ascii_lines,
                'metadata': metadata,
                'width': len(ascii_lines[0]) if ascii_lines else 0,
                'height': len(ascii_lines)
            }
        
        return self.ascii_cache[json_path]
    
    def render_ascii_art(self, console: tcod.console.Console, x: int, y: int, 
                        ascii_data: Dict[str, Any], main_color: Tuple[int, int, int] = (255, 255, 255)):
        """Render ASCII art to console with color gradient"""
        lines = ascii_data['lines']
        ascii_chars = ascii_data['metadata']['ascii_chars']
        
        for row_idx, line in enumerate(lines):
            for col_idx, char in enumerate(line):
                if char != ' ':
                    # Calculate color intensity based on character
                    char_intensity = ascii_chars.index(char) / (len(ascii_chars) - 1) if char in ascii_chars else 0
                    
                    # Create gradient from dark to bright
                    color = tuple(int(c * (0.2 + 0.8 * (1 - char_intensity))) for c in main_color)
                    
                    console.print(x + col_idx, y + row_idx, char, fg=color)
    
    def render_ascii_art_animated(self, console: tcod.console.Console, x: int, y: int,
                                ascii_data: Dict[str, Any], rotation_angle: float = 0,
                                main_color: Tuple[int, int, int] = (255, 255, 255)):
        """Render ASCII art with rotation animation (creates multiple views)"""
        # For now, just render normally - true 3D rotation would require
        # re-projecting the original 3D model at different angles
        self.render_ascii_art(console, x, y, ascii_data, main_color)


def convert_and_integrate_glb(glb_file_path: str, name: str) -> str:
    """Convert GLB file and save for TCOD integration"""
    
    # Configure ASCII conversion
    config = AsciiArtConfig(
        width=40,   # Reasonable size for game UI
        height=20,
        ascii_chars="@%#*+=~-:. ",  # Custom character set
        use_shading=True,
        camera_elevation=25.0,      # Good viewing angle
        camera_azimuth=35.0
    )
    
    converter = GLBToASCII(config)
    output_path = f"RP/{name}_ascii.json"
    
    try:
        ascii_lines = converter.convert_glb_to_ascii(glb_file_path, output_path)
        print(f"✓ Converted {glb_file_path} to {output_path}")
        return output_path
    except Exception as e:
        print(f"✗ Error converting {glb_file_path}: {e}")
        return ""


def demo_tcod_integration():
    """Demo showing ASCII art in TCOD"""
    screen_width = 120  
    screen_height = 60
    
    # Initialize TCOD
    tileset = tcod.tileset.load_tilesheet(
        "RP/AllieClassic.png", 16, 16, tcod.tileset.CHARMAP_CP437
    )
    
    with tcod.context.new_terminal(
        screen_width, screen_height,
        tileset=tileset,
        title="GLB ASCII Art Demo",
        vsync=True,
    ) as context:
        console = tcod.console.Console(screen_width, screen_height, order="F")
        renderer = AsciiArtRenderer()
        
        # Example: Load converted ASCII art
        # ascii_data = renderer.load_ascii_art("RP/sword_ascii.json")
        
        while True:
            console.clear()
            
            # Title
            console.print(2, 2, "GLB to ASCII Art in TCOD", fg=(255, 255, 128))
            console.print(2, 3, "=" * 30, fg=(100, 100, 100))
            
            # Instructions
            console.print(2, 5, "Place your GLB files in the project folder", fg=(200, 200, 200))
            console.print(2, 6, "Use convert_and_integrate_glb() to convert them", fg=(200, 200, 200))
            console.print(2, 7, "Then load and display with AsciiArtRenderer", fg=(200, 200, 200))
            
            # Example ASCII art display area
            console.print(2, 10, "ASCII Art Display Area:", fg=(128, 255, 128))
            
            # Draw a border for the display area
            for i in range(50):
                console.print(5 + i, 12, "-", fg=(80, 80, 80))
                console.print(5 + i, 35, "-", fg=(80, 80, 80))
            for i in range(23):
                console.print(5, 12 + i, "|", fg=(80, 80, 80))
                console.print(54, 12 + i, "|", fg=(80, 80, 80))
            
            # Placeholder text
            console.print(20, 23, "Your GLB ASCII art", fg=(150, 150, 150))
            console.print(22, 24, "will appear here", fg=(150, 150, 150))
            
            # Example usage code
            console.print(2, 38, "Example usage:", fg=(255, 200, 100))
            console.print(2, 40, "# Convert GLB to ASCII", fg=(120, 120, 120))
            console.print(2, 41, "json_path = convert_and_integrate_glb('model.glb', 'my_model')", fg=(150, 200, 255))
            console.print(2, 42, "", fg=(150, 200, 255))
            console.print(2, 43, "# Load and display in game", fg=(120, 120, 120))
            console.print(2, 44, "renderer = AsciiArtRenderer()", fg=(150, 200, 255))
            console.print(2, 45, "ascii_data = renderer.load_ascii_art(json_path)", fg=(150, 200, 255))
            console.print(2, 46, "renderer.render_ascii_art(console, x, y, ascii_data)", fg=(150, 200, 255))
            
            console.print(2, 50, "Press ESC to exit", fg=(255, 100, 100))
            
            context.present(console)
            
            for event in tcod.event.get():
                if event.type == "QUIT":
                    return
                elif event.type == "KEYDOWN":
                    if event.sym == tcod.event.KeySym.ESCAPE:
                        return


# Integration with your existing game
def add_ascii_art_to_game(console: tcod.console.Console, ascii_renderer: AsciiArtRenderer):
    """Example of how to add ASCII art to your existing game"""
    
    # Example: Display weapon ASCII art in inventory
    # weapon_ascii = ascii_renderer.load_ascii_art("RP/sword_ascii.json")
    # ascii_renderer.render_ascii_art(console, 10, 5, weapon_ascii, (255, 200, 100))
    
    # Example: Display enemy ASCII art
    # enemy_ascii = ascii_renderer.load_ascii_art("RP/dragon_ascii.json")
    # ascii_renderer.render_ascii_art(console, 50, 10, enemy_ascii, (255, 100, 100))
    
    # Example: Display environment objects
    # chest_ascii = ascii_renderer.load_ascii_art("RP/chest_ascii.json")
    # ascii_renderer.render_ascii_art(console, 30, 20, chest_ascii, (200, 150, 100))
    
    pass


if __name__ == "__main__":
    demo_tcod_integration()