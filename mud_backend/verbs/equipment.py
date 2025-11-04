# mud_backend/verbs/equipment.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import game_state

class Wear(BaseVerb):
    """
    Handles the 'wear' command.
    Moves an item from inventory to a worn_items slot.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Wear what?")
            return
            
        target_name = " ".join(self.args).lower()
        
        # 1. Find the item in the player's inventory (pack)
        item_id_to_wear = None
        for item_id in self.player.inventory:
            item_data = game_state.GAME_ITEMS.get(item_id)
            if item_data and target_name in item_data['name'].lower():
                item_id_to_wear = item_id
                break
        
        if not item_id_to_wear:
            self.player.send_message(f"You don't seem to have a '{target_name}' to wear.")
            return
            
        item_data = game_state.GAME_ITEMS.get(item_id_to_wear)
        
        # 2. Check if the item is wearable
        target_slot = item_data.get("wearable_slot")
        if not target_slot:
            self.player.send_message(f"You can't figure out how to wear {item_data['name']}.")
            return
            
        # 3. Check if the slot is free
        if self.player.worn_items.get(target_slot) is not None:
            # Slot is full. We'd need to handle auto-swapping later.
            self.player.send_message(f"You are already wearing something in that spot.")
            return
            
        # 4. Wear the item
        self.player.inventory.remove(item_id_to_wear)
        self.player.worn_items[target_slot] = item_id_to_wear
        
        # Simple messaging for now
        self.player.send_message(f"You wear {item_data['name']}.")


class Remove(BaseVerb):
    """
    Handles the 'remove' command.
    Moves an item from a worn_items slot to inventory.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Remove what?")
            return
            
        target_name = " ".join(self.args).lower()
        
        # 1. Find the item in the player's *worn* items
        item_id_to_remove = None
        slot_found = None
        
        for slot, item_id in self.player.worn_items.items():
            if item_id:
                item_data = game_state.GAME_ITEMS.get(item_id)
                if item_data and target_name in item_data['name'].lower():
                    item_id_to_remove = item_id
                    slot_found = slot
                    break
                    
        if not item_id_to_remove:
            self.player.send_message(f"You are not wearing a '{target_name}'.")
            return
            
        item_data = game_state.GAME_ITEMS.get(item_id_to_remove)
        
        # 2. Remove the item
        self.player.worn_items[slot_found] = None
        self.player.inventory.append(item_id_to_remove)
        
        self.player.send_message(f"You remove {item_data['name']}.")