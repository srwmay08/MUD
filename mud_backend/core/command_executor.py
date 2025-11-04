# core/command_executor.py
import importlib.util
import os
import time 
import datetime 
import copy 
from typing import List, Tuple, Dict, Any, Optional 

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, fetch_room_data, save_game_state
from mud_backend.core.chargen_handler import (
    handle_chargen_input, 
    get_chargen_prompt, 
    do_initial_stat_roll
)
from mud_backend.core.room_handler import show_room_to_player

# --- Import our new skill handler ---
from mud_backend.core.skill_handler import show_skill_list 

# --- Import our new game state and loop functions ---
from mud_backend.core import game_state
from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
# ---
from mud_backend import config # <-- NEW IMPORT

# (VERB_ALIASES and DIRECTION_MAP are updated)
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
    "nw": ("movement", "Northwest"),
    "se": ("movement", "Move"),
    "southeast": ("movement", "Move"),
    "sw": ("movement", "Move"),
    "southwest": ("movement", "Southwest"),
    
    # Object Interaction Verbs
    "enter": ("movement", "Enter"),
    "climb": ("movement", "Climb"),
    
    # --- UPDATED: Item Action Verbs ---
    "get": ("item_actions", "Get"),
    "take": ("item_actions", "Take"),
    "drop": ("item_actions", "Drop"),
    "put": ("item_actions", "Put"),
    "stow": ("item_actions", "Put"), # <-- THIS IS THE FIX
    
    # Observation Verbs
    "examine": ("observation", "Examine"),
    "investigate": ("observation", "Investigate"),
    "look": ("observation", "Look"),

    # Harvesting/Resource Verbs
    "search": ("harvesting", "Search"), 
    "skin": ("harvesting", "Skin"),
    
    # Combat Verbs
    "attack": ("attack", "Attack"),
    "stance": ("stance", "Stance"),
    
    # Training Verbs
    "check": ("training", "CheckIn"),
    "checkin": ("training", "CheckIn"),
    "train": ("training", "Train"),
    "list": ("training", "List"),
    "done": ("training", "Done"),
    
    # Character Info Verbs
    "stat": ("stats", "Stats"),
    "stats": ("stats", "Stats"),
    "skill": ("skills", "Skills"),
    "skills": ("skills", "Skills"),
    "health": ("health", "Health"),
    "hp": ("health", "Health"),
    
    # --- UPDATED: Inventory & Equipment Verbs ---
    "inventory": ("inventory", "Inventory"),
    "inv": ("inventory", "Inventory"),
    "wealth": ("inventory", "Wealth"),
    "wear": ("equipment", "Wear"),
    "wield": ("equipment", "Wear"), # 'wield' is an alias for 'wear'
    "remove": ("equipment", "Remove"),
    
    # Trading Verbs
    "give": ("trading", "Give"),
    "accept": ("trading", "Accept"),
    "decline": ("trading", "Decline"),
    "cancel": ("trading", "Cancel"),

    # Other Verbs
    "experience": ("experience", "Experience"),
    "exp": ("experience", "Experience"),
    "exit": ("movement", "Exit"),
    "out": ("movement", "Exit"),
    "say": ("say", "Say"),
    "ping": ("tick", "Tick"),
}



DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}


# --- (_prune_active_players and _check_and_run_game_tick unchanged, omitting for brevity) ---
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

def _check_and_run_game_tick(broadcast_callback):
    current_time = time.time()
    if (current_time - game_state.LAST_GAME_TICK_TIME) < game_state.TICK_INTERVAL_SECONDS:
        return
    game_state.LAST_GAME_TICK_TIME = current_time
    game_state.GAME_TICK_COUNTER += 1
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
    monster_respawn.process_respawns(
        log_time_prefix=log_prefix,
        broadcast_callback=broadcast_callback,
        game_npcs_dict={},
        game_equipment_tables_global={},
        game_items_global=game_state.GAME_ITEMS
    )
    print(f"{log_prefix}: Global tick complete.")

