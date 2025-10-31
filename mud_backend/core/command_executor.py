# core/command_executor.py
import importlib.util
import os
from typing import List, Tuple

# Imports are all absolute, which is correct
from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, fetch_room_data, save_game_state

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
    
    room_db_data = fetch_room_data(player_db_data["current_room_id"])
    
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    room = Room(room_db_data["room_id"], room_db_data["name"], room_db_data["description"])

    # 3. Locate and Import the Verb File
    verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
    
    if not os.path.exists(verb_file_path):
        player.send_message(f"I don't know the command **'{verb_name}'**.")
    else:
        try:
            # --- THIS IS THE KEY FIX ---
            # We must tell importlib the FULL package path for the module,
            # not just the verb_name (e.g., "mud_backend.verbs.look")
            verb_module_name = f"mud_backend.verbs.{verb_name}"
            
            # Now, load the spec using the full name and file path
            spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
            # ---------------------
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # The class name is typically the verb name capitalized (e.g., 'look' -> 'Look')
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
            # Catch any other runtime errors in the verb logic
            player.send_message(f"An unexpected error occurred while running **{verb_name}**: {e}")


    # 5. Persist State Changes
    save_game_state(player)

    # 6. Return output to the client
    return player.messages


def get_player_object(player_name: str) -> Player:
    """Helper function to load the player object without executing a command."""
    
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        # Fallback to a blank player if not found
        return Player(player_name, "void") 
    
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    return player