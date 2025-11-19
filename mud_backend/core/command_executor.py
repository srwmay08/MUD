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
    do_initial_stat_roll,
    send_stat_roll_prompt,
    send_assignment_prompt 
)
# ---
# --- THIS IS THE FIX: Import from new location
# ---
from mud_backend.core.room_handler import show_room_to_player, _get_map_data
# ---
# --- END FIX
# ---
from mud_backend.core.skill_handler import show_skill_list 

# --- REFACTORED: Removed game_state import ---
# from mud_backend.core import game_state 
# --- END REFACTOR ---

from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
from mud_backend import config

# ---
# --- MODIFIED: VERB ALIASES (Added Group, Band, Whisper)
# ---
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
    "goto": ("movement", "GOTO"), 
    
    # Interaction & Items
    "get": ("item_actions", "Get"), "take": ("item_actions", "Take"),
    "drop": ("item_actions", "Drop"), "put": ("item_actions", "Put"),
    "stow": ("item_actions", "Put"), "pour": ("item_actions", "Pour"),
    "wear": ("equipment", "Wear"), "wield": ("equipment", "Wear"), 
    "remove": ("equipment", "Remove"),
    "inventory": ("inventory", "Inventory"), "inv": ("inventory", "Inventory"),
    "wealth": ("inventory", "Wealth"),
    "swap": ("inventory", "Swap"),

    # Observation
    "look": ("observation", "Look"), "examine": ("observation", "Examine"),
    "investigate": ("observation", "Investigate"),

    # Combat & Status
    "attack": ("attack", "Attack"),
    "stance": ("stance", "Stance"), 
    "sit": ("posture", "Posture"), 
    "stand": ("posture", "Posture"),
    "kneel": ("posture", "Posture"), 
    "prone": ("posture", "Posture"),
    "crouch": ("posture", "Posture"),
    "meditate": ("posture", "Posture"),
    "lay": ("posture", "Posture"),
    "health": ("health", "Health"), "hp": ("health", "Health"),
    "stat": ("stats", "Stats"), "stats": ("stats", "Stats"),
    "skill": ("skills", "Skills"), "skills": ("skills", "Skills"),
    "experience": ("experience", "Experience"), "exp": ("experience", "Experience"),
    # "trip": ("maneuvers", "Trip"), # <-- Handled conditionally

# --- GATHERING VERBS ---
    "skin": ("harvesting", "Skin"),
    "butcher": ("harvesting", "Skin"),
    "forage": ("foraging", "Forage"),
    "harvest": ("herbalism", "Harvest"),
    "mine": ("mining", "Mine"),
    "prospect": ("mining", "Prospect"),
    "chop": ("lumberjacking", "Chop"),
    "cut": ("lumberjacking", "Chop"),
    "survey": ("lumberjacking", "Survey"),
    "fish": ("fishing", "Fish"),

    # --- ACTIVITIES ---
    "search": ("harvesting", "Search"),
    "eat": ("foraging", "Eat"), 
    "drink": ("foraging", "Drink"),
    
    # --- Communication ---
    "say": ("say", "Say"),
    "talk": ("talk", "Talk"), 
    "whisper": ("whisper", "Whisper"),
    "bt": ("band", "BT"),

    # --- Trading & Shops ---
    "give": ("trading", "Give"), "accept": ("trading", "Accept"),
    "decline": ("trading", "Decline"), "cancel": ("trading", "Cancel"),
    "exchange": ("trading", "Exchange"),
    "list": ("shop", "List"), "buy": ("shop", "Buy"),
    "sell": ("shop", "Sell"), "appraise": ("shop", "Appraise"),
    
    # --- Grouping & Bands ---
    "group": ("group", "Group"),
    "hold": ("group", "Hold"),
    "join": ("group", "Join"),
    "leave": ("group", "Leave"),
    "disband": ("group", "Disband"),
    "band": ("band", "Band"),
    
    # --- Systems ---
    "help": ("help", "Help"),
    "flag": ("flags", "Flag"), "flags": ("flags", "Flag"),

    # Training
    "check": ("training", "CheckIn"), "checkin": ("training", "CheckIn"),
    "train": ("training", "Train"), "done": ("training", "Done"),
}
# --- END MODIFIED ---