# ---
# UPDATED EXECUTE_COMMAND (Room Object Filtering Fix)
# ---
def execute_command(player_name: str, command_line: str, sid: str) -> Dict[str, Any]:
    """
    The main function to parse and execute a game command.
    """
    
    # --- (State management logic is unchanged) ---
    player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
    if player_info and player_info.get("player_obj"):
        player = player_info["player_obj"]
        player.messages.clear()
    else:
        player_db_data = fetch_player_data(player_name)
        
        if not player_db_data:
            # 4. This is a NEW character
            start_room_id = config.CHARGEN_START_ROOM
            player = Player(player_name, start_room_id, {})
            player.game_state = "chargen"
            player.chargen_step = 0
            
            # --- FIX: Set HP to Max HP ---
            player.hp = player.max_hp 
            # --- END FIX ---
            
            player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
        else:
            # 5. This is a RETURNING character
            player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
            
    # --- (Room fetching logic is unchanged) ---
    room_db_data = game_state.GAME_ROOMS.get(player.current_room_id)
    if not room_db_data:
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

    # --- UPDATED: Monster and Corpse filtering logic (Fixes Persistence) ---
    live_room_objects = []
    all_objects = room_db_data.get("objects", []) 
    
    if all_objects:
        for obj in all_objects:
            monster_id = obj.get("monster_id")
            
            # 1. If it has a monster_id: check if it is active (not defeated)
            if monster_id:
                if monster_id not in game_state.DEFEATED_MONSTERS:
                    # Logic to re-inject template if monster object is missing stats/etc. (e.g., just respawned)
                    if "stats" not in obj:
                        template = game_state.GAME_MONSTER_TEMPLATES.get(monster_id)
                        if template:
                            obj.update(copy.deepcopy(template))
                            live_room_objects.append(obj)
                        else:
                            print(f"[ERROR] Monster {monster_id} in room {room.room_id} has no template!")
                    else:
                        live_room_objects.append(obj)
            
            # 2. If it does NOT have a monster_id (e.g., fountain, well, CORPSE, or ITEM): KEEP IT
            else:
                live_room_objects.append(obj)

    room.objects = live_room_objects
    # --- END UPDATED ---
    
    # --- (Command parsing logic is unchanged) ---
    parts = command_line.strip().split()
    command = ""
    args = []
    if parts:
        command = parts[0].lower()
        args = parts[1:]
        
    # --- (Game state routing is unchanged) ---
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command == "look":
            show_room_to_player(player, room)
            do_initial_stat_roll(player) 
            player.chargen_step = 1 
        else:
            handle_chargen_input(player, command_line)
            
    elif player.game_state == "training":
        if not parts:
            player.send_message("Invalid command. Type 'list', 'train', or 'done'.")
        verb_info = VERB_ALIASES.get(command)
        if command in ["train", "list", "done", "look"]:
            if command == "look":
                verb_info = ("observation", "Look")
                if args:
                    player.send_message("You must 'done' training to interact with objects.")
                    verb_info = None
            if verb_info:
                _run_verb(player, room, command, args, verb_info)
            else:
                player.send_message(f"Unknown command '{command}' in training mode.")
        else:
            player.send_message(f"You cannot '{command}' while training. Type 'done' to finish.")
        
    elif player.game_state == "playing":
        if not parts:
            if command_line.lower() != "ping":
                player.send_message("What?")
        else:
            verb_info = VERB_ALIASES.get(command)
            if not verb_info:
                player.send_message(f"I don't know the command **'{command}'**.")
            else:
                verb_module, verb_class = verb_info
                if verb_module == "training" and command not in ["check", "checkin"]:
                    player.send_message("You must 'check in' at the inn to train.")
                else:
                    _run_verb(player, room, command, args, verb_info)
    
    # --- (Save and return logic is unchanged) ---
    game_state.ACTIVE_PLAYERS[player.name.lower()] = {
        "sid": sid,
        "player_name": player.name, 
        "current_room_id": player.current_room_id,
        "last_seen": time.time(),
        "player_obj": player 
    }
    save_game_state(player)
    return {
        "messages": player.messages,
        "game_state": player.game_state
    }

# --- (_run_verb and get_player_object are unchanged, omitting for brevity) ---
def _run_verb(player: Player, room: Room, command: str, args: List[str], verb_info: Tuple[str, str]):
    try:
        verb_name, verb_class_name = verb_info
        if verb_class_name == "Move":
            if command in DIRECTION_MAP: args = [DIRECTION_MAP[command]]
        elif verb_class_name == "Exit":
            if command == "out": args = []

        verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
        verb_module_name = f"mud_backend.verbs.{verb_name}"
        spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
        if spec is None: 
             raise FileNotFoundError(f"Verb file '{verb_name}.py' not found")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        VerbClass = getattr(module, verb_class_name)
        verb_instance = VerbClass(player=player, room=room, args=args)
        verb_instance.execute()
    except Exception as e:
        player.send_message(f"An unexpected error occurred while running **{command}**: {e}")
        print(f"Full error for command '{command}' from file '{verb_name}.py': {e}")
        import traceback
        traceback.print_exc()

def get_player_object(player_name: str) -> Optional[Player]:
    player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
    if player_info and player_info.get("player_obj"):
        return player_info["player_obj"]
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        return None
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    return player