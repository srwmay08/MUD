# mud_backend/verbs/harvesting.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import game_state
from mud_backend.core import loot_system
from typing import Dict, Any
from mud_backend.core import db # <--- NEW IMPORT

def _find_target_corpse(room_objects: list, target_name: str) -> Dict[str, Any] | None:
    """Helper function to find a corpse object by keywords."""
    for obj in room_objects:
        if obj.get("is_corpse") and target_name in obj.get("keywords", []):
            return obj
    return None

def _spill_item_into_room(room_objects: list, item_id: str) -> str | None:
    """
    Creates an item object and adds it to the room's object list.
    Returns the item's name if successful.
    """
    item_data = game_state.GAME_ITEMS.get(item_id)
    if not item_data:
        print(f"[LOOT_SYSTEM] WARNING: Could not find item_id '{item_id}' in GAME_ITEMS.")
        return None
    
    item_name = item_data.get("name", "an unknown item")
    item_keywords = [
        item_name.lower(), 
        item_id.lower()
    ] + item_name.lower().split()

    new_item_obj = {
        "name": item_name,
        "description": item_data.get("description", "It's an item."),
        "keywords": list(set(item_keywords)),
        "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"],
        "is_item": True,
        "item_id": item_id,
        "perception_dc": 0
    }
    
    room_objects.append(new_item_obj)
    return item_name


class Absorb(BaseVerb):
    """
    Handles the 'absorb' command. (Redundant now, but kept for alias list consistency)
    """
    def execute(self):
        exp_in_room = self.room.unabsorbed_social_exp
        
        if exp_in_room <= 0:
            self.player.send_message("There is no experience here to absorb.")
            return

        # Uses the passive absorption function
        # We call it here manually if a player uses the command, even though it's now tick-based
        self.player.absorb_exp_pulse()
        
        # Clear the experience from the room
        self.room.unabsorbed_social_exp = 0
        # --- NEW: Save the room state after modifying it ---
        db.save_room_state(self.room) 


class Search(BaseVerb):
    """
    Handles the 'search' command.
    Searches a corpse for items, spilling them onto the ground.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Search what?")
            return

        target_name = " ".join(self.args).lower()
        
        corpse_obj = _find_target_corpse(self.room.objects, target_name)

        if not corpse_obj:
            self.player.send_message(f"You don't see a **{target_name}** here to search.")
            return

        if corpse_obj.get("searched_and_emptied", False):
            self.player.send_message(f"The {corpse_obj['name']} has already been searched.")
            return

        # Mark as searched immediately
        corpse_obj["searched_and_emptied"] = True
        
        item_ids_to_drop = corpse_obj.get("inventory", [])
        
        if not item_ids_to_drop:
            self.player.send_message(f"You search the {corpse_obj['name']} but find nothing.")
            corpse_obj["description"] = f"The lifeless body of {corpse_obj['original_name']}. It has been picked clean."
            db.save_room_state(self.room) # Save the description change
            return

        self.player.send_message(f"You search the {corpse_obj['name']} and find:")
        
        found_items_names = []
        for item_id in item_ids_to_drop:
            item_name = _spill_item_into_room(self.room.objects, item_id)
            if item_name:
                found_items_names.append(item_name)
        
        # Send a summary of found items
        for name in found_items_names:
            self.player.send_message(f"- {name}")

        # Clear the corpse's inventory and update its description
        corpse_obj["inventory"] = []
        corpse_obj["description"] = f"The lifeless body of {corpse_obj['original_name']}. It has been picked clean."
        
        # --- NEW: Save the room state after modifying it ---
        db.save_room_state(self.room)


class Skin(BaseVerb):
    """
    Handles the 'skin' command.
    Attempts to skin a corpse for pelts or hides.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Skin what?")
            return

        target_name = " ".join(self.args).lower()
        
        corpse_obj = _find_target_corpse(self.room.objects, target_name)

        if not corpse_obj:
            self.player.send_message(f"You don't see a **{target_name}** here to skin.")
            return
            
        if not corpse_obj.get("skinnable", False):
            self.player.send_message(f"You cannot skin the {corpse_obj['name']}.")
            return
            
        if corpse_obj.get("skinned", False):
            self.player.send_message(f"The {corpse_obj['name']} has already been skinned.")
            return

        # Mark as skinned immediately
        corpse_obj["skinned"] = True
        
        # Get the original monster template
        template_key = corpse_obj.get("original_template_key")
        if not template_key:
            self.player.send_message("You try to skin it, but the corpse is unidentifiable.")
            db.save_room_state(self.room) # Save the 'skinned' flag
            return
            
        monster_template = game_state.GAME_MONSTER_TEMPLATES.get(template_key)
        if not monster_template:
            self.player.send_message("You can't seem to find a way to skin this creature.")
            db.save_room_state(self.room) # Save the 'skinned' flag
            return

        # Get player's skinning skill
        player_skill = self.player.skills.get("skinning", 0)
        
        # Call the loot_system function
        item_ids_to_drop = loot_system.generate_skinning_loot(
            monster_template=monster_template,
            player_skill_value=player_skill,
            game_items_data=game_state.GAME_ITEMS
        )
        
        if not item_ids_to_drop:
            self.player.send_message("You try to skin the creature, but fail to produce anything of use.")
            db.save_room_state(self.room) # Save the 'skinned' flag
            return
            
        for item_id in item_ids_to_drop:
            item_name = _spill_item_into_room(self.room.objects, item_id)
            if item_name:
                # Check if it was a failure item
                skinning_info = monster_template.get("skinning", {})
                if item_id == skinning_info.get("item_yield_failed_key"):
                    self.player.send_message(f"You try to skin the {corpse_obj['original_name']} but ruin it, producing {item_name}.")
                else:
                    self.player.send_message(f"You skillfully skin the {corpse_obj['original_name']}, producing {item_name}.")
        
        # --- NEW: Save the room state after modifying it ---
        db.save_room_state(self.room)