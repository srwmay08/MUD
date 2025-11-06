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

# --- UPDATED: VERB_ALIASES ---
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
    "nw": ("movement", "Move"), # <-- THIS IS THE FIX
    "se": ("movement", "Move"),
    "southeast": ("movement", "Move"),
    "sw": ("movement", "Move"), # <-- THIS IS THE FIX
    "southwest": ("movement", "Move"), # <-- THIS IS THE FIX
    
    # Object Interaction Verbs
    "enter": ("movement", "Enter"),
    "climb": ("movement", "Climb"),
    
    # --- UPDATED: Item Action Verbs ---
    "get": ("item_actions", "Get"),
    "take": ("item_actions", "Take"),
    "drop": ("item_actions", "Drop"),
    "put": ("item_actions", "Put"),
    "stow": ("item_actions", "Put"),
    "pour": ("item_actions", "Pour"), 
    
    # Observation Verbs
    "examine": ("observation", "Examine"),
    "investigate": ("observation", "Investigate"),
    "look": ("observation", "Look"),

    # Harvesting/Resource Verbs
    "search": ("harvesting", "Search"), 
    "skin": ("harvesting", "Skin"),
    "forage": ("foraging", "Forage"), 
    
    # Combat Verbs
    "attack": ("attack", "Attack"),
    # "stance": ("stance", "Stance"), # <-- REMOVED
    
    # --- NEW: Posture Verbs ---
    "sit": ("posture", "Posture"),
    "kneel": ("posture", "Posture"),
    "prone": ("posture", "Posture"),
    "stand": ("posture", "Posture"),
    
    # Training Verbs
    "check": ("training", "CheckIn"),
    "checkin": ("training", "CheckIn"),
    "train": ("training", "Train"),
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
    "wield": ("equipment", "Wear"), 
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
    
    # --- NEW: Banking Verbs ---
    "deposit": ("banking", "Deposit"),
    "withdraw": ("banking", "Withdraw"),
    "balance": ("banking", "Balance"),
    
    # --- NEW: Shop Verbs ---
    "list": ("shop", "List"), # This will be the shop list
    "buy": ("shop", "Buy"),
    "sell": ("shop", "Sell"),
    "appraise": ("shop", "Appraise"),
    
    # --- NEW: Herb Use Verbs ---
    "eat": ("foraging", "Eat"),
    "drink": ("foraging", "Drink"),
}
# --- END UPDATED ---


DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}


# --- (_prune_active_players and _check_and_run_game_tick unchanged, omitting for brevity) ---
def _prune_active_players(log_prefix: str, broadcast_callback):
    # This function is now in game_loop_handler.py
    pass

def _check_and_run_game_tick(broadcast_callback):
    # This function is now in game_loop_handler.py
    pass

