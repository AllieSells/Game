@echo off
echo Building MyGame with PyInstaller...

REM Install PyInstaller if not already installed
pip install pyinstaller

REM Clean previous builds
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM Build the game
pyinstaller MyGame.spec

echo.
echo Build complete!
echo Executable can be found in: dist\MyGame\MyGame.exe
echo.
pause