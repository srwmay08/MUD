# mud_backend/verbs/equipment.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import game_state
# --- THIS IS THE FIX ---
from typing import Dict, Any, Tuple
# --- END FIX ---

def _find_item_in_inventory(player, target_name: str) -> str | None:
    """Finds the first item_id in a player's inventory that matches."""
    for item_id in player.inventory:
        item_data = game_state.GAME_ITEMS.get(item_id)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_id
    return None

# --- THIS IS THE FIX ---
# Changed the return type hint from (str, str) | (None, None)
# to the valid syntax: tuple[str, str] | tuple[None, None]
def _find_item_worn(player, target_name: str) -> tuple[str, str] | tuple[None, None]:
# --- END FIX ---
    """Finds the first item_id and slot on a player that matches."""
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = game_state.GAME_ITEMS.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_id, slot
    return None, None

class Wear(BaseVerb):
    """
    Handles the 'wear' and 'wield' commands.
    Moves an item from inventory to a free wearable slot.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Wear what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Find the item in the player's *inventory*
        item_id = _find_item_in_inventory(self.player, target_name)
        
        if not item_id:
            # Check if they are already holding it
            for slot in ["mainhand", "offhand"]:
                 held_id = self.player.worn_items.get(slot)
                 if held_id:
                    held_data = game_state.GAME_ITEMS.get(held_id)
                    if (held_data and (target_name == held_data.get("name", "").lower() or 
                                       target_name in held_data.get("keywords", []))):
                        self.player.send_message("You are already holding that.")
                        return
            
            self.player.send_message(f"You don't have a {target_name} in your pack.")
            return

        item_data = game_state.GAME_ITEMS.get(item_id)
        if not item_data:
            self.player.send_message("An error occurred with that item.")
            return

        # 2. Check if the item is wearable
        target_slot = item_data.get("wearable_slot")
        if not target_slot:
            self.player.send_message(f"You cannot wear {item_data.get('name')}.")
            return
            
        # 3. Check if the target slot is free
        if self.player.worn_items.get(target_slot) is not None:
            occupied_id = self.player.worn_items.get(target_slot)
            occupied_item = game_state.GAME_ITEMS.get(occupied_id, {})
            self.player.send_message(f"You are already wearing {occupied_item.get('name')} on your {target_slot}.")
            return
            
        # 4. Perform the action
        self.player.inventory.remove(item_id)
        self.player.worn_items[target_slot] = item_id
        
        # Use "wield" for weapons, "wear" for everything else
        verb = "wield" if item_data.get("item_type") in ["weapon", "shield"] else "wear"
        self.player.send_message(f"You {verb} {item_data.get('name')}.")

class Remove(BaseVerb):
    """
    Handles the 'remove' command.
    Moves an item from a worn slot to inventory.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Remove what?")
            return

        target_name = " ".join(self.args).lower()

        # 1. Find the item on the player's *body*
        item_id, slot = _find_item_worn(self.player, target_name)
        
        if not item_id:
            self.player.send_message(f"You are not wearing a {target_name}.")
            return
            
        item_data = game_state.GAME_ITEMS.get(item_id, {})
        
        # 2. Perform the action
        self.player.worn_items[slot] = None # Free up the slot
        self.player.inventory.append(item_id) # Add to pack
        
        verb = "remove"
        if item_data.get("item_type") in ["weapon", "shield"]:
            if slot == "mainhand": verb = "lower"
            if slot == "offhand": verb = "unstrap"
            
        self.player.send_message(f"You {verb} {item_data.get('name')} and put it in your pack.")