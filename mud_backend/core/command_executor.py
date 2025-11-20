# mud_backend/core/command_executor.py
import importlib.util
import os
import time 
from typing import List, Tuple, Dict, Any, Optional 
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, save_game_state
from mud_backend.core.chargen_handler import (
    handle_chargen_input, 
    do_initial_stat_roll,
    send_stat_roll_prompt,
    send_assignment_prompt,
    get_chargen_prompt
)
from mud_backend.core.room_handler import _get_map_data
from mud_backend import config

CRITICAL_COMMANDS = {
    'quit', 'logout', 'save', 
    'trade', 'exchange', 'give', 'accept', 'buy', 'sell'
}

VERB_ALIASES: Dict[str, Tuple[str, str]] = {
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
    "get": ("item_actions", "Get"), "take": ("item_actions", "Take"),
    "drop": ("item_actions", "Drop"), "put": ("item_actions", "Put"),
    "stow": ("item_actions", "Put"), "pour": ("item_actions", "Pour"),
    "wear": ("equipment", "Wear"), "wield": ("equipment", "Wear"), 
    "remove": ("equipment", "Remove"),
    "inventory": ("inventory", "Inventory"), "inv": ("inventory", "Inventory"),
    "wealth": ("inventory", "Wealth"),
    "swap": ("inventory", "Swap"),
    "look": ("observation", "Look"), "examine": ("observation", "Examine"),
    "investigate": ("observation", "Investigate"),
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
    "skin": ("harvesting", "Skin"), "butcher": ("harvesting", "Skin"),
    "forage": ("foraging", "Forage"), "harvest": ("herbalism", "Harvest"),
    "mine": ("mining", "Mine"), "prospect": ("mining", "Prospect"),
    "chop": ("lumberjacking", "Chop"), "cut": ("lumberjacking", "Chop"),
    "survey": ("lumberjacking", "Survey"), "fish": ("fishing", "Fish"),
    "crush": ("smelting", "Crush"), "wash": ("smelting", "Wash"),
    "charge": ("smelting", "Charge"), "bellow": ("smelting", "Bellow"),
    "vent": ("smelting", "Vent"), "tap": ("smelting", "Tap"),
    "extract": ("smelting", "Extract"), "shingle": ("smelting", "Shingle"),
    "assess": ("assess", "Assess"), "carve": ("woodworking", "Carve"),
    "search": ("harvesting", "Search"), "eat": ("foraging", "Eat"), 
    "drink": ("foraging", "Drink"),
    "say": ("say", "Say"), "talk": ("talk", "Talk"), "whisper": ("whisper", "Whisper"),
    "bt": ("band", "BT"),
    "give": ("trading", "Give"), "accept": ("trading", "Accept"),
    "decline": ("trading", "Decline"), "cancel": ("trading", "Cancel"),
    "exchange": ("trading", "Exchange"),
    "list": ("shop", "List"), "buy": ("shop", "Buy"),
    "sell": ("shop", "Sell"), "appraise": ("shop", "Appraise"),
    "group": ("group", "Group"), "hold": ("group", "Hold"),
    "join": ("group", "Join"), "leave": ("group", "Leave"),
    "disband": ("group", "Disband"), "band": ("band", "Band"),
    "help": ("help", "Help"), "flag": ("flags", "Flag"), "flags": ("flags", "Flag"),
    "check": ("training", "CheckIn"), "checkin": ("training", "CheckIn"),
    "train": ("training", "Train"), "done": ("training", "Done"),
}

ALWAYS_ALLOWED_COMMANDS = {
    'look', 'l', 'examine', 'x', 'investigate',
    'inventory', 'inv', 'wealth', 'score',
    'health', 'hp', 'stats', 'skills', 'experience', 'exp',
    'help', 'flag', 'flags',
    'say', 'whisper', 'talk', 'bt',
    'group', 'band', 'list', 'appraise', 
    'check', 'checkin', 'train', 'done' 
}

DIRECTION_MAP = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "northeast": "northeast", "northwest": "northwest", "southeast": "southeast", "southwest": "southwest",
}


