#!/usr/bin/env python3
"""
Build script for MyGame using PyInstaller
"""
import os
import shutil
import subprocess
import sys

def main():
    print("Building MyGame with PyInstaller...")
    
    # Install PyInstaller if needed
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Clean previous builds
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            print(f"Cleaning {folder}...")
            shutil.rmtree(folder)
    
    # Build the game
    print("Building executable...")
    result = subprocess.run([sys.executable, "-m", "PyInstaller", "MyGame.spec"])
    
    if result.returncode == 0:
        print("\nBuild complete!")
        if os.name == 'nt':  # Windows
            print("Executable: dist\\MyGame\\MyGame.exe")
        else:
            print("Executable: dist/MyGame/MyGame")
    else:
        print("\nBuild failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()