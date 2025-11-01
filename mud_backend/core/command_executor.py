# core/command_executor.py
import importlib.util
import os
import time 
import datetime 
from typing import List, Tuple, Dict, Any 

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, fetch_room_data, save_game_state
from mud_backend.core.chargen_handler import (
    handle_chargen_input, 
    get_chargen_prompt, 
    do_initial_stat_roll
)
from mud_backend.core.room_handler import show_room_to_player

# --- Import our new game state and loop functions ---
from mud_backend.core import game_state
from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
from mud_backend.core import combat_system # monster_respawn needs this
# ---

# This maps all player commands to the correct verb file.
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
    
    # --- NEW PING VERB ---
    "ping": ("ping", "Ping"),
}

# This map is used to convert "n" to "north"
DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    # Add full names so they map to themselves
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}


# ---
# NEW FUNCTION: THE GAME TICK
# ---
def _check_and_run_game_tick(current_player: Player):
    """
    Checks if enough time has passed and runs the global game tick
    for environment and respawns.
    """
    current_time = time.time()
    
    # Check if TICK_INTERVAL_SECONDS have passed
    if (current_time - game_state.LAST_GAME_TICK_TIME) > game_state.TICK_INTERVAL_SECONDS:
        
        # --- IT'S TIME TO TICK! ---
        game_state.LAST_GAME_TICK_TIME = current_time
        
        # We don't have a full active player list, but we can
        # create a temporary one with just the player who triggered the tick.
        # This allows environment to send them messages.
        # A more advanced server would track all active players.
        temp_active_players = {current_player.name: current_player}
        
        # Create a log prefix
        log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        log_prefix = f"{log_time} - GAME_TICK"
        print(f"{log_prefix}: Running global tick...")

        # 1. Update Environment (Time/Weather)
        # Note: We create a dummy broadcast_callback for now
        def broadcast_to_room(room_id, message, type):
            # In a real setup, this would find all players in room_id
            # and send them the message.
            if current_player.current_room_id == room_id:
                current_player.send_message(message)

        # TODO: game_tick_counter isn't tracked, just pass 1
        environment.update_environment_state(
            game_tick_counter=1,
            active_players_dict=temp_active_players,
            log_time_prefix=log_prefix,
            broadcast_callback=broadcast_to_room
        )

        # 2. Update Monster Respawns
        # TODO: Pass real global data
        monster_respawn.process_respawns(
            log_time_prefix=log_prefix,
            current_time_utc=datetime.datetime.now(datetime.timezone.utc),
            tracked_defeated_entities_dict=game_state.DEFEATED_MONSTERS, # Using this as a proxy
            game_rooms_dict=game_state.GAME_ROOMS,
            game_npcs_dict={}, # TODO: Pass real data
            game_monster_templates_dict={}, # TODO: Pass real data
            broadcast_callback=broadcast_to_room,
            recently_defeated_targets_dict=combat_system.RUNTIME_ENTITY_HP, # Needs a better name
            game_equipment_tables_global={}, # TODO: Pass real data
            game_items_global={} # TODO: Pass real data
        )
        
        print(f"{log_prefix}: Global tick complete.")

# ---
# UPDATED EXECUTE_COMMAND
# ---
def execute_command(player_name: str, command_line: str) -> Dict[str, Any]:
    """
    The main function to parse and execute a game command.
    """
    
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

    # ---
    # 3. RUN THE GAME TICK
    # ---
    # This runs *before* the player's command.
    # It checks the global timer and runs all tick logic if needed.
    # We pass the current player so they can receive ambient messages.
    _check_and_run_game_tick(player)
    # ---

    # 4. Fetch Room Data (NOW FROM CACHE)
    # ---
    room_db_data = game_state.GAME_ROOMS.get(player.current_room_id)
    if not room_db_data:
        # Fallback to DB if cache fails (e.g., new room added)
        print(f"[WARN] Room {player.current_room_id} not in cache! Fetching from DB.")
        room_db_data = fetch_room_data(player.current_room_id)
        if room_db_data and room_db_data.get("room_id") != "void":
            game_state.GAME_ROOMS[player.current_room_id] = room_db_data # Add to cache
            
    room = Room(
        room_id=room_db_data.get("room_id", "void"), 
        name=room_db_data.get("name", "The Void"), 
        description=room_db_data.get("description", "..."), 
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

    # 5. --- CHECK GAME STATE ---
    
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command_line.lower() == "look":
            show_room_to_player(player, room)
            do_initial_stat_roll(player) 
            player.chargen_step = 1 
        else:
            handle_chargen_input(player, command_line)
        
    elif player.game_state == "playing":
        # --- NORMAL GAMEPLAY ---
        
        parts = command_line.strip().split()
        if not parts:
            # Silently allow empty commands (for the "ping")
            if command_line.lower() != "ping":
                player.send_message("What?")
            return { "messages": player.messages, "game_state": player.game_state }
        
        command = parts[0].lower()
        args = parts[1:]

        # --- UPDATED: ALIAS-BASED VERB LOGIC ---
        
        # Find the verb file and class name from the new mapping
        verb_info = VERB_ALIASES.get(command)
        
        if not verb_info:
            player.send_message(f"I don't know the command **'{command}'**.")
        else:
            # Unpack the tuple
            verb_name, verb_class_name = verb_info
        
            # Special argument handling
            if verb_class_name == "Move":
                if command in DIRECTION_MAP:
                    args = [DIRECTION_MAP[command]]
            elif verb_class_name == "Exit":
                if command == "out":
                    args = []
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

                VerbClass = getattr(module, verb_class_name)
                
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
    
    # 6. Persist State Changes
    save_game_state(player)

    # 7. Return output to the client
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