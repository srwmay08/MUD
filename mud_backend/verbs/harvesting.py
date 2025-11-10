# mud_backend/verbs/harvesting.py
from mud_backend.verbs.base_verb import BaseVerb
# --- REMOVED: from mud_backend.core import game_state ---
from mud_backend.core import loot_system
from typing import Dict, Any
from mud_backend.core import db 
# --- NEW: Import RT helpers ---
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time
# --- END NEW ---

def _find_target_corpse(room_objects: list, target_name: str) -> Dict[str, Any] | None:
    """
    Helper function to find a corpse object by name or keywords.
    It prioritizes finding an un-searched corpse.
    """
    
    unsearched_matches = []
    searched_matches = []
    
    for obj in room_objects:
        if not obj.get("is_corpse"):
            continue
            
        # Check if the target name matches the object's name OR is in its keywords
        if (target_name == obj.get("name", "").lower() or 
            target_name in obj.get("keywords", [])):
            
            if obj.get("searched_and_emptied", False):
                searched_matches.append(obj)
            else:
                unsearched_matches.append(obj)

    # Prioritize the unsearched list first
    if unsearched_matches:
        return unsearched_matches[0]
    
    # If no unsearched ones, return the first searched one (if any)
    if searched_matches:
        return searched_matches[0]

    return None # No matches at all

# --- REFACTORED: Accept world object ---
def _spill_item_into_room(world: 'World', room_objects: list, item_id: str) -> str | None:
    """
    Creates an item object and adds it to the room's object list.
    Returns the item's name if successful.
    """
    # --- FIX: Use world.game_items ---
    item_data = world.game_items.get(item_id)
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
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player):
            return
        # --- END NEW ---

        exp_in_room = self.room.unabsorbed_social_exp
        
        if exp_in_room <= 0:
            self.player.send_message("There is no experience here to absorb.")
            return

        # Uses the passive absorption function
        # We call it here manually if a player uses the command, even though it's now tick-based
        self.player.absorb_exp_pulse()
        
        # Clear the experience from the room
        self.room.unabsorbed_social_exp = 0
        # --- FIX: Use self.world.save_room ---
        self.world.save_room(self.room)
        
        # --- NEW: Set RT ---
        # This is a fast social action
        _set_action_roundtime(self.player, 1.0)
        # --- END NEW ---


class Search(BaseVerb):
    """
    Handles the 'search' command.
    Searches a corpse for items, spilling them onto the ground, and removes the corpse.
    """
    def execute(self):
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player):
            return
        # --- END NEW ---

        if not self.args:
            self.player.send_message("Search what?")
            return

        target_name = " ".join(self.args).lower()
        
        corpse_obj = _find_target_corpse(self.room.objects, target_name)

        if not corpse_obj:
            self.player.send_message(f"You don't see a **{target_name}** here to search.")
            return

        # --- NEW: Set RT for the action ---
        _set_action_roundtime(self.player, 5.0) # 5s RT for searching
        # --- END NEW ---

        if corpse_obj.get("searched_and_emptied", False):
            self.player.send_message(f"You search the {corpse_obj['name']} but find nothing left.")
            # --- THIS IS THE FIX ---
            # Remove the already-searched corpse
            if corpse_obj in self.room.objects:
                self.room.objects.remove(corpse_obj)
            self.world.save_room(self.room)
            # --- END FIX ---
            return

        # Mark as searched immediately (so it can't be searched again)
        corpse_obj["searched_and_emptied"] = True
        
        item_ids_to_drop = corpse_obj.get("inventory", [])
        
        if not item_ids_to_drop:
            self.player.send_message(f"You search the {corpse_obj['name']} but find nothing.")
            
            # --- THIS IS THE FIX ---
            # Remove the empty corpse from the room
            if corpse_obj in self.room.objects:
                self.room.objects.remove(corpse_obj)
            # --- FIX: Use self.world.save_room ---
            self.world.save_room(self.room) # Save the room state
            # --- END FIX ---
            return

        self.player.send_message(f"You search the {corpse_obj['name']} and find:")
        
        found_items_names = []
        for item_id in item_ids_to_drop:
            # --- FIX: Pass self.world ---
            item_name = _spill_item_into_room(self.world, self.room.objects, item_id)
            if item_name:
                found_items_names.append(item_name)
        
        # Send a summary of found items
        for name in found_items_names:
            self.player.send_message(f"- {name}")

        # --- THIS IS THE FIX ---
        # Clear the corpse's inventory (redundant, but good practice)
        corpse_obj["inventory"] = []
        # Remove the searched corpse from the room
        if corpse_obj in self.room.objects:
            self.room.objects.remove(corpse_obj)
        
        # Save the room state *after* spilling items and removing corpse
        # --- FIX: Use self.world.save_room ---
        self.world.save_room(self.room)
        # --- END FIX ---


class Skin(BaseVerb):
    """
    Handles the 'skin' command.
    Attempts to skin a corpse for pelts or hides.
    """
    def execute(self):
        # --- NEW: RT Check ---
        if _check_action_roundtime(self.player):
            return
        # --- END NEW ---

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

        # --- NEW: Set RT for the action ---
        _set_action_roundtime(self.player, 8.0) # 8s RT for skinning
        # --- END NEW ---

        # Mark as skinned immediately
        corpse_obj["skinned"] = True
        
        # Get the original monster template
        template_key = corpse_obj.get("original_template_key")
        if not template_key:
            self.player.send_message("You try to skin it, but the corpse is unidentifiable.")
            # --- FIX: Use self.world.save_room ---
            self.world.save_room(self.room) # Save the 'skinned' flag
            return
            
        # --- FIX: Use self.world.game_monster_templates ---
        monster_template = self.world.game_monster_templates.get(template_key)
        if not monster_template:
            self.player.send_message("You can't seem to find a way to skin this creature.")
            # --- FIX: Use self.world.save_room ---
            self.world.save_room(self.room) # Save the 'skinned' flag
            return

        # Get player's skinning skill
        # --- FIX: 'skinning' is not a skill, 'survival' might be used?
        # Let's assume 'survival' is the skill for skinning for now.
        # If 'skinning' is a real skill, this is correct.
        # Re-checking skills.json... there is no 'skinning' skill.
        # I will use 'survival'
        player_skill = self.player.skills.get("survival", 0)
        
        # Call the loot_system function
        # --- FIX: Pass self.world.game_items ---
        item_ids_to_drop = loot_system.generate_skinning_loot(
            monster_template=monster_template,
            player_skill_value=player_skill,
            game_items_data=self.world.game_items
        )
        
        if not item_ids_to_drop:
            self.player.send_message("You try to skin the creature, but fail to produce anything of use.")
            # --- FIX: Use self.world.save_room ---
            self.world.save_room(self.room) # Save the 'skinned' flag
            return
            
        for item_id in item_ids_to_drop:
            # --- FIX: Pass self.world ---
            item_name = _spill_item_into_room(self.world, self.room.objects, item_id)
            if item_name:
                # Check if it was a failure item
                skinning_info = monster_template.get("skinning", {})
                if item_id == skinning_info.get("item_yield_failed_key"):
                    self.player.send_message(f"You try to skin the {corpse_obj['original_name']} but ruin it, producing {item_name}.")
                else:
                    self.player.send_message(f"You skillfully skin the {corpse_obj['original_name']}, producing {item_name}.")
        
        # Save the room state after spilling items
        # --- FIX: Use self.world.save_room ---
        self.world.save_room(self.room)