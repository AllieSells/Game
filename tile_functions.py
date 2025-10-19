"""
Tile interaction functions for different tile types.
These functions handle what happens when tiles are interacted with.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine import Engine
    from entity import Actor

import tile_types
import color

def open_door(engine: "Engine", actor: "Actor", x: int, y: int) -> Optional[str]:
    """
    Open a closed door at the given coordinates.
    Returns a message string if successful, None if failed.
    """
    try:
        # Check if the tile is actually a closed door
        current_tile = engine.game_map.tiles[x, y]
        if not (hasattr(current_tile, 'dtype') and 
                current_tile['name'] == "Door"):
            return None
        
        # Change the tile to an open door
        engine.game_map.tiles[x, y] = tile_types.open_door
        
        # Add message to log, if visible to the player
        #if engine.game_map.visible[x, y]:
        #    message = f"{actor.name} opens the door."
        #    if hasattr(engine, 'message_log'):
        #        engine.message_log.add_message(message, color.grey)
        
        return message
        
    except Exception as e:
        return None

def close_door(engine: "Engine", actor: "Actor", x: int, y: int) -> Optional[str]:
    """
    Close an open door at the given coordinates.
    Returns a message string if successful, None if failed.
    """
    try:
        # Check if the tile is actually an open door
        current_tile = engine.game_map.tiles[x, y]
        if not (hasattr(current_tile, 'dtype') and 
                current_tile['name'] == "Open Door"):
            return None
        
        # Check if there's an entity blocking the door
        blocking_entity = engine.game_map.get_blocking_entity_at_location(x, y)
        if blocking_entity:
            return None
        
        # Change the tile to a closed door
        engine.game_map.tiles[x, y] = tile_types.closed_door
        
        # Add message to log, only if visible to the player
        #if engine.game_map.visible[x, y]:
        #    message = f"{actor.name} closes the door."
        #    if hasattr(engine, 'message_log'):
        #        engine.message_log.add_message(message, color.grey)
        
        return message
        
    except Exception as e:
        return None

def toggle_door(engine: "Engine", actor: "Actor", x: int, y: int) -> Optional[str]:
    """
    Toggle a door between open and closed states.
    Returns a message string if successful, None if failed.
    """
    try:
        current_tile = engine.game_map.tiles[x, y]
        tile_name = current_tile['name'] if hasattr(current_tile, 'dtype') else None
        
        if tile_name == "Door":
            return open_door(engine, actor, x, y)
        elif tile_name == "Open Door":
            return close_door(engine, actor, x, y)
        else:
            return None
            
    except Exception:
        return None

# Dictionary mapping tile names to their interaction functions
TILE_FUNCTIONS = {
    "Door": lambda engine, actor, x, y: open_door(engine, actor, x, y),
    "Open Door": lambda engine, actor, x, y: close_door(engine, actor, x, y),
    # Add more tile functions here as needed
    # "Lever": lambda engine, actor, x, y: toggle_lever(engine, actor, x, y),
    # "Chest": lambda engine, actor, x, y: open_chest(engine, actor, x, y),
}

def get_tile_function(tile_name: str):
    """Get the interaction function for a given tile name."""
    return TILE_FUNCTIONS.get(tile_name, None)

def interact_with_tile(engine: "Engine", actor: "Actor", x: int, y: int) -> Optional[str]:
    """
    General function to interact with any tile at the given coordinates.
    Returns a message string if successful, None if no interaction available.
    """
    try:
        current_tile = engine.game_map.tiles[x, y]
        tile_name = current_tile['name'] if hasattr(current_tile, 'dtype') else None
        
        if not tile_name:
            return None
        
        tile_function = get_tile_function(tile_name)
        if tile_function:
            return tile_function(engine, actor, x, y)
        else:
            return None
            
    except Exception:
        return None