# core/command_executor.py
import importlib.util
import os
# --- THIS IMPORT IS NEW ---
from typing import List, Tuple, Dict, Any 

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, fetch_room_data, save_game_state
from mud_backend.core.chargen_handler import handle_chargen_input, get_chargen_prompt

# --- THE TYPE HINT IS NOW 'dict' ---
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
        start_room_id = "inn_room" # New starting room
        player = Player(player_name, start_room_id, {})
        
        # --- SET CHARGEN STATE ---
        player.game_state = "chargEN" # NOTE: Your client expects "chargen"
        player.chargen_step = 0
        
        # Send welcome message
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
    # This is the most important new logic
    
    if player.game_state == "chargen":
        # If in chargen, send input to the chargen handler
        # We ignore the 'command_line' if it's the very first login step
        if player.chargen_step == 0 and command_line.lower() == "look":
            # This is the auto-look from the frontend, show the first question
            player.send_message(f"**{room.name}**")
            player.send_message(room.description)
            get_chargen_prompt(player)
        else:
            # This is an answer to a question
            handle_chargen_input(player, command_line)
        
    elif player.game_state == "playing":
        # --- NORMAL GAMEPLAY ---
        
        # 1. Parse the command line
        parts = command_line.strip().split()
        if not parts:
            player.send_message("What?")
            # --- MUST RETURN A DICT HERE TOO ---
            return { "messages": player.messages, "game_state": player.game_state }
        
        verb_name = parts[0].lower()
        args = parts[1:]

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

    # 6. --- THIS IS THE FIX ---
    # Return a dictionary containing the messages AND the current game state
    return {
        "messages": player.messages,
        "game_state": player.game_state
    }