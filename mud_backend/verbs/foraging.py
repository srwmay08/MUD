# mud_backend/verbs/foraging.py
import random
import time
import copy
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: from mud_backend.core import game_state ---
from typing import Tuple, Optional, TYPE_CHECKING # <-- NEW
# --- NEW: Import show_room_to_player ---
from mud_backend.core.room_handler import show_room_to_player
# --- END NEW ---

# --- NEW: Type checking for Player ---
if TYPE_CHECKING:
    from mud_backend.core.game_objects import Player
# --- END NEW ---


# --- (Helper _find_item_in_hands is unchanged) ---
def _find_item_in_hands(player, target_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Finds the first item_id in a player's hands that matches.
    Returns (item_id, slot_name) or (None, None)
    """
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            # --- FIX: Use player.world.game_items ---
            item_data = player.world.game_items.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_id, slot
    return None, None

def _has_tool(player, required_tool_type: str) -> bool:
    """Checks if the player is wielding a tool of the required type."""
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            item_data = player.world.game_items.get(item_id)
            # --- FIX: Check for small_edged as a fallback for herbalism ---
            if item_data and (item_data.get("tool_type") == required_tool_type or
                              (required_tool_type == "herbalism" and item_data.get("skill") == "small_edged")):
                return True
    return False

# ---
# --- NEW: CENTRAL ROUNDTIME HELPER FUNCTIONS
# ---

def _check_action_roundtime(player: 'Player', action_type: str) -> bool:
    """
    Checks if the player is in roundtime from any action.
    Sends a message and returns True if they are, False otherwise.
    
    action_type: 'speak', 'move', 'stance', 'attack', 'cast', 'other'
    """
    player_id = player.name.lower()
    current_time = time.time()
    
    rt_data = player.world.get_combat_state(player_id)
    if rt_data:
        next_action_time = rt_data.get("next_action_time", 0)
        if current_time < next_action_time:
            wait_time = next_action_time - current_time
            rt_type = rt_data.get("rt_type", "hard")
            
            # --- Check Hard vs Soft RT rules ---
            if rt_type == "hard":
                if action_type == "speak":
                    return False # Allow speaking
                else:
                    player.send_message(f"You are not ready to do that yet. (Wait {wait_time:.1f}s)")
                    return True # Block
            
            elif rt_type == "soft":
                if action_type in ["move", "stance", "speak"]:
                    return False # Allow move/stance/speak
                else:
                    player.send_message(f"You must wait for your concentration to return. (Wait {wait_time:.1f}s)")
                    return True # Block attack/cast/other
            
            return True # Default block
            
    return False # Player is free

def _set_action_roundtime(player: 'Player', duration_seconds: float, message: str = "", rt_type: str = "hard"):
    """
    Sets a non-combat action roundtime for the player and sends a message.
    If 'message' is provided, it's used *instead* of the default RT message.
    rt_type: 'hard' (red bar) or 'soft' (blue bar)
    """
    player_id = player.name.lower()
    final_duration = max(0.5, duration_seconds) # Ensure a minimum RT
    
    # --- ADD LOCK: Use player.world ---
    with player.world.combat_lock:
        # Get existing state or a new dict
        rt_data = player.world.get_combat_state(player_id)
        if rt_data is None:
            rt_data = {}
        
        rt_data["next_action_time"] = time.time() + final_duration
        rt_data["state_type"] = "action" 
        rt_data["rt_type"] = rt_type # <-- NEW
        
        # Explicitly remove combat keys in case they were stuck
        rt_data.pop("target_id", None)
        rt_data.pop("current_room_id", None)
        
        # Put it back in the global state
        player.world.set_combat_state(player_id, rt_data)
    # --- END LOCK ---
    
    # Send the RT message
    if message:
        player.send_message(message)
    
    # Send the generic RT message *only* if no custom message was provided
    # and the duration is long enough to warrant it.
    elif not message and final_duration >= 0.5:
        # Don't show "Roundtime" for soft RT, as magic system has its own message
        if rt_type == "hard":
            player.send_message(f"Roundtime: {final_duration:.1f}s")

# ---
# --- END CENTRAL RT HELPERS
# ---


class Forage(BaseVerb):
    """
    Handles the 'forage' (sense) command.
    """
    
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return
        
        # (Assuming 'survival' is the skill for this)
        survival_skill = self.player.skills.get("survival", 0)
        
        # --- NEW: Tool Check ---
        if not _has_tool(self.player, "herbalism"):
            self.player.send_message("You need a sickle or knife to properly forage for plants.")
            return
        # --- END NEW ---
        
        _set_action_roundtime(self.player, 3.0, rt_type="hard")
             
        self.player.send_message("You scan the area for forageable plants...")
        
        # ---
        # --- NEW REVEAL LOGIC
        # ---
        found_nodes_list = []
        refresh_room = False
        
        hidden_objects = self.room.db_data.get("hidden_objects", [])
        for i in range(len(hidden_objects) - 1, -1, -1):
            obj_stub = hidden_objects[i]
            
            if obj_stub.get("node_type") == "herbalism":
                dc = obj_stub.get("perception_dc", 999)
                roll = survival_skill + random.randint(1, 100)
                
                if roll >= dc:
                    found_stub = self.room.db_data["hidden_objects"].pop(i)
                    full_node = copy.deepcopy(self.world.game_nodes.get(found_stub["node_id"]))
                    if not full_node: continue
                    
                    full_node.update(found_stub)
                    self.room.objects.append(full_node)
                    
                    found_nodes_list.append(full_node.get("name", "a plant"))
                    refresh_room = True

        if refresh_room:
            # ---
            # --- THIS IS THE FIX: Save the room state
            # ---
            self.world.save_room(self.room)
            # ---
            # --- END FIX
            # ---
            
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} spots {found_nodes_list[0]}!", 
                "message",
                skip_sid=None
            )
            
            for sid, data in self.world.get_all_players_info():
                if data["current_room_id"] == self.room.room_id:
                    player_obj = data.get("player_obj")
                    if player_obj:
                        player_obj.messages.clear()
                        show_room_to_player(player_obj, self.room)
                        self.world.socketio.emit('command_response', 
                            {'messages': player_obj.messages, 'vitals': player_obj.get_vitals()}, 
                            to=sid)
        else:
            self.player.send_message("You do not sense any plants of interest here.")
        # ---
        # --- END NEW LOGIC
        # ---


class Eat(BaseVerb):
    """
    Handles the 'eat' command for herbs and food.
    """
    def execute(self):
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player, action_type="other"):
            return
        # --- END NEW ---

        if not self.args:
            self.player.send_message("Eat what?")
            return

        target_name = " ".join(self.args).lower()
        # --- THIS IS THE FIX ---
        item_id, item_location = _find_item_in_hands(self.player, target_name)
        
        if not item_id:
            self.player.send_message(f"You are not holding a '{target_name}' to eat.")
            return
        # --- END FIX ---

        # --- FIX: Use self.world.game_items ---
        item_data = self.world.game_items.get(item_id)
        if not item_data:
            self.player.send_message("That item seems to have vanished.")
            return
            
        item_name = item_data.get("name", "the item")
        use_verb = item_data.get("use_verb", "eat")

        if use_verb != "eat":
            self.player.send_message(f"You cannot eat {item_name}. Try '{use_verb.upper()}' instead.")
            return
            
        # Apply the effect
        effect = item_data.get("effect_on_use", {})
        if effect.get("heal_hp"):
            hp_to_heal = int(effect.get("heal_hp", 0))
            if hp_to_heal > 0:
                self.player.hp = min(self.player.max_hp, self.player.hp + hp_to_heal)
                self.player.send_message(f"You eat {item_name}. You feel a surge of vitality!")
                self.player.send_message(f"(You heal for {hp_to_heal} HP. Current HP: {self.player.hp}/{self.player.max_hp})")
            else:
                self.player.send_message(f"You eat {item_name}, but nothing seems to happen.")
        else:
            self.player.send_message(f"You eat {item_name}, but nothing seems to happen.")

        # --- THIS IS THE FIX ---
        # Remove the item from the hand it was in
        self.player.worn_items[item_location] = None
        # --- END FIX ---
        
        # --- NEW: Set RT ---
        _set_action_roundtime(self.player, 3.0, rt_type="hard") # 3s RT for eating
        # --- END NEW ---


class Drink(BaseVerb):
    """
    Handles the 'drink' command for potions.
    """
    def execute(self):
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player, action_type="other"):
            return
        # --- END NEW ---

        if not self.args:
            self.player.send_message("Drink what?")
            return

        target_name = " ".join(self.args).lower()
        # --- THIS IS THE FIX ---
        item_id, item_location = _find_item_in_hands(self.player, target_name)
        
        if not item_id:
            self.player.send_message(f"You are not holding a '{target_name}' to drink.")
            return
        # --- END FIX ---

        # --- FIX: Use self.world.game_items ---
        item_data = self.world.game_items.get(item_id)
        if not item_data:
            self.player.send_message("That item seems to have vanished.")
            return
            
        item_name = item_data.get("name", "the item")
        use_verb = item_data.get("use_verb", "drink")

        if use_verb != "drink":
            self.player.send_message(f"You cannot drink {item_name}. Try '{use_verb.upper()}' instead.")
            return

        # (Logic is identical to EAT for now)
        effect = item_data.get("effect_on_use", {})
        if effect.get("heal_hp"):
            hp_to_heal = int(effect.get("heal_hp", 0))
            if hp_to_heal > 0:
                self.player.hp = min(self.player.max_hp, self.player.hp + hp_to_heal)
                self.player.send_message(f"You drink {item_name}. You feel a surge of vitality!")
                self.player.send_message(f"(You heal for {hp_to_heal} HP. Current HP: {self.player.hp}/{self.player.max_hp})")
            else:
                self.player.send_message(f"You drink {item_name}, but nothing seems to happen.")
        else:
            self.player.send_message(f"You drink {item_name}, but nothing seems to happen.")

        # --- THIS IS THE FIX ---
        # Remove the item from the hand it was in
        self.player.worn_items[item_location] = None
        # --- END FIX ---
        
        # --- NEW: Set RT ---
        _set_action_roundtime(self.player, 3.0, rt_type="hard") # 3s RT for drinking
        # --- END NEW ---