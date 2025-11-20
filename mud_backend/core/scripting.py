# mud_backend/core/scripting.py
import re
import uuid
import copy
import random
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
    from mud_backend.core.game_objects import Player, Room

# --- SCRIPT COMMAND LIBRARY ---
# These are the functions you can call from your JSON triggers.

def spawn_mob(world: 'World', player: 'Player', room: 'Room', mob_template_id: str):
    """
    Spawns a monster in the current room.
    Usage: "spawn_mob(goblin_grunt)"
    """
    template = world.game_monster_templates.get(mob_template_id)
    if not template:
        print(f"[SCRIPT ERROR] spawn_mob: Template '{mob_template_id}' not found.")
        return

    new_uid = uuid.uuid4().hex
    new_mob = copy.deepcopy(template)
    new_mob["uid"] = new_uid
    
    # Add to Active Room
    room.objects.append(new_mob)
    
    # Register in AI Index (Required for Phase 1/2 Architecture)
    world.register_mob(new_uid, room.room_id)
    
    # Notify Room
    spawn_msg = new_mob.get("spawn_message_arrival", f"A {new_mob['name']} appears!")
    world.broadcast_to_room(room.room_id, spawn_msg, "ambient_spawn")

def echo(world: 'World', player: 'Player', room: 'Room', message: str):
    """
    Sends a message to the player who triggered the event.
    Usage: "echo(You feel a cold shiver run down your spine.)"
    """
    player.send_message(message)

def echo_room(world: 'World', player: 'Player', room: 'Room', message: str):
    """
    Sends a message to everyone in the room.
    Usage: "echo_room(The ground rumbles ominously.)"
    """
    world.broadcast_to_room(room.room_id, message, "message")

def heal(world: 'World', player: 'Player', room: 'Room', amount: str):
    """
    Heals the player.
    Usage: "heal(50)"
    """
    try:
        amt = int(amount)
        player.hp = min(player.hp + amt, player.max_hp)
        player.send_message(f"You feel rejuvenated. (+{amt} HP)")
    except ValueError:
        print(f"[SCRIPT ERROR] heal: Invalid amount '{amount}'")

def teleport(world: 'World', player: 'Player', room: 'Room', target_room_id: str):
    """
    Teleports the player to a specific room.
    Usage: "teleport(town_square)"
    """
    # We use the player's existing move logic to handle the index updates
    player.move_to_room(target_room_id, "You are suddenly whisked away!")

# --- MAPPING ---
SCRIPT_COMMANDS = {
    "spawn_mob": spawn_mob,
    "echo": echo,
    "echo_room": echo_room,
    "heal": heal,
    "teleport": teleport,
}

# --- PARSER ---
def execute_script(world: 'World', player: 'Player', room: 'Room', script_string: str):
    """
    Parses and executes a script string.
    Format: "command_name(arg1, arg2, ...)"
    Example: "spawn_mob(goblin_grunt)"
    """
    if not script_string:
        return

    # Regex to capture "command(args)"
    # This simple regex handles basic arguments. 
    # For complex args with commas inside strings, a real lexer would be needed.
    match = re.match(r"(\w+)\((.*)\)", script_string.strip())
    
    if not match:
        print(f"[SCRIPT ERROR] Invalid script syntax: {script_string}")
        return

    command_name = match.group(1)
    args_str = match.group(2)
    
    # Split args by comma, strip quotes/spaces
    args = [arg.strip().strip('"').strip("'") for arg in args_str.split(',') if arg.strip()]
    
    func = SCRIPT_COMMANDS.get(command_name)
    if func:
        try:
            func(world, player, room, *args)
        except TypeError as e:
            print(f"[SCRIPT ERROR] Argument mismatch for '{command_name}': {e}")
    else:
        print(f"[SCRIPT ERROR] Unknown command: '{command_name}'")