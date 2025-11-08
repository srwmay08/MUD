# mud_backend/core/command_executor.py
import importlib.util
import os
import time 
import datetime 
import copy 
import uuid
from typing import List, Tuple, Dict, Any, Optional 

# --- REFACTORED: World is now a type hint, not an import ---
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mud_backend.core.game_state import World
# --- END REFACTOR ---

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, fetch_room_data, save_game_state
from mud_backend.core.chargen_handler import (
    handle_chargen_input, 
    get_chargen_prompt, 
    do_initial_stat_roll
)
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core.skill_handler import show_skill_list 

# --- REFACTORED: Removed game_state import ---
# from mud_backend.core import game_state 
# --- END REFACTOR ---

from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
from mud_backend import config

# --- VERB ALIASES (Unchanged) ---
VERB_ALIASES: Dict[str, Tuple[str, str]] = {
    # Movement
    "move": ("movement", "Move"), "go": ("movement", "Move"),
    "n": ("movement", "Move"), "north": ("movement", "Move"),
    "s": ("movement", "Move"), "south": ("movement", "Move"),
    "e": ("movement", "Move"), "east": ("movement", "Move"),
    "w": ("movement", "Move"), "west": ("movement", "Move"),
    "ne": ("movement", "Move"), "northeast": ("movement", "Move"),
    "nw": ("movement", "Move"), "northwest": ("movement", "Move"),
    "se": ("movement", "Move"), "southeast": ("movement", "Move"),
    "sw": ("movement", "Move"), "southwest": ("movement", "Move"),
    "enter": ("movement", "Enter"), "climb": ("movement", "Climb"),
    "exit": ("movement", "Exit"), "out": ("movement", "Exit"),
    
    # Interaction & Items
    "get": ("item_actions", "Get"), "take": ("item_actions", "Take"),
    "drop": ("item_actions", "Drop"), "put": ("item_actions", "Put"),
    "stow": ("item_actions", "Put"), "pour": ("item_actions", "Pour"),
    "wear": ("equipment", "Wear"), "wield": ("equipment", "Wear"), 
    "remove": ("equipment", "Remove"),
    "inventory": ("inventory", "Inventory"), "inv": ("inventory", "Inventory"),
    "wealth": ("inventory", "Wealth"),

    # Observation
    "look": ("observation", "Look"), "examine": ("observation", "Examine"),
    "investigate": ("observation", "Investigate"),

    # Combat & Status
    "attack": ("attack", "Attack"),
    "stance": ("stance", "Stance"), 
    "sit": ("posture", "Posture"), "stand": ("posture", "Posture"),
    "kneel": ("posture", "Posture"), "prone": ("posture", "Posture"),
    "health": ("health", "Health"), "hp": ("health", "Health"),
    "stat": ("stats", "Stats"), "stats": ("stats", "Stats"),
    "skill": ("skills", "Skills"), "skills": ("skills", "Skills"),
    "experience": ("experience", "Experience"), "exp": ("experience", "Experience"),

    # Activities
    "search": ("harvesting", "Search"), "skin": ("harvesting", "Skin"),
    "forage": ("foraging", "Forage"), "eat": ("foraging", "Eat"), "drink": ("foraging", "Drink"),
    
    # Systems
    "say": ("say", "Say"),
    "give": ("trading", "Give"), "accept": ("trading", "Accept"),
    "decline": ("trading", "Decline"), "cancel": ("trading", "Cancel"), # <-- THIS IS THE FIX
    "exchange": ("trading", "Exchange"), # <-- NEW
    "list": ("shop", "List"), "buy": ("shop", "Buy"),
    "sell": ("shop", "Sell"), "appraise": ("shop", "Appraise"),

    # Training
    "check": ("training", "CheckIn"), "checkin": ("training", "CheckIn"),
    "train": ("training", "Train"), "done": ("training", "Done"),
}

DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}