# ---
# EXECUTE_COMMAND
# ---
def execute_command(player_name: str, command_line: str, sid: str) -> Dict[str, Any]:
    """
    The main function to parse and execute a game command.
    """
    
    # --- (State management logic is unchanged) ---
    player_info = None
    # --- ADD LOCK ---
    with game_state.PLAYER_LOCK:
        player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
    # --- END LOCK ---
    
    if player_info and player_info.get("player_obj"):
        player = player_info["player_obj"]
        player.messages.clear()
    else:
        player_db_data = fetch_player_data(player_name)
        
        if not player_db_data:
            start_room_id = config.CHARGEN_START_ROOM
            player = Player(player_name, start_room_id, {})
            player.game_state = "chargen"
            player.chargen_step = 0
            player.hp = player.max_hp 
            player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
        else:
            player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
            
    # --- (Room fetching logic is unchanged) ---
    room_db_data = None
    # --- ADD LOCK ---
    with game_state.ROOM_LOCK:
        # We lock reading the room cache, as another thread might be modifying it
        room_db_data = copy.deepcopy(game_state.GAME_ROOMS.get(player.current_room_id))
    # --- END LOCK ---

    if not room_db_data:
        print(f"[WARN] Room {player.current_room_id} not in cache! Fetching from DB.")
        room_db_data = fetch_room_data(player.current_room_id)
        if room_db_data and room_db_data.get("room_id") != "void":
            # --- ADD LOCK ---
            with game_state.ROOM_LOCK:
                game_state.GAME_ROOMS[player.current_room_id] = room_db_data
            # --- END LOCK ---
            room_db_data = copy.deepcopy(room_db_data) # Use a copy to avoid thread issues
            
    room = Room(
        room_id=room_db_data.get("room_id", "void"), 
        name=room_db_data.get("name", "The Void"), 
        description=room_db_data.get("description", "..."), 
        db_data=room_db_data # This db_data is now a copy, safe for this thread
    )

    # --- (Monster and Corpse filtering logic is unchanged) ---
    live_room_objects = []
    all_objects = room_db_data.get("objects", []) 
    
    if all_objects:
        for obj in all_objects:
            monster_id = obj.get("monster_id")
            
            if monster_id:
                is_defeated = False
                # --- ADD LOCK ---
                with game_state.COMBAT_LOCK:
                    is_defeated = monster_id in game_state.DEFEATED_MONSTERS
                # --- END LOCK ---

                if not is_defeated:
                    if "stats" not in obj:
                        template = game_state.GAME_MONSTER_TEMPLATES.get(monster_id)
                        if template:
                            obj.update(copy.deepcopy(template))
                            live_room_objects.append(obj)
                        else:
                            print(f"[ERROR] Monster {monster_id} in room {room.room_id} has no template!")
                    else:
                        live_room_objects.append(obj)
            else:
                live_room_objects.append(obj)

    room.objects = live_room_objects # This is the thread-safe copy
    
    # --- (Command parsing logic is unchanged) ---
    parts = command_line.strip().split()
    command = ""
    args = []
    if parts:
        command = parts[0].lower()
        args = parts[1:]
        
    # --- UPDATED: Game state routing ---
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command == "look":
            show_room_to_player(player, room)
            do_initial_stat_roll(player) 
            player.chargen_step = 1 
        else:
            handle_chargen_input(player, command_line)
            
    elif player.game_state == "training":
        # --- THIS IS THE FIX ---
        # Manually define verb_info for this state
        # to avoid collision with shop 'list'
        verb_info = None
        if command == "list":
            verb_info = ("training", "List")
        elif command == "train":
            verb_info = ("training", "Train")
        elif command == "done":
            verb_info = ("training", "Done")
        elif command == "look":
             verb_info = ("observation", "Look")
             if args:
                 player.send_message("You must 'done' training to interact with objects.")
                 verb_info = None
        
        if verb_info:
            _run_verb(player, room, command, args, verb_info)
        else:
            if not parts:
                 player.send_message("Invalid command. Type 'list', 'train', or 'done'.")
            else:
                 player.send_message(f"You cannot '{command}' while training. Type 'done' to finish.")
        # --- END FIX ---
        
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
    # --- ADD LOCK ---
    with game_state.PLAYER_LOCK:
        game_state.ACTIVE_PLAYERS[player.name.lower()] = {
            "sid": sid,
            "player_name": player.name, 
            "current_room_id": player.current_room_id,
            "last_seen": time.time(),
            "player_obj": player 
        }
    # --- END LOCK ---

    save_game_state(player)
    return {
        "messages": player.messages,
        "game_state": player.game_state
    }

# ---
# --- MODIFIED: _run_verb
# ---
def _run_verb(player: Player, room: Room, command: str, args: List[str], verb_info: Tuple[str, str]):
    """
    Loads and executes the appropriate verb class.
    """
    try:
        verb_name, verb_class_name = verb_info
        
        verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
        verb_module_name = f"mud_backend.verbs.{verb_name}"
        
        spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
        
        # --- THIS IS THE FIX for NameError: 'VerbClass' not defined ---
        if spec is None: 
             raise FileNotFoundError(f"Verb file '{verb_name}.py' not found")
             
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        VerbClass = getattr(module, verb_class_name)
        # --- END FIX ---
        
        # We pass the original 'command' to the verb
        verb_instance = VerbClass(player=player, room=room, args=args, command=command)
        
        # --- Alias argument handling ---
        if verb_class_name == "Move":
            if command in DIRECTION_MAP: verb_instance.args = [DIRECTION_MAP[command]]
        elif verb_class_name == "Exit":
            if command == "out": verb_instance.args = []

        verb_instance.execute()
        
    except Exception as e:
        player.send_message(f"An unexpected error occurred while running **{command}**: {e}")
        print(f"Full error for command '{command}' from file '{verb_name}.py': {e}")
        import traceback
        traceback.print_exc()

def get_player_object(player_name: str) -> Optional[Player]:
    player_info = None
    # --- ADD LOCK ---
    with game_state.PLAYER_LOCK:
        player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
    # --- END LOCK ---
    
    if player_info and player_info.get("player_obj"):
        return player_info["player_obj"]
        
    player_db_data = fetch_player_data(player_name)
    if not player_db_data:
        return None
    player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
    return player