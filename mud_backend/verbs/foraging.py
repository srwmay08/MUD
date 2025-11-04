# mud_backend/verbs/foraging.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import game_state
from typing import Tuple, Optional # <-- NEW

# --- NEW HELPER ---
def _find_item_in_hands(player, target_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Finds the first item_id in a player's hands that matches.
    Returns (item_id, slot_name) or (None, None)
    """
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            item_data = game_state.GAME_ITEMS.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_id, slot
    return None, None

# --- NEW HELPER ---
def _set_action_roundtime(player, duration_seconds: float):
    """Sets a non-combat action roundtime for the player."""
    player_id = player.name.lower()
    # Get existing state (could be combat RT) or a new dict
    rt_data = game_state.COMBAT_STATE.get(player_id, {})
    # Set the next action time
    rt_data["next_action_time"] = time.time() + duration_seconds
    # Put it back in the global state
    game_state.COMBAT_STATE[player_id] = rt_data

class Forage(BaseVerb):
    """
    Handles the 'forage' command.
    FORAGE {adjective} {noun}
    FORAGE SENSE
    """
    
    def execute(self):
        # --- NEW: Roundtime Check ---
        player_id = self.player.name.lower()
        current_time = time.time()
        
        if player_id in game_state.COMBAT_STATE:
            rt_data = game_state.COMBAT_STATE[player_id]
            if current_time < rt_data.get("next_action_time", 0):
                wait_time = rt_data["next_action_time"] - current_time
                self.player.send_message(f"You are not ready to do that yet. (Wait {wait_time:.1f}s)")
                return
        # --- END RT Check ---

        if not self.args:
            self.player.send_message("What are you trying to forage for? (e.g., FORAGE VIRIDIAN LEAF or FORAGE SENSE)")
            _set_action_roundtime(self.player, 1.0) # 1s RT for syntax error
            return

        args_str = " ".join(self.args).lower()
        player_survival = self.player.skills.get("survival", 0)
        
        # --- Handle FORAGE SENSE ---
        if args_str == "sense":
            if player_survival >= 25:
                self.player.send_message("You scan the area for forageable plants...")
                forageable_items = self.room.db_data.get("forageable_items", [])
                if not forageable_items:
                    self.player.send_message("You do not sense any plants of interest here.")
                    _set_action_roundtime(self.player, 3.0) # 3s RT
                    return
                
                self.player.send_message("You sense the following plants are present:")
                for item in forageable_items:
                    self.player.send_message(f"- {item.get('item_name', 'an unknown plant').title()}")
                _set_action_roundtime(self.player, 4.0) # 4s RT
            else:
                self.player.send_message("You do not have enough skill in Survival to sense nearby plants.")
                _set_action_roundtime(self.player, 2.0) # 2s RT
            return

        # --- Handle FORAGE <item> ---
        
        # Strip "for" if present
        if args_str.startswith("for "):
            target_name = args_str[4:].strip()
        else:
            target_name = args_str
            
        if not target_name:
            self.player.send_message("Forage for what?")
            _set_action_roundtime(self.player, 1.0) # 1s RT
            return

        # Check the room's forage table
        forageable_items = self.room.db_data.get("forageable_items", [])
        found_plant = None
        for item in forageable_items:
            if item.get("item_name", "").lower() == target_name:
                found_plant = item
                break
        
        if not found_plant:
            self.player.send_message("You forage... but find nothing.")
            # 10s base RT, reduced by 1s per 15 ranks of survival
            rt_seconds = max(3.0, 10.0 - (player_survival / 15.0))
            _set_action_roundtime(self.player, rt_seconds)
            return

        # We found a matching plant, now roll against the DC
        item_id = found_plant.get("item_id")
        item_dc = found_plant.get("dc", 100)
        item_data = game_state.GAME_ITEMS.get(item_id)
        
        if not item_data:
            self.player.send_message("You forage... but find nothing. (Error: Item data missing)")
            _set_action_roundtime(self.player, 3.0) # 3s RT
            return
            
        item_name = item_data.get("name", "a plant")
        
        # Roll: Skill + d100 vs DC
        roll = player_survival + random.randint(1, 100)
        
        if roll >= item_dc:
            # Success!
            self.player.inventory.append(item_id)
            # 8s base RT, reduced by 1s per 15 ranks
            rt_seconds = max(2.0, 8.0 - (player_survival / 15.0))
            self.player.send_message(f"You forage... and find {item_name}! (Roundtime: {rt_seconds:.1f}s)")
            _set_action_roundtime(self.player, rt_seconds)
        else:
            # Failure
            # 12s base RT, reduced by 1s per 15 ranks
            rt_seconds = max(4.0, 12.0 - (player_survival / 15.0))
            self.player.send_message(f"You forage for {item_name} but fail to find any. (Roundtime: {rt_seconds:.1f}s)")
            _set_action_roundtime(self.player, rt_seconds)

class Eat(BaseVerb):
    """
    Handles the 'eat' command for herbs and food.
    """
    def execute(self):
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

        item_data = game_state.GAME_ITEMS.get(item_id)
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

class Drink(BaseVerb):
    """
    Handles the 'drink' command for potions.
    """
    def execute(self):
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

        item_data = game_state.GAME_ITEMS.get(item_id)
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