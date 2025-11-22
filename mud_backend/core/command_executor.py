# mud_backend/core/command_executor.py
import time
import pkgutil
import importlib
import os
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend.core.game_objects import Player, Room
from mud_backend.core.db import fetch_player_data, save_game_state
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.chargen_handler import (
    handle_chargen_input, 
    do_initial_stat_roll,
    send_stat_roll_prompt,
    send_assignment_prompt,
    get_chargen_prompt
)
from mud_backend.core.room_handler import _get_map_data
from mud_backend import config

# Define critical commands that trigger a save
CRITICAL_COMMANDS = {
    'quit', 'logout', 'save', 
    'trade', 'exchange', 'give', 'accept', 'buy', 'sell'
}

# Always allowed, even in combat/other states (logic handled in verbs)
ALWAYS_ALLOWED_COMMANDS = {
    'look', 'l', 'inventory', 'inv', 'help', 'say', 'quit'
}

def _load_verbs():
    """
    Dynamically discovers and imports all modules in the verbs directory.
    This triggers the @VerbRegistry.register decorators.
    """
    # Path to the verbs package
    verbs_path = os.path.join(os.path.dirname(__file__), '..', 'verbs')
    
    # Walk through all modules in the package
    for _, name, _ in pkgutil.iter_modules([verbs_path]):
        full_module_name = f"mud_backend.verbs.{name}"
        if full_module_name not in  importlib.sys.modules:
            importlib.import_module(full_module_name)

# Load verbs at module level
_load_verbs()

def execute_command(world: 'World', player_name: str, command_line: str, sid: str, account_username: Optional[str] = None) -> Dict[str, Any]:
    """The main function to parse and execute a game command."""
    
    # 1. Player Session Management
    player_info = world.get_player_info(player_name.lower())
    
    if player_info and player_info.get("player_obj"):
        player = player_info["player_obj"]
        player.messages.clear()
    else:
        player_db_data = fetch_player_data(player_name)
        if not player_db_data:
            # New Character Logic
            if not account_username:
                print(f"[EXEC-ERROR] New player {player_name} has no account_username!")
                return {"messages": ["Critical error: Account not found."], "game_state": "error"}

            start_room_id = config.CHARGEN_START_ROOM
            player = Player(world, player_name, start_room_id, {})
            player.account_username = account_username
            player.game_state = "chargen"; player.chargen_step = 0
            
            # Initialize stats for new char
            player.hp = player.max_hp
            player.mana = player.max_mana
            player.stamina = player.max_stamina
            player.spirit = player.max_spirit
            ptps, mtps, stps = player._calculate_tps_per_level()
            player.ptps, player.mtps, player.stps = ptps, mtps, stps

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

    # Check Freeze
    if player.flags.get("frozen", "off") == "on":
        if command_line.strip().lower() not in ['quit', 'help']:
            player.send_message("You are frozen solid and cannot act.")
            vitals_data = player.get_vitals()
            map_data = _get_map_data(player, world)
            return {
                "messages": player.messages, 
                "game_state": player.game_state,
                "vitals": vitals_data,
                "map_data": map_data,
                "leave_message": None 
            }

    # 2. State Management Updates
    if player.game_state == "playing" and command_line.lower() != "ping":
        if player.is_goto_active:
            player.is_goto_active = False 
            player.goto_id = None
            
    # Ensure room hydration
    world.room_manager.get_room(player.current_room_id) 
    room = world.room_manager.get_active_room_safe(player.current_room_id)
    
    if not room:
        room = Room("void", "The Void", "Nothing is here.")

    # 3. Command Parsing
    parts = command_line.strip().split()
    command = parts[0].lower() if parts else ""
    args = parts[1:] if parts else []

    # 4. Game State Handling
    if player.game_state == "chargen":
        if player.chargen_step == 0 and command == "look":
            do_initial_stat_roll(player); player.chargen_step = 1
        elif player.chargen_step > 0 and command == "look":
            player.send_message(f"**Resuming character creation for {player.name}...**")
            if player.chargen_step == 1: send_stat_roll_prompt(player) 
            elif player.chargen_step == 2: send_assignment_prompt(player) 
            else: get_chargen_prompt(player) 
        else: 
            handle_chargen_input(player, command_line)

    elif player.game_state == "training":
        # --- FIXED: Added 'levelup' and 'level' to allowed training commands ---
        if command in ["list", "train", "done", "check", "checkin", "levelup", "level"]:
             _run_verb(world, player, room, command, args)
        elif command == "look":
             _run_verb(world, player, room, command, args)
             if args: player.send_message("You must 'done' training to interact with objects.")
        else:
            if not parts: player.send_message("Invalid command. Type 'list', 'train', 'levelup', or 'done'.")
            else: player.send_message(f"You cannot '{command}' while training. Type 'done' to finish.")

    elif player.game_state == "playing":
        if not parts:
            if command_line.lower() != "ping": player.send_message("What?")
        else:
            if _run_verb(world, player, room, command, args):
                pass 
            else:
                player.send_message(f"I don't know the command **'{command}'**.")
    
    # 6. Post-Execution Updates
    world.set_player_info(player.name.lower(), {
        "sid": sid, "player_name": player.name, "current_room_id": player.current_room_id,
        "last_seen": time.time(), "player_obj": player 
    })
    
    if command in CRITICAL_COMMANDS:
        save_game_state(player)
    
    vitals_data = player.get_vitals()
    map_data = _get_map_data(player, world)
    
    leave_msg = getattr(player, "temp_leave_message", None)
    player.temp_leave_message = None 

    return {
        "messages": player.messages, 
        "game_state": player.game_state,
        "vitals": vitals_data,
        "map_data": map_data,
        "leave_message": leave_msg 
    }

def _run_verb(world: 'World', player: Player, room: Room, command: str, args: List[str]) -> bool:
    """
    Instantiates and executes the verb class found in the registry.
    Returns True if a verb was found and executed, False otherwise.
    """
    verb_info = VerbRegistry.get_verb_info(command)
    
    if verb_info:
        VerbClass, admin_only = verb_info
        
        is_admin = getattr(player, "is_admin", False)
        if admin_only and not is_admin:
            return False 
            
        try:
            verb_instance = VerbClass(world=world, player=player, room=room, args=args, command=command)
            verb_instance.execute()
            return True
        except Exception as e:
            player.send_message(f"An error occurred: {e}")
            print(f"Error running command '{command}': {e}")
            import traceback
            traceback.print_exc()
            return True 
            
    return False