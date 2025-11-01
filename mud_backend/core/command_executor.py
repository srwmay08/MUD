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
    "southeast": ("movement", "Move"), # <-- FIX: Removed the stray 'V'
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
    
    # --- UPDATED TICK VERB ---
    "ping": ("tick", "Tick"),
}

# This map is used to convert "n" to "north"
DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}


# ---
# UPDATED FUNCTION: Prune Stale Players
# ---
def _prune_active_players(log_prefix: str, broadcast_callback):
    """
    Removes players from ACTIVE_PLAYERS if they haven't
    been seen in PLAYER_TIMEOUT_SECONDS.
    """
    current_time = time.time()
    stale_sids = []
    
    for sid, data in game_state.ACTIVE_PLAYERS.items():
        if (current_time - data["last_seen"]) > game_state.PLAYER_TIMEOUT_SECONDS:
            stale_sids.append(sid)
            
    if stale_sids:
        for sid in stale_sids:
            player_info = game_state.ACTIVE_PLAYERS.pop(sid, None)
            if player_info:
                room_id = player_info.get("current_room_id", "unknown")
                player_name = player_info.get("player_name", "Unknown")
                # Send broadcast via the callback
                broadcast_callback(room_id, f"{player_name} disappears.", "ambient")
                print(f"{log_prefix}: Pruned stale player {player_name} from room {room_id}.")

# ---
# UPDATED FUNCTION: THE GAME TICK
# ---
def _check_and_run_game_tick(dummy_player, broadcast_callback):
    """
    Checks if enough time has passed and runs the global game tick.
    This is now called by a background thread.
    """
    current_time = time.time()
    
    if (current_time - game_state.LAST_GAME_TICK_TIME) < game_state.TICK_INTERVAL_SECONDS:
        return # Not time to tick yet
        
    # --- IT'S TIME TO TICK! ---
    game_state.LAST_GAME_TICK_TIME = current_time
    game_state.GAME_TICK_COUNTER += 1
    
    # Get *all* active players for the environment check
    temp_active_players = {}
    for sid, data in game_state.ACTIVE_PLAYERS.items():
        player_name = data["player_name"]
        room_id = data["current_room_id"]
        temp_active_players[player_name] = Player(player_name, room_id) # Create light Player object
    
    log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    log_prefix = f"{log_time} - GAME_TICK ({game_state.GAME_TICK_COUNTER})" 
    print(f"{log_prefix}: Running global tick...")

    # 1. Prune stale players
    _prune_active_players(log_prefix, broadcast_callback)

    # 2. Update Environment (Time/Weather)
    environment.update_environment_state(
        game_tick_counter=game_state.GAME_TICK_COUNTER,
        active_players_dict=temp_active_players,
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback
    )

    # 3. Update Monster Respawns
    monster_respawn.process_respawns(
        log_time_prefix=log_prefix,
        current_time_utc=datetime.datetime.now(datetime.timezone.utc),
        broadcast_callback=broadcast_callback,
        game_npcs_dict={}, 
        game_monster_templates_dict={}, 
        game_equipment_tables_global={}, 
        game_items_global={} 
    )
    
    print(f"{log_prefix}: Global tick complete.")

# ---
# UPDATED EXECUTE_COMMAND
# ---
def execute_command(player_name: str, command_line: str, sid: str) -> Dict[str, Any]:
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
    
    # 3. RUN THE GAME TICK (No longer needed here, moved to background thread)

    # 4. Fetch Room Data (FROM CACHE)
    room_db_data = game_state.GAME_ROOMS.get(player.current_room_id)
    if not room_db_data:
        # ... (fallback logic) ...
        print(f"[WARN] Room {player.current_room_id} not in cache! Fetching from DB.")
        room_db_data = fetch_room_data(player.current_room_id)
        if room_db_data and room_db_data.get("room_id") != "void":
            game_state.GAME_ROOMS[player.current_room_id] = room_db_data
            
    room = Room(
        room_id=room_db_data.get("room_id", "void"), 
        name=room_db_data.get("name", "The Void"), 
        description=room_db_data.get("description", "..."), 
        db_data=room_db_data
    )

    # Filter defeated monsters
    # ... (unchanged) ...
    active_monsters = []
    for obj in room.objects:
        monster_id = obj.get("monster_id")
        if monster_id and monster_id in game_state.DEFEATED_MONSTERS:
            pass
        else:
            active_monsters.append(obj)
    room.objects = active_monsters


    # 5. --- CHECK GAME STATE ---
    
    if player.game_state == "chargen":
        # ... (chargen logic) ...
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
            if command_line.lower() != "ping":
                player.send_message("What?")
        else:
            command = parts[0].lower()
            args = parts[1:]
 
            verb_info = VERB_ALIASES.get(command)
            
            if not verb_info:
                player.send_message(f"I don't know the command **'{command}'**.")
            else:
                # ... (verb execution logic, unchanged) ...
                verb_name, verb_class_name = verb_info
                if verb_class_name == "Move":
                    if command in DIRECTION_MAP: args = [DIRECTION_MAP[command]]
                elif verb_class_name == "Exit":
                    if command == "out": args = []

                verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
                try:
                    verb_module_name = f"mud_backend.verbs.{verb_name}"
                    spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
                    if spec is None: raise FileNotFoundError(f"Verb file not found at {verb_file_path}")
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    VerbClass = getattr(module, verb_class_name)
                    verb_instance = VerbClass(player=player, room=room, args=args)
                    verb_instance.execute()
                except Exception as e:
                    player.send_message(f"An unexpected error occurred while running **{command}**: {e}")
                    print(f"Full error for command '{command}': {e}")
    
    # ---
    # 6. UPDATE ACTIVE PLAYER LIST (with SID)
    # ---
    game_state.ACTIVE_PLAYERS[sid] = {
        "player_name": player.name,
        "current_room_id": player.current_room_id,
        "last_seen": time.time()
    }

    # 7. Persist State Changes
    save_game_state(player)

    # 8. Return output to the client
    # (We no longer check broadcasts here, app.py does it)
    return {
        "messages": player.messages,
        "game_state": player.game_state
    }


def get_player_object(player_name: str) -> Player:
    # ... (unchanged) ...
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        return Player(player_name, "void") 
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    return player