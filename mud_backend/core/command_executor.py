# core/command_executor.py
import importlib  # <-- CHANGED: Use 'importlib' instead of 'importlib.util'
import os
from typing import List, Tuple
from .game_objects import Player, Room
from .db import fetch_player_data, fetch_room_data, save_game_state

def execute_command(player_name: str, command_line: str) -> List[str]:
    """
    The main function to parse and execute a game command.
    Returns a list of messages for the client.
    """
    
    # 1. Parse the command line
    parts = command_line.strip().split()
    if not parts:
        return ["What?"]
    
    verb_name = parts[0].lower()
    args = parts[1:]

    # 2. Fetch Player and Room State
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        return [f"Error: Player '{player_name}' not found."]
    
    # We assume current_room_id exists if the player was found.
    room_db_data = fetch_room_data(player_db_data["current_room_id"])
    
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    
    # --- THIS IS THE FIRST FIX ---
    # We pass the full db_data dict to the Room constructor
    room = Room(room_db_data["room_id"], room_db_data["name"], room_db_data["description"], db_data=room_db_data)

    
    # --- THIS IS THE SECOND FIX ---
    # We now import by module name (e.g., 'mud_backend.verbs.look')
    # This correctly handles all imports within the verb files.
    
    verb_class_name = verb_name.capitalize()
    
    try:
        # Construct the full module name (e.g., "mud_backend.verbs.look")
        module_name = f"mud_backend.verbs.{verb_name}"
        
        # Import the module by its full name
        module = importlib.import_module(module_name)

        # Get the class (e.g., 'Look') from the imported module
        VerbClass = getattr(module, verb_class_name)
        
        # 4. Instantiate and Execute the Verb
        verb_instance = VerbClass(player=player, room=room, args=args)
        verb_instance.execute()
        
    except ModuleNotFoundError:
        # This catches if 'mud_backend.verbs.look' doesn't exist
        player.send_message(f"I don't know the command **'{verb_name}'**.")
    except AttributeError:
        # This catches if the module is found, but the 'Look' class isn't
        player.send_message(f"Error: The file '{verb_name}.py' is missing the class '{verb_class_name}'.")
    except NotImplementedError as e:
        player.send_message(f"Error in '{verb_name}': {e}")
    except Exception as e:
        # Catch any other runtime errors in the verb logic
        player.send_message(f"An unexpected error occurred while running **{verb_name}**: {e}")
    # --- END OF THE SECOND FIX ---


    # 5. Persist State