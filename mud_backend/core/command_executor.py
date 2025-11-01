# core/command_executor.py
import importlib.util
import os
# --- UPDATED TYPING ---
from typing import List, Tuple, Dict, Any 

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, fetch_room_data, save_game_state
from mud_backend.core.chargen_handler import (
    handle_chargen_input, 
    get_chargen_prompt, 
    do_initial_stat_roll
)
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core import game_state

# ---
# NEW VERB_ALIASES MAPPING
# ---
# This dictionary now maps a command string to a TUPLE:
# (filename, ClassName)
# This allows us to group multiple classes in one file.
#
VERB_ALIASES: Dict[str, Tuple[str, str]] = {
    # Movement Verbs (all in 'movement.py')
    "move": ("movement", "Move"),
    "go": ("movement", "Move"),
    "n": ("movement", "Move"),
    "north": ("movement", "Move"),
    "s": ("movement", "Move"),
    "south": ("movement", "Move"),
    "e": ("movement", "Move"),
    "east": ("movement", "Move"),
    "w": ("movement", "Move"),
    "west": ("movement", "Move"),
    "ne": ("movement", "Move"),
    "northeast": ("movement", "Move"),
    "nw": ("movement", "Move"),
    "northwest": ("movement", "Move"),
    "se": ("movement", "Move"),
    "southeast": ("movement", "Move"),
    "sw": ("movement", "Move"),
    "southwest": ("movement", "Move"),
    
    # Object Interaction Verbs
    "enter": ("movement", "Enter"),
    "climb": ("movement", "Climb"),
    
    # Observation Verbs (all in 'observation.py')
    "examine": ("observation", "Examine"),
    "investigate": ("observation", "Investigate"),
    "search": ("observation", "Investigate"), # Alias
    "look": ("observation", "Look"),

    # Combat Verbs
    "attack": ("attack", "Attack"),
    
    # Exit Verbs
    "exit": ("movement", "Exit"),
    "out": ("movement", "Exit"),
    
    # Other Verbs
    "say": ("say", "Say"),
}

# This map is still needed for the 'move' verb logic
DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}

def execute_command(player_name: str, command_line: str) -> Dict[str, Any]:
    """
    The main function to parse and execute a game command.
    Returns a dictionary with messages and game state.
    """
    
    # ... (Steps 1, 2, 3: Fetching Player, Room, and filtering monsters are unchanged) ...
    
    # 1. Fetch Player Data
    player_db_data = fetch_player_data(player_name)
    
    # 2. Handle New vs. Existing Player
    if not player_db_data:
        start_room_id = "inn_room"
        player = Player(player_name, start_room_id, {})
        player.game_state = "chargen"
        player.chargen_step = 0
        player.hp = 100
        player.max_hp = 100
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

    # Filter defeated monsters
    active_monsters = []
    for obj in room.objects:
        monster_id = obj.get("monster_id")
        if monster_id:
            if monster_id in game_state.DEFEATED_MONSTERS:
                pass
            else:
                active_monsters.append(obj)
        else:
            active_monsters.append(obj)
    room.objects = active_monsters

    # 4. --- CHECK GAME STATE ---
    
    if player.game_state == "chargEN":
        # ... (Chargen logic is unchanged) ...
        if player.chargen_step == 0 and command_line.lower() == "look":
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

        # ---
        # UPDATED VERB LOADING LOGIC
        # ---
        
        # 2. Find the verb file and class name from the new mapping
        verb_info = VERB_ALIASES.get(command)
        
        if not verb_info:
            player.send_message(f"I don't know the command **'{command}'**.")
        else:
            # Unpack the tuple
            verb_name, verb_class_name = verb_info
        
            # 3. Special argument handling (THIS LOGIC IS UPDATED)
            # We check the ClassName, not the filename
            if verb_class_name == "Move":
                if command in DIRECTION_MAP:
                    # Command was "n" or "north". Set args to ["north"]
                    args = [DIRECTION_MAP[command]]
                else:
                    # Command was "move" or "go". Args are already set
                    pass 
            elif verb_class_name == "Exit":
                if command == "out":
                    # Command was "out". Set args to empty list.
                    args = []
                else:
                    # Command was "exit". Args are already set
                    pass
            # --- END UPDATED LOGIC ---

            # 4. Locate and Import the Verb File
            verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
            
            try:
                verb_module_name = f"mud_backend.verbs.{verb_name}"
                spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
                
                if spec is None:
                     raise FileNotFoundError(f"Verb file not found at {verb_file_path}")
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 5. Get the class from the module
                # We use the specific verb_class_name from our alias map
                VerbClass = getattr(module, verb_class_name)
                
                # 6. Instantiate and Execute the Verb
                verb_instance = VerbClass(player=player, room=room, args=args)
                verb_instance.execute()
                
            except FileNotFoundError:
                 player.send_message(f"Server Error: The verb file '{verb_name}.py' is missing.")
            except AttributeError:
                player.send_message(f"Error: The file '{verb_name}.py' is missing the class '{verb_class_name}'.")
            except NotImplementedError as e:
                player.send_message(f"Error in '{verb_name}': {e}")
            except Exception as e:
                player.send_message(f"An unexpected error occurred while running **{command}**: {e}")
                # Log the full error for debugging
                print(f"Full error for command '{command}': {e}")
    
    # 5. Persist State Changes
    save_game_state(player)

    # 6. Return output to the client
    return {
        "messages": player.messages,
        "game_state": player.game_state
    }


def get_player_object(player_name: str) -> Player:
    # ... (This function is unchanged) ...
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        return Player(player_name, "void") 
    
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    return player