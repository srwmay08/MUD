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
from mud_backend.core.skill_handler import show_skill_list 
from mud_backend.core import game_state
from mud_backend.core.game_loop import environment
from mud_backend.core.game_loop import monster_respawn
from mud_backend import config

# --- VERB ALIASES ---
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
    "say": ("say", "Say"), "ping": ("tick", "Tick"),
    "give": ("trading", "Give"), "accept": ("trading", "Accept"),
    "decline": ("trading", "Decline"), "cancel": ("trading", "Cancel"),
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

def execute_command(player_name: str, command_line: str, sid: str) -> Dict[str, Any]:
    """The main function to parse and execute a game command."""
    player_info = None
    with game_state.PLAYER_LOCK:
        player_info = game_state.ACTIVE_PLAYERS.get(player_name.lower())
    
    if player_info and player_info.get("player_obj"):
        player = player_info["player_obj"]
        player.messages.clear()
    else:
        player_db_data = fetch_player_data(player_name)
        if not player_db_data:
            start_room_id = config.CHARGEN_START_ROOM
            player = Player(player_name, start_room_id, {})
            player.game_state = "chargen"; player.chargen_step = 0; player.hp = player.max_hp 
            player.send_message(f"Welcome, **{player.name}**! You awaken from a hazy dream...")
        else:
            player = Player(player_db_data["name"], player_db_data["current_room_id"], player_db_data)
            
    room_db_data = None
    with game_state.ROOM_LOCK:
        room_db_data = copy.deepcopy(game_state.GAME_ROOMS.get(player.current_room_id))

    if not room_db_data:
        print(f"[WARN] Room {player.current_room_id} not in cache! Fetching from DB.")
        room_db_data = fetch_room_data(player.current_room_id)
        if room_db_data and room_db_data.get("room_id") != "void":
            with game_state.ROOM_LOCK: game_state.GAME_ROOMS[player.current_room_id] = room_db_data
            room_db_data = copy.deepcopy(room_db_data)
            
    room = Room(room_db_data.get("room_id", "void"), room_db_data.get("name", "The Void"), room_db_data.get("description", "..."), db_data=room_db_data)

    live_room_objects = []
    all_objects = room_db_data.get("objects", []) 
    if all_objects:
        for obj in all_objects:
            monster_id = obj.get("monster_id")
            if monster_id:
                is_defeated = False
                with game_state.COMBAT_LOCK: is_defeated = monster_id in game_state.DEFEATED_MONSTERS
                if not is_defeated:
                    if "stats" not in obj:
                        template = game_state.GAME_MONSTER_TEMPLATES.get(monster_id)
                        if template:
                            obj.update(copy.deepcopy(template))
                            live_room_objects.append(obj)
                        else: print(f"[ERROR] Monster {monster_id} in room {room.room_id} has no template!")
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
        if verb_info: _run_verb(player, room, command, args, verb_info)
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
                else: _run_verb(player, room, command, args, verb_info)
    
    with game_state.PLAYER_LOCK:
        game_state.ACTIVE_PLAYERS[player.name.lower()] = {
            "sid": sid, "player_name": player.name, "current_room_id": player.current_room_id,
            "last_seen": time.time(), "player_obj": player 
        }
    save_game_state(player)
    return {"messages": player.messages, "game_state": player.game_state}

def _run_verb(player: Player, room: Room, command: str, args: List[str], verb_info: Tuple[str, str]):
    try:
        verb_name, verb_class_name = verb_info
        verb_file_path = os.path.join(os.path.dirname(__file__), '..', 'verbs', f'{verb_name}.py')
        verb_module_name = f"mud_backend.verbs.{verb_name}"
        spec = importlib.util.spec_from_file_location(verb_module_name, verb_file_path)
        if spec is None: raise FileNotFoundError(f"Verb file '{verb_name}.py' not found")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        VerbClass = getattr(module, verb_class_name)
        verb_instance = VerbClass(player=player, room=room, args=args, command=command)
        if verb_class_name == "Move" and command in DIRECTION_MAP: verb_instance.args = [DIRECTION_MAP[command]]
        elif verb_class_name == "Exit" and command == "out": verb_instance.args = []
        verb_instance.execute()
    except Exception as e:
        player.send_message(f"An error occurred: {e}")
        print(f"Error running command '{command}': {e}")
        import traceback
        traceback.print_exc()