# ---
# --- NEW: Commands that should NEVER be queued (always run immediately)
# ---
ALWAYS_ALLOWED_COMMANDS = {
    'look', 'l', 'examine', 'x', 'investigate',
    'inventory', 'inv', 'wealth', 'score',
    'health', 'hp', 'stats', 'skills', 'experience', 'exp',
    'help', 'flag', 'flags',
    'say', 'whisper', 'talk', 'bt',
    'group', 'band', 'list', 'appraise', # Shop list/appraise are usually safe
    'check', 'checkin', 'train', 'done' # Training commands
}
# --- END NEW ---

DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}


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

            # ---
            # --- THIS IS THE FIX (Bug 1: Grant starting TPs)
            # ---
            ptps, mtps, stps = player._calculate_tps_per_level()
            player.ptps = ptps
            player.mtps = mtps
            player.stps = stps
            # ---
            # --- END FIX
            # ---

            # ---
            # --- NEW: Add start room to visited list ---
            if start_room_id not in player.visited_rooms:
                player.visited_rooms.append(start_room_id)
            # --- END NEW ---
            
            player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
        else:
            # --- THIS IS A LOADING CHARACTER ---
            # --- REFACTORED: Inject world into existing Player ---
            player = Player(world, player_db_data["name"], player_db_data["current_room_id"], player_db_data)
            # --- END REFACTOR ---
            
            # ---
            # --- NEW: Add current room to visited list on load ---
            if player.current_room_id not in player.visited_rooms:
                player.visited_rooms.append(player.current_room_id)
            # --- END NEW ---
            
            # ---
            # --- NEW: Load transient group ID from world state
            # ---
            player.group_id = world.get_player_group_id_on_load(player.name.lower())
            # --- END NEW ---

    # ---
    # --- NEW: Check if this new command should cancel a GOTO
    # ---
    if player.game_state == "playing" and command_line.lower() != "ping":
        if player.is_goto_active:
            player.is_goto_active = False 
            # The background task will see this flag next time it checks
    # ---
    # --- END NEW
    # ---
            
    # --- REFACTORED: Get room from world ---
    # ---
    # --- THIS IS THE BUG FIX (Part 1) ---
    # ---
    # We get a DEEP COPY, so any UIDs we add won't be saved unless
    # we explicitly update the cache.
    room_db_data = world.get_room(player.current_room_id)
    # --- END REFACTOR ---
            
    room = Room(room_db_data.get("room_id", "void"), room_db_data.get("name", "The Void"), room_db_data.get("description", "..."), db_data=room_db_data)

    # ---
    # --- THIS IS THE FIX: Object merging logic is now HERE
    # ---
    live_room_objects = []
    # This list is from the deep-copied room data
    all_objects_stubs = room_db_data.get("objects", []) 
    
    # Get a reference to the stubs list in the *cache* to update UIDs
    room_data_in_cache = world.game_rooms.get(room.room_id, {})
    all_objects_stubs_in_cache = room_data_in_cache.get("objects", [])
    cache_stubs_by_content = {str(s): s for s in all_objects_stubs_in_cache}
    
    if all_objects_stubs:
        for obj_stub in all_objects_stubs: # obj is a dict (a stub) in the list
            node_id = obj_stub.get("node_id")
            monster_id = obj_stub.get("monster_id")
            obj_stub_in_cache = cache_stubs_by_content.get(str(obj_stub)) # Get cache reference

            # 1. Is it a node?
            if node_id:
                template = world.game_nodes.get(node_id)
                if template:
                    merged_obj = copy.deepcopy(template)
                    merged_obj.update(obj_stub) 
                    if "uid" not in merged_obj:
                         merged_obj["uid"] = uuid.uuid4().hex
                         if obj_stub_in_cache:
                            obj_stub_in_cache["uid"] = merged_obj["uid"] # Save UID to cache
                    live_room_objects.append(merged_obj)
            
            # 2. Is it a monster/NPC stub?
            elif monster_id:
                uid = obj_stub.get("uid")
                if not uid:
                    uid = uuid.uuid4().hex
                    if obj_stub_in_cache:
                        obj_stub_in_cache["uid"] = uid # Save UID back to the stub in cache
                
                if uid and world.get_defeated_monster(uid) is not None:
                    continue # It's defeated, skip it
                
                template = world.game_monster_templates.get(monster_id)
                if template:
                    merged_obj = copy.deepcopy(template)
                    merged_obj.update(obj_stub) # Apply instance vars (like the UID)
                    merged_obj["uid"] = uid # Ensure UID is set
                    live_room_objects.append(merged_obj)

            # 3. Is it a simple object (door, corpse, item, etc.)?
            else:
                if obj_stub.get("is_npc") and "uid" not in obj_stub:
                    uid = uuid.uuid4().hex
                    obj_stub["uid"] = uid
                    if obj_stub_in_cache:
                        obj_stub_in_cache["uid"] = uid
                    
                live_room_objects.append(obj_stub)
            
    room.objects = live_room_objects
    # ---
    # --- END FIX
    # ---


    parts = command_line.strip().split()
    command = parts[0].lower() if parts else ""
    args = parts[1:] if parts else []

    # ---
    # --- NEW: COMMAND QUEUE (TYPE-AHEAD) LOGIC ---
    # ---
    # Only check for queueing if we are playing and it's not a utility command
    if player.game_state == "playing" and command_line.lower() != "ping":
        # 1. Check if this is a command we should potentially queue (i.e., NOT always allowed)
        if command not in ALWAYS_ALLOWED_COMMANDS and command in VERB_ALIASES:
            
            # 2. Check Roundtime
            current_time = time.time()
            combat_state = world.get_combat_state(player.name.lower())
            
            if combat_state:
                next_action = combat_state.get("next_action_time", 0)
                remaining_rt = next_action - current_time
                
                if remaining_rt > 0:
                    # Player is in RT.
                    
                    # 3. Type-Ahead Check
                    # If RT is small (< 1.0s) and queue is empty, queue it.
                    if remaining_rt <= 1.0:
                        if len(player.command_queue) == 0:
                            player.command_queue.append(command_line)
                            # Optional: Send a distinct feedback for queued action?
                            # player.send_message(f"[Queued: {command_line}]") 
                            
                            # Return state immediately, do not process verb
                            vitals_data = player.get_vitals()
                            map_data = _get_map_data(player, world)
                            return {
                                "messages": player.messages, 
                                "game_state": player.game_state,
                                "vitals": vitals_data,
                                "map_data": map_data
                            }
                        else:
                            # Queue is full (limit 1 to prevent spam/confusion)
                            pass 
                    
                    # If RT is large (> 1.0s), we just let it fall through.
                    # The verb itself calls `_check_action_roundtime` which sends the "Wait X seconds" message.
    # ---
    # --- END NEW LOGIC ---
    # ---
        
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command == "look":
            # This is a brand new character logging in for the first time.
            # ---
            # --- THIS IS THE FIX: Removed show_room_to_player(player, room);
            # ---
            do_initial_stat_roll(player); player.chargen_step = 1
        
        # --- THIS IS THE FIX ---
        elif player.chargen_step > 0 and command == "look":
            # This is a player RECONNECTING during chargen.
            # The "look" is the login command, not an answer.
            # We re-send the correct prompt for their current step.
            player.send_message(f"**Resuming character creation for {player.name}...**")
            if player.chargen_step == 1:
                send_stat_roll_prompt(player) # Re-prompt for stat rolling
            elif player.chargen_step == 2:
                send_assignment_prompt(player) # Re-prompt for stat assignment
            else:
                # This covers all appearance questions (step 3+)
                get_chargen_prompt(player) # Re-prompt for the correct appearance question
        # --- END FIX ---
            #
            # REMOVED: show_room_to_player(player, room); 
            # do_initial_stat_roll(player); player.chargen_step = 1
            # ---
            # --- END FIX
            # ---
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
            
            # ---
            # --- MODIFIED: Check for learned spells/maneuvers
            # ---
            if not verb_info:
                if command in ["prep", "prepare"]:
                    if player.known_spells: # Check if they know *any* spell
                        verb_info = ("magic", "Prep")
                elif command == "cast":
                     if player.known_spells:
                        verb_info = ("magic", "Cast")
                elif command == "trip":
                    # Check for EITHER the training or final maneuver
                    if "trip" in player.known_maneuvers or "trip_training" in player.known_maneuvers:
                        verb_info = ("maneuvers", "Trip")
            # ---
            # --- END MODIFIED
            # ---

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
    # --- MODIFIED: Use new player method
    # ---
    vitals_data = player.get_vitals()
    # ---
    # --- NEW: Get map data
    # ---
    map_data = _get_map_data(player, world)
    return {
        "messages": player.messages, 
        "game_state": player.game_state,
        "vitals": vitals_data,
        "map_data": map_data # <-- NEW
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