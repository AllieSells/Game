import tcod
import traceback
import random
import math
import sys
import os

# Add the current directory to path to import our GLB converter
sys.path.append(os.path.dirname(__file__))
from glb_to_ascii import GLBToASCII, AsciiArtConfig
from tcod_ascii_integration import AsciiArtRenderer

def main() -> None:
    screen_width = 250
    screen_height = 100
    print(f"Console size: {screen_width}x{screen_height}")
    
    # Player position
    player_x, player_y = 10, 10
    
    # Initialize GLB to ASCII converter
    ascii_renderer = AsciiArtRenderer()
    sphere_ascii_data = None
    config = None
    converter = None
    sphere_path = None
    
    # Convert the sphere GLB to ASCII
    try:
        config = AsciiArtConfig(
            width=40,
            height=20,
            ascii_chars="@%#*+=~-:. ",
            use_shading=True,
            camera_elevation=30.0,
            camera_azimuth=45.0,
            light_elevation=45.0,
            light_azimuth=135.0,
            light_intensity=1.0,
            ambient_light=0.2,
            use_shadows=True
        )
        converter = GLBToASCII(config)
        sphere_path = os.path.join(os.path.dirname(__file__), "sphere.glb")
        ascii_lines = converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
        print("✓ Successfully loaded sphere.glb as ASCII art")
    except Exception as e:
        print(f"Could not load sphere.glb: {e}")
        sphere_ascii_data = None
    
    # Camera controls for the 3D model
    camera_elevation = 30.0
    camera_azimuth = 45.0
    show_ascii = True
    
    # Lighting controls
    light_elevation = 45.0
    light_azimuth = 135.0
    light_intensity = 1.0
    ambient_light = 0.2
    use_shadows = True

    tileset = tcod.tileset.load_tilesheet(
        "RP/AllieClassic.png", 16, 16, tcod.tileset.CHARMAP_CP437
    )

    with tcod.context.new_terminal(
        screen_width,
        screen_height,
        tileset=tileset,
        title="ASCII Playground - 250x250",
        vsync=True,
        sdl_window_flags=tcod.context.SDL_WINDOW_FULLSCREEN,
    ) as context:
        console = tcod.console.Console(screen_width, screen_height, order="F")
        try:
            while True:
                console.clear()
                
                # Draw some basic content
                console.print(1, 1, "ASCII Playground - WASD: move, Q/E: tilt, R: rotate, Z/X/C/V: light, T: toggle, ESC: quit", fg=(255, 255, 255))
                
                # Display model controls
                console.print(1, 2, f"Model: {'ON' if show_ascii and sphere_ascii_data else 'OFF'} | Elevation: {camera_elevation:.0f}° | Azimuth: {camera_azimuth:.0f}°", fg=(200, 200, 200))
                console.print(1, 3, f"Light: Elev {light_elevation:.0f}° | Azim {light_azimuth:.0f}° | Intensity {light_intensity:.1f} | Shadows: {'ON' if use_shadows else 'OFF'}", fg=(150, 200, 255))
                
                # Draw border
                for x in range(screen_width):
                    console.print(x, 0, "#", fg=(100, 100, 100))
                    console.print(x, screen_height-1, "#", fg=(100, 100, 100))
                for y in range(screen_height):
                    console.print(0, y, "#", fg=(100, 100, 100))
                    console.print(screen_width-1, y, "#", fg=(100, 100, 100))
                
                # Draw some random stuff for testing
                for i in range(20):
                    x = random.randint(5, screen_width-5)
                    y = random.randint(5, screen_height-5)
                    char = random.choice("*+.,:;~")
                    color = (random.randint(50, 255), random.randint(50, 255), random.randint(50, 255))
                    console.print(x, y, char, fg=color)
                
                # Draw the GLB ASCII art if available
                if show_ascii and sphere_ascii_data:
                    try:
                        # Position the sphere ASCII art in the center-right area
                        sphere_x = screen_width // 2 + 20
                        sphere_y = screen_height // 2 - 10
                        
                        # Use a nice color for the sphere
                        ascii_renderer.render_ascii_art(
                            console, sphere_x, sphere_y, sphere_ascii_data,
                            main_color=(100, 200, 255)  # Light blue
                        )
                        
                        # Add a label and light direction indicator
                        console.print(sphere_x + 5, sphere_y - 2, "3D Sphere (GLB)", fg=(150, 150, 150))
                        
                        # Show light direction with an arrow/indicator
                        light_indicator_x = int(sphere_x + 20 + 8 * math.cos(math.radians(light_azimuth)))
                        light_indicator_y = int(sphere_y + 10 + 4 * math.sin(math.radians(light_elevation)))
                        
                        # Clamp to screen bounds
                        light_indicator_x = max(1, min(screen_width-2, light_indicator_x))
                        light_indicator_y = max(1, min(screen_height-2, light_indicator_y))
                        
                        console.print(light_indicator_x, light_indicator_y, "☀", fg=(255, 255, 100))  # Light source
                        console.print(light_indicator_x-1, light_indicator_y+1, "Light", fg=(200, 200, 100))
                        
                    except Exception as e:
                        console.print(5, screen_height - 10, f"Error rendering sphere: {str(e)[:50]}", fg=(255, 100, 100))
                
                # Draw player
                console.print(player_x, player_y, "@", fg=(255, 255, 0))
                
                context.present(console)

                try:
                    for event in tcod.event.get():
                        context.convert_event(event)
                        if event.type == "QUIT":
                            raise SystemExit()
                        elif event.type == "KEYDOWN":
                            if event.sym == tcod.event.KeySym.ESCAPE:
                                raise SystemExit()
                            elif event.sym == tcod.event.KeySym.W and player_y > 1:
                                player_y -= 1
                            elif event.sym == tcod.event.KeySym.S and player_y < screen_height - 2:
                                player_y += 1
                            elif event.sym == tcod.event.KeySym.A and player_x > 1:
                                player_x -= 1
                            elif event.sym == tcod.event.KeySym.D and player_x < screen_width - 2:
                                player_x += 1
                            # GLB model controls
                            elif event.sym == tcod.event.KeySym.Q:  # Rotate elevation up
                                camera_elevation = min(90, camera_elevation + 15)
                                if sphere_ascii_data and config:
                                    try:
                                        new_config = AsciiArtConfig(
                                            width=40, height=20, ascii_chars="@%#*+=~-:. ",
                                            use_shading=True, camera_elevation=camera_elevation, camera_azimuth=camera_azimuth,
                                            light_elevation=light_elevation, light_azimuth=light_azimuth,
                                            light_intensity=light_intensity, ambient_light=ambient_light, use_shadows=use_shadows
                                        )
                                        new_converter = GLBToASCII(new_config)
                                        ascii_lines = new_converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
                                        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
                                        print(f"Tilted up to {camera_elevation}°")
                                    except: pass
                            elif event.sym == tcod.event.KeySym.E:  # Rotate elevation down
                                camera_elevation = max(-90, camera_elevation - 15)
                                if sphere_ascii_data and config:
                                    try:
                                        new_config = AsciiArtConfig(
                                            width=40, height=20, ascii_chars="@%#*+=~-:. ",
                                            use_shading=True, camera_elevation=camera_elevation, camera_azimuth=camera_azimuth,
                                            light_elevation=light_elevation, light_azimuth=light_azimuth,
                                            light_intensity=light_intensity, ambient_light=ambient_light, use_shadows=use_shadows
                                        )
                                        new_converter = GLBToASCII(new_config)
                                        ascii_lines = new_converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
                                        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
                                        print(f"Tilted down to {camera_elevation}°")
                                    except: pass
                            elif event.sym == tcod.event.KeySym.R:  # Rotate azimuth
                                camera_azimuth = (camera_azimuth + 30) % 360
                                if sphere_ascii_data and config:
                                    try:
                                        new_config = AsciiArtConfig(
                                            width=40, height=20, ascii_chars="@%#*+=~-:. ",
                                            use_shading=True, camera_elevation=camera_elevation, camera_azimuth=camera_azimuth,
                                            light_elevation=light_elevation, light_azimuth=light_azimuth,
                                            light_intensity=light_intensity, ambient_light=ambient_light, use_shadows=use_shadows
                                        )
                                        new_converter = GLBToASCII(new_config)
                                        ascii_lines = new_converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
                                        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
                                        print(f"Rotated to {camera_azimuth}°")
                                    except: pass
                            elif event.sym == tcod.event.KeySym.T:  # Toggle ASCII art display
                                show_ascii = not show_ascii
                                print(f"Model display: {'ON' if show_ascii else 'OFF'}")
                            
                            # Light controls
                            elif event.sym == tcod.event.KeySym.Z:  # Light elevation up
                                light_elevation = min(90, light_elevation + 15)
                                if sphere_ascii_data:
                                    try:
                                        new_config = AsciiArtConfig(
                                            width=40, height=20, ascii_chars="@%#*+=~-:. ",
                                            use_shading=True, camera_elevation=camera_elevation, camera_azimuth=camera_azimuth,
                                            light_elevation=light_elevation, light_azimuth=light_azimuth,
                                            light_intensity=light_intensity, ambient_light=ambient_light, use_shadows=use_shadows
                                        )
                                        new_converter = GLBToASCII(new_config)
                                        ascii_lines = new_converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
                                        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
                                        print(f"Light elevated to {light_elevation}°")
                                    except: pass
                            elif event.sym == tcod.event.KeySym.X:  # Light elevation down
                                light_elevation = max(-90, light_elevation - 15)
                                if sphere_ascii_data:
                                    try:
                                        new_config = AsciiArtConfig(
                                            width=40, height=20, ascii_chars="@%#*+=~-:. ",
                                            use_shading=True, camera_elevation=camera_elevation, camera_azimuth=camera_azimuth,
                                            light_elevation=light_elevation, light_azimuth=light_azimuth,
                                            light_intensity=light_intensity, ambient_light=ambient_light, use_shadows=use_shadows
                                        )
                                        new_converter = GLBToASCII(new_config)
                                        ascii_lines = new_converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
                                        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
                                        print(f"Light lowered to {light_elevation}°")
                                    except: pass
                            elif event.sym == tcod.event.KeySym.C:  # Light azimuth rotate
                                light_azimuth = (light_azimuth + 30) % 360
                                if sphere_ascii_data:
                                    try:
                                        new_config = AsciiArtConfig(
                                            width=40, height=20, ascii_chars="@%#*+=~-:. ",
                                            use_shading=True, camera_elevation=camera_elevation, camera_azimuth=camera_azimuth,
                                            light_elevation=light_elevation, light_azimuth=light_azimuth,
                                            light_intensity=light_intensity, ambient_light=ambient_light, use_shadows=use_shadows
                                        )
                                        new_converter = GLBToASCII(new_config)
                                        ascii_lines = new_converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
                                        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
                                        print(f"Light rotated to {light_azimuth}°")
                                    except: pass
                            elif event.sym == tcod.event.KeySym.V:  # Toggle shadows
                                use_shadows = not use_shadows
                                if sphere_ascii_data:
                                    try:
                                        new_config = AsciiArtConfig(
                                            width=40, height=20, ascii_chars="@%#*+=~-:. ",
                                            use_shading=True, camera_elevation=camera_elevation, camera_azimuth=camera_azimuth,
                                            light_elevation=light_elevation, light_azimuth=light_azimuth,
                                            light_intensity=light_intensity, ambient_light=ambient_light, use_shadows=use_shadows
                                        )
                                        new_converter = GLBToASCII(new_config)
                                        ascii_lines = new_converter.convert_glb_to_ascii(sphere_path, "sphere_ascii.json")
                                        sphere_ascii_data = ascii_renderer.load_ascii_art("sphere_ascii.json")
                                        print(f"Shadows: {'ON' if use_shadows else 'OFF'}")
                                    except: pass
                except Exception: # handles game exceptions
                    traceback.print_exc() #prints error to stderr

        except SystemExit: # save and quit
            raise
        except BaseException: # Save on any other unexpected exception
            raise


if __name__ == "__main__":
    main()
