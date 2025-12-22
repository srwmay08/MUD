# mud_backend/core/scripting.py
import uuid
import copy
import random
import traceback
import time
from typing import TYPE_CHECKING, Optional, Dict, Any

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
    from mud_backend.core.game_objects import Player, Room

# --- SCRIPT API ---
# This class defines the "verbs" available inside your scripts.
class ScriptAPI:
    def __init__(self, world: 'World', player: 'Player', room: 'Room'):
        self.world = world
        self.player = player
        self.room = room

    def spawn_mob(self, mob_template_id: str):
        """
        Spawns a monster in the current room.
        Usage: spawn_mob("goblin_grunt")
        """
        template = self.world.game_monster_templates.get(mob_template_id)
        if not template:
            print(f"[SCRIPT ERROR] spawn_mob: Template '{mob_template_id}' not found.")
            return

        new_uid = uuid.uuid4().hex
        new_mob = copy.deepcopy(template)
        new_mob["uid"] = new_uid
        
        # Add to Active Room
        self.room.objects.append(new_mob)
        
        # Register in AI Index
        self.world.register_mob(new_uid, self.room.room_id)
        
        # Notify Room
        spawn_msg = new_mob.get("spawn_message_arrival", f"A {new_mob['name']} appears!")
        self.world.broadcast_to_room(self.room.room_id, spawn_msg, "ambient_spawn")

    def echo(self, message: str):
        """
        Sends a message to the player.
        Usage: echo("You hear a spooky sound.")
        """
        self.player.send_message(message)

    def echo_room(self, message: str, skip_player: bool = False):
        """
        Sends a message to everyone in the room.
        Usage: echo_room("The ground shakes.", skip_player=True)
        """
        skip_sid = self.player.uid if skip_player else None
        self.world.broadcast_to_room(self.room.room_id, message, "message", skip_sid=skip_sid)

    def heal(self, amount: int):
        """
        Heals the player.
        Usage: heal(50)
        """
        try:
            amt = int(amount)
            self.player.hp = min(self.player.hp + amt, self.player.max_hp)
            self.player.send_message(f"You feel rejuvenated. (+{amt} HP)")
        except ValueError:
            print(f"[SCRIPT ERROR] heal: Invalid amount '{amount}'")

    def teleport(self, target_room_id: str):
        """
        Teleports the player.
        Usage: teleport("town_square")
        """
        self.player.move_to_room(target_room_id, "You are suddenly whisked away!")

    def grant_xp(self, amount: int):
        """
        Grants XP.
        Usage: grant_xp(100)
        """
        self.player.grant_experience(amount, source="script")

    def has_item(self, item_id: str) -> bool:
        """
        Checks if player has an item in inventory or equipped.
        Usage: if has_item("gate_key"): ...
        """
        if item_id in self.player.inventory:
            return True
        for slot, worn_id in self.player.worn_items.items():
            if worn_id == item_id:
                return True
        return False

    def take_item(self, item_id: str):
        """
        Removes an item from the player (inventory or equipped).
        Usage: take_item("gate_key")
        """
        if item_id in self.player.inventory:
            self.player.inventory.remove(item_id)
            self.player.send_message(f"You lose {item_id}.") # Ideally lookup name
            return

        for slot, worn_id in self.player.worn_items.items():
            if worn_id == item_id:
                self.player.worn_items[slot] = None
                self.player.send_message(f"You lose {item_id}.")
                return

    def give_item(self, item_id: str, count: int = 1):
        """
        Gives an item to the player. Tries hands first, then inventory.
        Usage: give_item("fresh_water")
        """
        item_template = self.world.game_items.get(item_id)
        if not item_template:
            print(f"[SCRIPT ERROR] give_item: Template '{item_id}' not found.")
            self.player.send_message(f"Error: Item '{item_id}' does not exist.")
            return

        for _ in range(count):
            new_item = copy.deepcopy(item_template)
            new_item["uid"] = uuid.uuid4().hex
            
            # 1. Try Main Hand
            if self.player.worn_items.get("mainhand") is None:
                self.player.worn_items["mainhand"] = new_item
                self.player.send_message(f"You take {item_template['name']} in your main hand.")
            # 2. Try Off Hand
            elif self.player.worn_items.get("offhand") is None:
                self.player.worn_items["offhand"] = new_item
                self.player.send_message(f"You take {item_template['name']} in your off hand.")
            # 3. Fallback to Inventory
            else:
                self.player.inventory.append(new_item)
                self.player.send_message(f"You receive {item_template['name']} (placed in pack).")

    # --- NEW METHODS ---
    def start_timer(self, seconds: int, callback_script: str):
        """
        Starts a background timer that executes another script script when done.
        Usage: start_timer(60, "spawn_mob('boss_orc')")
        """
        def timer_task():
            self.world.socketio.sleep(seconds)
            # We need to re-fetch objects to ensure they are valid context
            p = self.world.get_player_obj(self.player.name.lower())
            r = self.world.get_active_room_safe(self.room.room_id)
            if p and r and p.current_room_id == r.room_id:
                execute_script(self.world, p, r, callback_script)
        
        self.world.socketio.start_background_task(timer_task)

    def fail_quest(self, quest_id: str):
        """Marks a quest as failed via counters."""
        self.player.quest_counters[f"{quest_id}_failed"] = 1
        self.player.send_message(f"**Quest Failed!**")

    def check_flag(self, flag_name: str) -> str:
        """Checks a player flag (e.g. 'sneaking')."""
        return self.player.flags.get(flag_name, "off")

    def alert_room(self, message: str):
        self.world.broadcast_to_room(self.room.room_id, f"**ALARM**: {message}", "message")

# --- EXECUTION ENGINE ---

def execute_script(world: 'World', player: 'Player', room: 'Room', script_string: str):
    """
    Compiles and executes a string as Python code within a restricted scope.
    """
    if not script_string:
        return

    # 1. Initialize the API
    api = ScriptAPI(world, player, room)

    # 2. Define the Safe Scope (The "Globals" available to the script)
    # We expose the API methods directly so scripts look cleaner.
    safe_scope = {
        # Objects (Read properties like player.level, but be careful with modifications)
        "player": player, 
        "room": room,
        
        # API Methods
        "spawn_mob": api.spawn_mob,
        "echo": api.echo,
        "echo_room": api.echo_room,
        "heal": api.heal,
        "teleport": api.teleport,
        "grant_xp": api.grant_xp,
        "has_item": api.has_item,
        "take_item": api.take_item,
        "give_item": api.give_item,
        "start_timer": api.start_timer,
        "fail_quest": api.fail_quest,
        "check_flag": api.check_flag,
        "alert_room": api.alert_room,
        
        # Utilities
        "random": random,
        "time": time,
        
        # Safety: Block access to dangerous internals
        "__builtins__": {
            "print": print, # Optional: allow server console logging
            "int": int,
            "str": str,
            "len": len,
            "list": list,
            "dict": dict,
            "range": range
            # DO NOT include 'open', 'import', 'exec', 'eval' here
        }
    }

    # 3. Execute
    try:
        # We wrap the script in a try/except block for robustness
        exec(script_string, safe_scope)
    except Exception as e:
        print(f"[SCRIPT ERROR] Error executing script in Room {room.room_id}:")
        print(f"Script: {script_string}")
        print(f"Error: {e}")
        traceback.print_exc()