def execute_command(world: 'World', player_name: str, command_line: str, sid: str, account_username: Optional[str] = None) -> Dict[str, Any]:
    """The main function to parse and execute a game command."""
    
    player_info = world.get_player_info(player_name.lower())
    
    if player_info and player_info.get("player_obj"):
        player = player_info["player_obj"]
        player.messages.clear()
    else:
        player_db_data = fetch_player_data(player_name)
        if not player_db_data:
            # New Character
            if not account_username:
                print(f"[EXEC-ERROR] New player {player_name} has no account_username!")
                return {"messages": ["Critical error: Account not found."], "game_state": "error"}

            start_room_id = config.CHARGEN_START_ROOM
            player = Player(world, player_name, start_room_id, {})
            player.account_username = account_username
            player.game_state = "chargen"; player.chargen_step = 0
            
            player.hp = player.max_hp
            player.mana = player.max_mana
            player.stamina = player.max_stamina
            player.spirit = player.max_spirit

            ptps, mtps, stps = player._calculate_tps_per_level()
            player.ptps = ptps
            player.mtps = mtps
            player.stps = stps

            if start_room_id not in player.visited_rooms:
                player.visited_rooms.append(start_room_id)
            
            player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
            world.add_player_to_room_index(player.name.lower(), start_room_id)

        else:
            # Loading Character
            player = Player(world, player_db_data["name"], player_db_data["current_room_id"], player_db_data)
            
            if player.current_room_id not in player.visited_rooms:
                player.visited_rooms.append(player.current_room_id)
            
            player.group_id = world.get_player_group_id_on_load(player.name.lower())
            world.add_player_to_room_index(player.name.lower(), player.current_room_id)

    if player.game_state == "playing" and command_line.lower() != "ping":
        if player.is_goto_active:
            player.is_goto_active = False 
            
    # --- PHASE 2 FIX: Use get_room to ensure hydration, then grab ActiveRoom object ---
    # This guarantees room data is loaded and entities are instantiated.
    world.get_room(player.current_room_id) 
    room = world.active_rooms.get(player.current_room_id)
    
    # Failsafe for void/error
    if not room:
        fallback_data = world.get_room("void")
        # If even void is missing, construct manually
        if not fallback_data:
             room = Room("void", "The Void", "Nothing is here.")
        else:
             room = world.active_rooms.get("void", Room("void", "The Void", "Nothing is here."))
    # ---------------------------------------------------------------------------------

    parts = command_line.strip().split()
    command = parts[0].lower() if parts else ""
    args = parts[1:] if parts else []

    if player.game_state == "playing" and command_line.lower() != "ping":
        if command not in ALWAYS_ALLOWED_COMMANDS and command in VERB_ALIASES:
            current_time = time.time()
            combat_state = world.get_combat_state(player.name.lower())
            
            if combat_state:
                next_action = combat_state.get("next_action_time", 0)
                remaining_rt = next_action - current_time
                
                if remaining_rt > 0:
                    if remaining_rt <= 1.0:
                        if len(player.command_queue) == 0:
                            player.command_queue.append(command_line)
                            
                            vitals_data = player.get_vitals()
                            map_data = _get_map_data(player, world)
                            return {
                                "messages": player.messages, 
                                "game_state": player.game_state,
                                "vitals": vitals_data,
                                "map_data": map_data
                            }
                        else:
                            pass 
        
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command == "look":
            do_initial_stat_roll(player); player.chargen_step = 1
        elif player.chargen_step > 0 and command == "look":
            player.send_message(f"**Resuming character creation for {player.name}...**")
            if player.chargen_step == 1:
                send_stat_roll_prompt(player) 
            elif player.chargen_step == 2:
                send_assignment_prompt(player) 
            else:
                get_chargen_prompt(player) 
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
            _run_verb(world, player, room, command, args, verb_info)
        else:
            if not parts: player.send_message("Invalid command. Type 'list', 'train', or 'done'.")
            else: player.send_message(f"You cannot '{command}' while training. Type 'done' to finish.")
    elif player.game_state == "playing":
        if not parts:
            if command_line.lower() != "ping": player.send_message("What?")
        else:
            verb_info = VERB_ALIASES.get(command)
            
            if not verb_info:
                if command in ["prep", "prepare"]:
                    if player.known_spells: 
                        verb_info = ("magic", "Prep")
                elif command == "cast":
                     if player.known_spells:
                        verb_info = ("magic", "Cast")
                elif command == "trip":
                    if "trip" in player.known_maneuvers or "trip_training" in player.known_maneuvers:
                        verb_info = ("maneuvers", "Trip")

            if not verb_info: player.send_message(f"I don't know the command **'{command}'**.")
            else:
                verb_module, verb_class = verb_info
                if verb_module == "training" and command not in ["check", "checkin"]:
                    player.send_message("You must 'check in' at the inn to train.")
                else: 
                    _run_verb(world, player, room, command, args, verb_info)
    
    world.set_player_info(player.name.lower(), {
        "sid": sid, "player_name": player.name, "current_room_id": player.current_room_id,
        "last_seen": time.time(), "player_obj": player 
    })
    
    if command in CRITICAL_COMMANDS:
        save_game_state(player)
    
    vitals_data = player.get_vitals()
    map_data = _get_map_data(player, world)
    return {
        "messages": player.messages, 
        "game_state": player.game_state,
        "vitals": vitals_data,
        "map_data": map_data 
    }

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
        
        verb_instance = VerbClass(world=world, player=player, room=room, args=args, command=command)
        
        if verb_class_name == "Move" and command in DIRECTION_MAP: verb_instance.args = [DIRECTION_MAP[command]]
        elif verb_class_name == "Exit" and command == "out": verb_instance.args = []
        verb_instance.execute()
    except Exception as e:
        player.send_message(f"An error occurred: {e}")
        print(f"Error running command '{command}': {e}")
        import traceback
        traceback.print_exc()