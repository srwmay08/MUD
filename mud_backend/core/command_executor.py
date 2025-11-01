# core/command_executor.py
import importlib.util
import os
import time 
import datetime 
import copy # <-- Keep this import
from typing import List, Tuple, Dict, Any, Optional 

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

# (VERB_ALIASES and DIRECTION_MAP are unchanged)
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
    
    "ping": ("tick", "Tick"),
}
DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}


# --- (Prune Stale Players function is unchanged) ---
def _prune_active_players(log_prefix: str, broadcast_callback):
    current_time = time.time()
    stale_players = []
    for player_name, data in game_state.ACTIVE_PLAYERS.items():
        if (current_time - data["last_seen"]) > game_state.PLAYER_TIMEOUT_SECONDS:
            stale_players.append(player_name)
    if stale_players:
        for player_name in stale_players:
            player_info = game_state.ACTIVE_PLAYERS.pop(player_name, None)
            if player_info:
                room_id = player_info.get("current_room_id", "unknown")
                disappears_message = f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span> disappears.'
                broadcast_callback(room_id, disappears_message, "ambient")
                print(f"{log_prefix}: Pruned stale player {player_name} from room {room_id}.")

# --- (Game Tick function is unchanged) ---
def _check_and_run_game_tick(broadcast_callback):
    """
    Checks if enough time has passed and runs the global game tick.
    """
    current_time = time.time()
    
    if (current_time - game_state.LAST_GAME_TICK_TIME) < game_state.TICK_INTERVAL_SECONDS:
        return # Not time to tick yet
        
    game_state.LAST_GAME_TICK_TIME = current_time
    game_state.GAME_TICK_COUNTER += 1
    
    # Get *all* active players for the environment check
    temp_active_players = {}
    for player_name, data in game_state.ACTIVE_PLAYERS.items():
        player_obj = data.get("player_obj")
        if not player_obj:
            player_obj = Player(player_name, data["current_room_id"])
        temp_active_players[player_name] = player_obj
    
    log_time = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    log_prefix = f"{log_time} - GAME_TICK ({game_state.GAME_TICK_COUNTER})" 
    print(f"{log_prefix}: Running global tick...")

    _prune_active_players(log_prefix, broadcast_callback)

    environment.update_environment_state(
        game_tick_counter=game_state.GAME_TICK_COUNTER,
        active_players_dict=temp_active_players,
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback
    )

    # ---
    # THIS IS THE FIX. We only pass the arguments it actually needs.
    # ---
    monster_respawn.process_respawns(
        log_time_prefix=log_prefix,
        current_time_utc=datetime.datetime.now(datetime.timezone.utc),
        broadcast_callback=broadcast_callback,
        game_npcs_dict={}, # TODO: Pass real data
        game_equipment_tables_global={}, # TODO: Pass real data
        game_items_global=game_state.GAME_ITEMS # Pass the real items
    )
    # --- END FIX ---
    
    print(f"{log_prefix}: Global tick complete.")

# ---
# UPDATED EXECUTE_COMMAND
# ---
def execute_command(player_name: str, command_line: str, sid: str) -> Dict[str, Any]:
    """
    The main function to parse and execute a game command.
    """
    
    # 1. Fetch Player Data (unchanged)
    player_db_data = fetch_player_data(player_name)
    
    # 2. Handle New vs. Existing Player (unchanged)
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
    
    # 3. RUN THE GAME TICK (No longer needed here)

    # 4. Fetch Room Data (FROM CACHE)
    # --- THIS IS THE BUG FIX ---
    # We NO LONGER deepcopy. We get the *actual* live room object.
    room_db_data = game_state.GAME_ROOMS.get(player.current_room_id)
    if not room_db_data:
        print(f"[WARN] Room {player.current_room_id} not in cache! Fetching from DB.")
        room_db_data = fetch_room_data(player.current_room_id)
        if room_db_data and room_db_data.get("room_id") != "void":
            game_state.GAME_ROOMS[player.current_room_id] = room_db_data
    # --- END BUG FIX ---
            
    room = Room(
        room_id=room_db_data.get("room_id", "void"), 
        name=room_db_data.get("name", "The Void"), 
        description=room_db_data.get("description", "..."), 
        # Pass the *live* dict so the Room object can modify it
        db_data=room_db_data 
    )

    # --- UPDATED: Filter defeated monsters and INFLATE stubs ---
    # This now modifies the live game_state.GAME_ROOMS[...]["objects"] list
    active_monsters = []
    if "objects" in room_db_data:
        for obj in room_db_data["objects"]:
            monster_id = obj.get("monster_id")
            if monster_id and monster_id in game_state.DEFEATED_MONSTERS:
                pass # Monster is dead, don't add it
            else:
                # --- Inflate monster stubs ---
                if monster_id and "stats" not in obj:
                    template = game_state.GAME_MONSTER_TEMPLATES.get(monster_id)
                    if template:
                        # --- INFLATE IN-PLACE ---
                        # Merge the template data into the room's object
                        obj.update(copy.deepcopy(template))
                        active_monsters.append(obj)
                    else:
                        print(f"[ERROR] Monster {monster_id} in room {room.room_id} has no template!")
                else:
                    # It's a normal object or an already-inflated monster
                    active_monsters.append(obj)
                
    room.objects = active_monsters
    # We no longer need to write this back, as we modified it in-place.
    # The `room` object's `self.objects` list points to the same
    # list as `game_state.GAME_ROOMS[player.current_room_id]["objects"]`.
    # --- END UPDATE ---
    
    # 5. --- CHECK GAME STATE ---
    # (Chargen logic is unchanged)
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command_line.lower() == "look":
            show_room_to_player(player, room)
            do_initial_stat_roll(player) 
            player.chargen_step = 1 
        else:
            handle_chargen_input(player, command_line)
        
    elif player.game_state == "playing":
        # (Verb execution logic is unchanged)
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
    
    # 6. UPDATE ACTIVE PLAYER LIST (unchanged)
    game_state.ACTIVE_PLAYERS[player.name.lower()] = {
        "sid": sid,
        "player_name": player.name, 
        "current_room_id": player.current_room_id,
        "last_seen": time.time(),
        "player_obj": player 
    }

    # 7. Persist State Changes (unchanged)
    save_game_state(player)

    # 8. Return output to the client (unchanged)
    return {
        "messages": player.messages,
        "game_state": player.game_state
    }


# 9. get_player_object (unchanged)
def get_player_object(player_name: str) -> Optional[Player]:
    player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
    if player_info and player_info.get("player_obj"):
        return player_info["player_obj"]
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        return None
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    return player