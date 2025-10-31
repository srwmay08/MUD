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

# --- NEW: Dictionary to map all directions ---
DIRECTION_ALIASES = {
    "n": "north",
    "north": "north",
    "s": "south",
    "south": "south",
    "e": "east",
    "east": "east",
    "w": "west",
    "west": "west",
    "ne": "northeast",
    "northeast": "northeast",
    "nw": "northwest",
    "northwest": "northwest",
    "se": "southeast",
    "southeast": "southeast",
    "sw": "southwest",
    "southwest": "southwest",
}
# ---

def execute_command(player_name: str, command_line: str) -> Dict[str, Any]:
    """
    The main function to parse and execute a game command.
    Returns a dictionary with messages and game state.
    """
    
    # 1. Fetch Player Data
    player_db_data = fetch_player_data(player_name)
    
    # 2. Handle New vs. Existing Player
    if not player_db_data:
        # --- NEW CHARACTER ---
        start_room_id = "inn_room"
        player = Player(player_name, start_room_id, {})
        player.game_state = "chargen"
        player.chargen_step = 0
        player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
        
    else:
        # --- EXISTING CHARACTER ---
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
            player.send_message(f"**{room.name}**")
            player.send_message(room.description)
            do_initial_stat_roll(player) 
            player.chargen_step = 1 # Now waiting for stat roll command
        else:
            handle_chargen_input(player, command_line)
        
    elif player.game_state == "playing":
        # --- NORMAL GAMEPLAY ---
        
        # 1. Parse the command line
        parts = command_line.strip().split()
        if not parts:
            player.send_message("What?")
            return { "messages": player.messages, "game_state": player.game_state }
        
        verb_name = parts[0].lower()
        args = parts[1:]

        # --- NEW: Direction & Move Handling ---
        # Check if the entered verb is a direction
        normalized_direction = DIRECTION_ALIASES.get(verb_name)
        
        if normalized_direction:
            # The command IS a direction. Reroute to 'move' verb.
            verb_name = "move"
            args = [normalized_direction] # e.g., ["north"]
        elif verb_name == "move":
            # The command is "move". We must normalize the argument.
            if not args:
                player.send_message("Move where?")
                return { "messages": player.messages, "game_state": player.game_state }
            
            normalized_arg = DIRECTION_ALIASES.get(args[0].lower())
            if not normalized_arg:
                player.send_message(f"I don't understand the direction '{args[0]}'.")
                return { "messages": player.messages, "game_state": player.game_state }
            
            args = [normalized_arg] # Replace "n" with "north"
        # --- END NEW HANDLING ---

        # 2. Locate and Import the Verb File
        verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
        
        if not os.path.exists(verb_file_path):
            player.send_message(f"I don't know the command **'{verb_name}'**.")
        else:
            try:
                # Dynamically import the module
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