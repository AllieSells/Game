"""
Test script to demonstrate GLB to ASCII conversion
Run this to see how the converter works
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from glb_to_ascii import GLBToASCII, AsciiArtConfig


def test_with_simple_model():
    """Test the converter with a basic setup"""
    
    # Configure the ASCII art settings
    config = AsciiArtConfig(
        width=60,          # Width of ASCII art
        height=30,         # Height of ASCII art
        ascii_chars="@%#*+=~-:. ",  # Characters to use (dense to sparse)
        use_shading=True,  # Use lighting/shading
        camera_elevation=30.0,  # Camera angle up/down
        camera_azimuth=45.0     # Camera angle left/right
    )
    
    converter = GLBToASCII(config)
    
    print("GLB to ASCII Converter Test")
    print("=" * 50)
    
    # Check if we can find any GLB files in the current directory
    glb_files = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.lower().endswith('.glb'):
                glb_files.append(os.path.join(root, file))
    
    if glb_files:
        print(f"Found {len(glb_files)} GLB file(s):")
        for glb_file in glb_files:
            print(f"  - {glb_file}")
        
        # Use the first GLB file found
        glb_path = glb_files[0]
        print(f"\nTesting with: {glb_path}")
        
        try:
            # Convert to ASCII
            ascii_lines = converter.convert_glb_to_ascii(glb_path)
            
            print("\n" + "="*60)
            print("ASCII ART RESULT:")
            print("="*60)
            
            for line in ascii_lines:
                print(line)
            
            print("="*60)
            
            # Save to file for TCOD use
            output_path = "test_model_ascii.json"
            converter.save_to_tcod_format(ascii_lines, output_path)
            print(f"\nSaved ASCII art to: {output_path}")
            
        except Exception as e:
            print(f"Error converting GLB: {e}")
            print("Make sure the GLB file is valid and accessible.")
    
    else:
        print("No GLB files found in the current directory.")
        print("\nTo test the converter:")
        print("1. Download a GLB model file (free models available at:")
        print("   - https://sketchfab.com/3d-models/categories/animals-pets?features=downloadable&sort_by=-likeCount")
        print("   - https://github.com/KhronosGroup/glTF-Sample-Models/tree/master/2.0")
        print("2. Place the .glb file in this folder")
        print("3. Run this script again")
        
        # Create a demo with basic shapes instead
        create_demo_ascii()


def create_demo_ascii():
    """Create a simple ASCII art demo without GLB file"""
    print("\n" + "="*50)
    print("DEMO ASCII ART (without GLB file):")
    print("="*50)
    
    # Simple ASCII art example
    demo_art = [
        "                    @@@@@@@@@@                    ",
        "                  @@%%%%%%%%%#@@                  ",
        "                @@%%%%%%%%%%%%%#@@                ",
        "              @@%%%%%%%%%%%%%%%%%#@@              ",
        "            @@%%%%%%%%%%%%%%%%%%%%#*@@            ",
        "          @@%%%%%%%%%%%%%%%%%%%%%%#*+=@@          ",
        "        @@%%%%%%%%%%%%%%%%%%%%%%%%#*+=--@@        ",
        "      @@%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::@@      ",
        "    @@%%%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::..@@    ",
        "  @@%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::.  @@  ",
        "@@%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::.    @@",
        "@@%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::.    @@",
        "@@%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::.    @@",
        "  @@%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::.  @@  ",
        "    @@%%%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::..@@    ",
        "      @@%%%%%%%%%%%%%%%%%%%%%%%%%%#*+=--::@@      ",
        "        @@%%%%%%%%%%%%%%%%%%%%%%%%#*+=--@@        ",
        "          @@%%%%%%%%%%%%%%%%%%%%%%#*+=@@          ",
        "            @@%%%%%%%%%%%%%%%%%%%%#*@@            ",
        "              @@%%%%%%%%%%%%%%%%%#@@              ",
        "                @@%%%%%%%%%%%%%#@@                ",
        "                  @@%%%%%%%%%#@@                  ",
        "                    @@@@@@@@@@                    "
    ]
    
    for line in demo_art:
        print(line)
    
    print("="*50)
    print("This is what your GLB models will look like!")
    print("The characters '@%#*+=~-:.' represent depth/lighting")


def quick_start_instructions():
    """Print quick start instructions"""
    print("\n" + "="*50)
    print("QUICK START GUIDE:")
    print("="*50)
    
    print("1. GET A GLB MODEL:")
    print("   - Download from Sketchfab, GitHub, or create in Blender")
    print("   - Place the .glb file in this folder")
    
    print("\n2. BASIC CONVERSION:")
    print("   from glb_to_ascii import GLBToASCII, AsciiArtConfig")
    print("   ")
    print("   config = AsciiArtConfig(width=60, height=30)")
    print("   converter = GLBToASCII(config)")
    print("   ascii_lines = converter.convert_glb_to_ascii('your_model.glb')")
    
    print("\n3. USE IN YOUR TCOD GAME:")
    print("   # Load the ASCII art")
    print("   from tcod_ascii_integration import AsciiArtRenderer")
    print("   renderer = AsciiArtRenderer()")
    print("   ascii_data = renderer.load_ascii_art('model_ascii.json')")
    print("   ")
    print("   # Render in your game loop")
    print("   renderer.render_ascii_art(console, x, y, ascii_data, (255, 255, 255))")
    
    print("\n4. CUSTOMIZE:")
    print("   - Change width/height for different sizes")
    print("   - Modify ascii_chars for different styles")
    print("   - Adjust camera angles for better views")
    print("   - Use different colors in TCOD rendering")


if __name__ == "__main__":
    test_with_simple_model()
    quick_start_instructions()