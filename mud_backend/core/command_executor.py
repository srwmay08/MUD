# core/command_executor.py
import importlib.util
import os
from typing import List, Tuple, Dict, Any 

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, fetch_room_data, save_game_state
from mud_backend.core.chargen_handler import (
    handle_chargen_input, 
    get_chargen_prompt, 
    do_initial_stat_roll
)
# --- NEW IMPORT ---
from mud_backend.core.room_handler import show_room_to_player

# --- NEW: Master Verb Alias Dictionary ---
# This maps all player commands to the correct verb file.
VERB_ALIASES = {
    # Movement Verbs
    "move": "move",
    "go": "move",
    "n": "move",
    "north": "move",
    "s": "move",
    "south": "move",
    "e": "move",
    "east": "move",
    "w": "move",
    "west": "move",
    "ne": "move",
    "northeast": "move",
    "nw": "move",
    "northwest": "move",
    "se": "move",
    "southeast": "move",
    "sw": "move",
    "southwest": "move",
    
    # Object Interaction Verbs
    "enter": "enter",
    "climb": "climb",
    
    # Exit Verbs
    "exit": "exit",
    "out": "exit",
    
    # Other Verbs
    "look": "look",
    "say": "say",
}

# --- NEW: Full Direction Names ---
# This helps the 'move' verb know what argument to use
DIRECTION_MAP = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}

def execute_command(player_name: str, command_line: str) -> Dict[str, Any]:
    """
    The main function to parse and execute a game command.
    Returns a dictionary with messages and game state.
    """
    
    # 1. Fetch Player Data
    player_db_data = fetch_player_data(player_name)
    
    # 2. Handle New vs. Existing Player
    if not player_db_data:
        start_room_id = "inn_room"
        player = Player(player_name, start_room_id, {})
        player.game_state = "chargen"
        player.chargen_step = 0
        player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
    else:
        player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)

    # 3. Fetch Room Data
    room_db_data = fetch_room_data(player.current_room_id)
    room = Room(
        room_id=room_db_data["room_id"], 
        name=room_db_data["name"], 
        description=room_db_data["description"], 
        db_data=room_db_data
    )

    # 4. --- CHECK GAME STATE ---
    
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command_line.lower() == "look":
            # Show room and trigger first chargen step
            show_room_to_player(player, room)
            do_initial_stat_roll(player) 
            player.chargen_step = 1 
        else:
            handle_chargen_input(player, command_line)
        
    elif player.game_state == "playing":
        # --- NORMAL GAMEPLAY ---
        
        # 1. Parse the command line
        parts = command_line.strip().split()
        if not parts:
            player.send_message("What?")
            return { "messages": player.messages, "game_state": player.game_state }
        
        command = parts[0].lower()
        args = parts[1:]

        # --- NEW: ALIAS-BASED VERB LOGIC ---
        
        # Find the verb file (e.g., "n" -> "move")
        verb_name = VERB_ALIASES.get(command)
        
        # Handle special case for 'move' aliases
        if verb_name == "move":
            if command == "move" or command == "go":
                # Command was "move north" or "go n"
                if not args:
                    player.send_message("Move where?")
                    return { "messages": player.messages, "game_state": player.game_state }
                # Normalize the argument
                arg_direction = args[0].lower()
                normalized_arg = DIRECTION_MAP.get(arg_direction, arg_direction)
                args = [normalized_arg]
            else:
                # Command was "n" or "north"
                normalized_direction = DIRECTION_MAP.get(command, command)
                args = [normalized_direction]
        # --- END NEW LOGIC ---

        # 2. Locate and Import the Verb File
        if not verb_name:
            player.send_message(f"I don't know the command **'{command}'**.")
        else:
            verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
            
            try:
                verb_module_name = f"mud_backend.verbs.{verb_name}"
                spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                verb_class_name = verb_name.capitalize()
                VerbClass = getattr(module, verb_class_name)
                
                # 4. Instantiate and Execute the Verb
                verb_instance = VerbClass(player=player, room=room, args=args)
                verb_instance.execute()
                
            except AttributeError:
                player.send_message(f"Error: The file '{verb_name}.py' is missing the class '{verb_class_name}'.")
            except NotImplementedError as e:
                player.send_message(f"Error in '{verb_name}': {e}")
            except Exception as e:
                player.send_message(f"An unexpected error occurred while running **{verb_name}**: {e}")
    
    # 5. Persist State Changes
    save_game_state(player)

    # 6. Return output to the client
    return {
        "messages": player.messages,
        "game_state": player.game_state
    }


def get_player_object(player_name: str) -> Player:
    """Helper function to load the player object without executing a command."""
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        return Player(player_name, "void") 
    
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    return player