# ---
# --- NEW HELPER FUNCTION ---
# ---
def _get_player_vitals(world: 'World', player: Player) -> Dict[str, Any]:
    """
    Gathers all vital player stats for the GUI and returns them in a dict.
    Includes HP, Mana, Stamina, Spirit, Posture, Status, and Roundtime.
    """
    
    # 1. Get HP, Mana, Stamina, Spirit
    vitals = {
        "hp": player.hp,
        "max_hp": player.max_hp,
        "mana": player.mana,
        "max_mana": player.max_mana,
        "stamina": player.stamina,
        "max_stamina": player.max_stamina,
        "spirit": player.spirit,
        "max_spirit": player.max_spirit,
    }

    # 2. Get Posture and Status Effects
    vitals["posture"] = player.posture.capitalize()
    vitals["status_effects"] = player.status_effects # This is a list

    # 3. Get Roundtime
    rt_data = world.get_combat_state(player.name.lower())
    rt_end_time_ms = 0
    rt_duration_ms = 0
    
    if rt_data:
        rt_end_time_sec = rt_data.get("next_action_time", 0)
        if rt_end_time_sec > time.time():
            rt_end_time_ms = int(rt_end_time_sec * 1000)
            rt_duration_ms = int((rt_end_time_sec - time.time()) * 1000)

    vitals["rt_end_time_ms"] = rt_end_time_ms
    vitals["rt_duration_ms"] = rt_duration_ms

    return vitals
# ---
# --- END NEW HELPER FUNCTION ---
# ---


