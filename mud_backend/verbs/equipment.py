# mud_backend/verbs/equipment.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: from mud_backend.core import game_state ---
from typing import Dict, Any, Tuple, Optional

def _find_item_in_inventory(player, target_name: str) -> str | None:
    """Finds the first item_id in a player's inventory that matches."""
    for item_id in player.inventory:
        # --- FIX: Use player.world.game_items ---
        item_data = player.world.game_items.get(item_id)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_id
    return None

def _find_item_worn(player, target_name: str) -> tuple[str, str] | tuple[None, None]:
    """Finds the first item_id and slot on a player that matches."""
    for slot, item_id in player.worn_items.items():
        if item_id:
            # --- FIX: Use player.world.game_items ---
            item_data = player.world.game_items.get(item_id)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or 
                    target_name in item_data.get("keywords", [])):
                    return item_id, slot
    return None, None

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

class Wear(BaseVerb):
    """
    Handles the 'wear' and 'wield' commands.
    Moves an item from inventory OR hands to a wearable slot.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Wear what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Find the item (Hands FIRST, then Inventory)
        item_id = None
        source_type = None # "hand" or "inventory"
        source_slot = None # if "hand", which one
        
        # Check hands
        hand_item_id, hand_slot = _find_item_in_hands(self.player, target_name)
        if hand_item_id:
            item_id = hand_item_id
            source_type = "hand"
            source_slot = hand_slot
        else:
            # Check inventory
            inv_item_id = _find_item_in_inventory(self.player, target_name)
            if inv_item_id:
                item_id = inv_item_id
                source_type = "inventory"

        if not item_id:
            self.player.send_message(f"You don't have a '{target_name}'.")
            return

        # --- FIX: Use self.world.game_items ---
        item_data = self.world.game_items.get(item_id)
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
            # --- FIX: Use self.world.game_items ---
            occupied_item = self.world.game_items.get(occupied_id, {})
            self.player.send_message(f"You are already wearing {occupied_item.get('name')} on your {target_slot}.")
            return
            
        # 4. Perform the action (Move from source to target)
        if source_type == "inventory":
            self.player.inventory.remove(item_id)
        elif source_type == "hand":
             self.player.worn_items[source_slot] = None

        self.player.worn_items[target_slot] = item_id
        
        # Use "wield" for weapons, "wear" for everything else
        verb = "wield" if item_data.get("item_type") in ["weapon", "shield"] else "wear"
        self.player.send_message(f"You {verb} {item_data.get('name')}.")

class Remove(BaseVerb):
    """
    Handles the 'remove' command.
    Moves an item from a worn slot to inventory or hands.
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
            
        # --- FIX: Use self.world.game_items ---
        item_data = self.world.game_items.get(item_id, {})
        
        # 2. Find an empty hand
        right_hand_slot = "mainhand"
        left_hand_slot = "offhand"
        target_hand_slot = None
        
        if self.player.worn_items.get(right_hand_slot) is None:
            target_hand_slot = right_hand_slot
        elif self.player.worn_items.get(left_hand_slot) is None:
            target_hand_slot = left_hand_slot

        # 3. Perform the action
        if target_hand_slot:
            # Move to empty hand
            self.player.worn_items[slot] = None # Free up the worn slot
            self.player.worn_items[target_hand_slot] = item_id
            verb = "remove"
            if item_data.get("item_type") in ["weapon", "shield"]:
                verb = "lower"
            self.player.send_message(f"You {verb} {item_data.get('name')} and hold it.")
        else:
            # Hands are full, try moving to pack.
            # CRITICAL FIX: prevent removing a container into itself.
            # If this item IS the main backpack, it cannot go into inventory.
            if item_data.get("wearable_slot") == "back" and item_data.get("is_container"):
                 self.player.send_message("Your hands are full, and you can't put your pack inside itself! Drop something first.")
                 return

            self.player.worn_items[slot] = None # Free up the worn slot
            self.player.inventory.append(item_id) # Add to pack
            verb = "remove"
            if item_data.get("item_type") in ["weapon", "shield"]:
                if slot == "mainhand": verb = "lower"
                if slot == "offhand": verb = "unstrap"
            self.player.send_message(f"You {verb} {item_data.get('name')} and put it in your pack.")