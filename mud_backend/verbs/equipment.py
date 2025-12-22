# mud_backend/verbs/equipment.py
from mud_backend.verbs.base_verb import BaseVerb
from typing import Dict, Any, Tuple, Optional
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.item_utils import (
    find_item_in_inventory, 
    get_item_data, 
    find_item_in_hands, 
    find_item_worn, 
    find_container_on_player
)
from mud_backend.core import db
import uuid

@VerbRegistry.register(["wear", "wield"])
class Wear(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Wear what?")
            return
        target_name = " ".join(self.args).lower()
        
        item_id = None
        source_type = None 
        source_slot = None
        
        hand_item_id, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_name)
        if hand_item_id:
            item_id = hand_item_id
            source_type = "hand"
            source_slot = hand_slot
        else:
            inv_item_id = find_item_in_inventory(self.player, self.world.game_items, target_name)
            if inv_item_id:
                item_id = inv_item_id
                source_type = "inventory"

        if not item_id:
            self.player.send_message(f"You don't have a '{target_name}'.")
            return

        item_data = self.world.game_items.get(item_id)
        if not item_data:
            self.player.send_message("Error with item.")
            return

        target_slot = item_data.get("wearable_slot")
        if not target_slot:
            self.player.send_message(f"You cannot wear {item_data.get('name')}.")
            return
            
        if self.player.worn_items.get(target_slot) is not None:
            self.player.send_message(f"You are already wearing something on your {target_slot}.")
            return
            
        if source_type == "inventory":
            self.player.inventory.remove(item_id)
        elif source_type == "hand":
             self.player.worn_items[source_slot] = None

        self.player.worn_items[target_slot] = item_id
        verb = "wield" if item_data.get("item_type") in ["weapon", "shield"] else "wear"
        self.player.send_message(f"You {verb} {item_data.get('name')}.")
        _set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["remove"])
class Remove(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Remove what?")
            return
        target_name = " ".join(self.args).lower()
        item_id, slot = find_item_worn(self.player, target_name)
        if not item_id:
            self.player.send_message(f"You are not wearing a {target_name}.")
            return
        item_data = self.world.game_items.get(item_id, {})
        
        target_hand_slot = None
        if self.player.worn_items.get("mainhand") is None: target_hand_slot = "mainhand"
        elif self.player.worn_items.get("offhand") is None: target_hand_slot = "offhand"

        if target_hand_slot:
            self.player.worn_items[slot] = None 
            self.player.worn_items[target_hand_slot] = item_id
            verb = "lower" if item_data.get("item_type") in ["weapon", "shield"] else "remove"
            self.player.send_message(f"You {verb} {item_data.get('name')} and hold it.")
        else:
            if item_data.get("wearable_slot") == "back" and item_data.get("is_container"):
                 self.player.send_message("Hands full! Cannot put pack inside itself.")
                 return
            self.player.worn_items[slot] = None 
            self.player.inventory.append(item_id) 
            self.player.send_message(f"You remove {item_data.get('name')} and put it in your pack.")
        _set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["pour"])
class Pour(BaseVerb):
    def execute(self):
        self.player.send_message("Pour is not implemented.")