# --- REFACTORED: 'world' is the first argument + add account_username ---
def execute_command(world: 'World', player_name: str, command_line: str, sid: str, account_username: Optional[str] = None) -> Dict[str, Any]:
    """The main function to parse and execute a game command."""
    
    # --- REFACTORED: Get player from world ---
    player_info = world.get_player_info(player_name.lower())
    # --- END REFACTOR ---
    
    if player_info and player_info.get("player_obj"):
        player = player_info["player_obj"]
        player.messages.clear()
    else:
        player_db_data = fetch_player_data(player_name)
        if not player_db_data:
            # --- THIS IS A NEW CHARACTER ---
            if not account_username:
                # This should not happen if app.py is correct, but it's a safety check
                print(f"[EXEC-ERROR] New player {player_name} has no account_username!")
                return {"messages": ["Critical error: Account not found."], "game_state": "error"}

            start_room_id = config.CHARGEN_START_ROOM
            # --- REFACTORED: Inject world into new Player ---
            player = Player(world, player_name, start_room_id, {})
            # --- NEW: Assign account username ---
            player.account_username = account_username
            # --- END REFACTOR ---
            player.game_state = "chargen"; player.chargen_step = 0
            
            # --- NEW: Set default HP/Mana/etc on creation ---
            player.hp = player.max_hp
            player.mana = player.max_mana
            player.stamina = player.max_stamina
            player.spirit = player.max_spirit
            # --- END NEW ---
            
            player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
        else:
            # --- THIS IS A LOADING CHARACTER ---
            # --- REFACTORED: Inject world into existing Player ---
            player = Player(world, player_db_data["name"], player_db_data["current_room_id"], player_db_data)
            # --- END REFACTOR ---
            
    # --- REFACTORED: Get room from world ---
    room_db_data = world.get_room(player.current_room_id)
    # --- END REFACTOR ---
            
    room = Room(room_db_data.get("room_id", "void"), room_db_data.get("name", "The Void"), room_db_data.get("description", "..."), db_data=room_db_data)

    live_room_objects = []
    all_objects = room_db_data.get("objects", []) 
    if all_objects:
        for obj in all_objects:
            monster_id = obj.get("monster_id")
            if monster_id:
                if "uid" not in obj:
                     obj["uid"] = uuid.uuid4().hex
                uid = obj["uid"]

                # --- REFACTORED: Check world for defeated state ---
                is_defeated = world.get_defeated_monster(uid) is not None
                # --- END REFACTOR ---
                
                if not is_defeated:
                    if "stats" not in obj:
                        # --- REFACTORED: Get template from world ---
                        template = world.game_monster_templates.get(monster_id)
                        # --- END REFACTOR ---
                        if template:
                            current_uid = obj["uid"]
                            obj.update(copy.deepcopy(template))
                            obj["uid"] = current_uid 
                            live_room_objects.append(obj)
                        else: 
                             pass
                    else: live_room_objects.append(obj)
            else: live_room_objects.append(obj)
    room.objects = live_room_objects
    
    parts = command_line.strip().split()
    command = parts[0].lower() if parts else ""
    args = parts[1:] if parts else []
        
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command == "look":
            show_room_to_player(player, room); do_initial_stat_roll(player); player.chargen_step = 1 
        else: handle_chargen_input(player, command_line)
    elif player.game_state == "training":
        verb_info = None
        if command == "list": verb_info = ("training", "List")
        elif command == "train": verb_info = ("training", "Train")
        elif command == "done": verb_info = ("training", "Done")
        elif command == "look":
             verb_info = ("observation", "Look")
             if args: player.send_message("You must 'done' training to interact with objects."); verb_info = None
        if verb_info:
            # --- REFACTORED: Pass world to _run_verb ---
            _run_verb(world, player, room, command, args, verb_info)
            # --- END REFACTOR ---
        else:
            if not parts: player.send_message("Invalid command. Type 'list', 'train', or 'done'.")
            else: player.send_message(f"You cannot '{command}' while training. Type 'done' to finish.")
    elif player.game_state == "playing":
        if not parts:
            if command_line.lower() != "ping": player.send_message("What?")
        else:
            verb_info = VERB_ALIASES.get(command)
            if not verb_info: player.send_message(f"I don't know the command **'{command}'**.")
            else:
                verb_module, verb_class = verb_info
                if verb_module == "training" and command not in ["check", "checkin"]:
                    player.send_message("You must 'check in' at the inn to train.")
                else: 
                    # --- REFACTORED: Pass world to _run_verb ---
                    _run_verb(world, player, room, command, args, verb_info)
                    # --- END REFACTOR ---
    
    # --- REFACTORED: Set player in world ---
    world.set_player_info(player.name.lower(), {
        "sid": sid, "player_name": player.name, "current_room_id": player.current_room_id,
        "last_seen": time.time(), "player_obj": player 
    })
    # --- END REFACTOR ---
    
    save_game_state(player)
    
    # ---
    # --- NEW: Bundle vitals with every response ---
    # ---
    vitals_data = _get_player_vitals(world, player)
    return {
        "messages": player.messages, 
        "game_state": player.game_state,
        "vitals": vitals_data  # <-- NEW
    }

# --- REFACTORED: 'world' is the first argument ---
def _run_verb(world: 'World', player: Player, room: Room, command: str, args: List[str], verb_info: Tuple[str, str]):
    try:
        verb_name, verb_class_name = verb_info
        verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
        verb_module_name = f"mud_backend.verbs.{verb_name}"
        spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
        if spec is None: raise FileNotFoundError(f"Verb file '{verb_name}.py' not found")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        VerbClass = getattr(module, verb_class_name)
        
        # --- REFACTORED: Pass world to verb constructor ---
        verb_instance = VerbClass(world=world, player=player, room=room, args=args, command=command)
        # --- END REFACTOR ---
        
        if verb_class_name == "Move" and command in DIRECTION_MAP: verb_instance.args = [DIRECTION_MAP[command]]
        elif verb_class_name == "Exit" and command == "out": verb_instance.args = []
        verb_instance.execute()
    except Exception as e:
        player.send_message(f"An error occurred: {e}")
        print(f"Error running command '{command}': {e}")
        import traceback
        traceback.print_exc()