# mud_backend/verbs/harvesting.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import loot_system
from typing import Dict, Any
from mud_backend.core import db 
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
# --- NEW: Import math and config ---
import time
import math
from mud_backend import config
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
            
        if (target_name == obj.get("name", "").lower() or 
            target_name in obj.get("keywords", [])):
            
            if obj.get("searched_and_emptied", False):
                searched_matches.append(obj)
            else:
                unsearched_matches.append(obj)

    if unsearched_matches:
        return unsearched_matches[0]
    
    if searched_matches:
        return searched_matches[0]

    return None

def _spill_item_into_room(world: 'World', room_objects: list, item_id: str) -> str | None:
    """
    Creates an item object and adds it to the room's object list.
    Returns the item's name if successful.
    """
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
        if _check_action_roundtime(self.player, action_type="other"):
            return

        exp_in_room = self.room.unabsorbed_social_exp
        
        if exp_in_room <= 0:
            self.player.send_message("There is no experience here to absorb.")
            return

        self.player.absorb_exp_pulse()
        
        self.room.unabsorbed_social_exp = 0
        self.world.save_room(self.room)
        
        _set_action_roundtime(self.player, 1.0, rt_type="hard")


class Search(BaseVerb):
    """
    Handles the 'search' command.
    Searches a corpse for items, spilling them onto the ground, and removes the corpse.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

        if not self.args:
            self.player.send_message("Search what?")
            return

        target_name = " ".join(self.args).lower()
        
        corpse_obj = _find_target_corpse(self.room.objects, target_name)

        if not corpse_obj:
            self.player.send_message(f"You don't see a **{target_name}** here to search.")
            return

        # Note: We do NOT change this RT per user request.
        # This is the "search" action, not the "looting" action.
        _set_action_roundtime(self.player, 5.0, rt_type="hard") 

        if corpse_obj.get("searched_and_emptied", False):
            self.player.send_message(f"You search the {corpse_obj['name']} but find nothing left.")
            if corpse_obj in self.room.objects:
                self.room.objects.remove(corpse_obj)
            self.world.save_room(self.room)
            return

        corpse_obj["searched_and_emptied"] = True
        
        item_ids_to_drop = corpse_obj.get("inventory", [])
        
        if not item_ids_to_drop:
            self.player.send_message(f"You search the {corpse_obj['name']} but find nothing.")
            
            if corpse_obj in self.room.objects:
                self.room.objects.remove(corpse_obj)
            self.world.save_room(self.room) 
            return

        self.player.send_message(f"You search the {corpse_obj['name']} and find:")
        
        found_items_names = []
        for item_id in item_ids_to_drop:
            item_name = _spill_item_into_room(self.world, self.room.objects, item_id)
            if item_name:
                found_items_names.append(item_name)
        
        for name in found_items_names:
            self.player.send_message(f"- {name}")

        corpse_obj["inventory"] = []
        if corpse_obj in self.room.objects:
            self.room.objects.remove(corpse_obj)
        
        self.world.save_room(self.room)


class Skin(BaseVerb):
    """
    Handles the 'skin' command.
    Attempts to skin a corpse for pelts or hides.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

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

        # ---
        # --- MODIFIED: Variable RT for Skinning
        # ---
        # Using 'survival' skill as the basis for skinning
        survival_skill = self.player.skills.get("survival", 0)
        # --- THIS IS THE FIX: Read base RT from config ---
        base_rt = getattr(config, 'SKINNING_BASE_RT', 15.0) # Skinning is a complex task
        # --- END FIX ---
        rt_reduction = survival_skill / 10.0 # 1s off per 10 ranks
        rt = max(3.0, base_rt - rt_reduction) # 3s minimum RT
        
        _set_action_roundtime(self.player, rt, rt_type="hard")
        # --- END MODIFIED ---

        corpse_obj["skinned"] = True
        
        template_key = corpse_obj.get("original_template_key")
        if not template_key:
            self.player.send_message("You try to skin it, but the corpse is unidentifiable.")
            self.world.save_room(self.room)
            return
            
        monster_template = self.world.game_monster_templates.get(template_key)
        if not monster_template:
            self.player.send_message("You can't seem to find a way to skin this creature.")
            self.world.save_room(self.room)
            return

        # Using 'survival' skill for the roll
        player_skill = self.player.skills.get("survival", 0)
        
        item_ids_to_drop = loot_system.generate_skinning_loot(
            monster_template=monster_template,
            player_skill_value=player_skill,
            game_items_data=self.world.game_items
        )
        
        if not item_ids_to_drop:
            self.player.send_message("You try to skin the creature, but fail to produce anything of use.")
            self.world.save_room(self.room)
            return
            
        for item_id in item_ids_to_drop:
            item_name = _spill_item_into_room(self.world, self.room.objects, item_id)
            if item_name:
                skinning_info = monster_template.get("skinning", {})
                if item_id == skinning_info.get("item_yield_failed_key"):
                    self.player.send_message(f"You try to skin the {corpse_obj['original_name']} but ruin it, producing {item_name}.")
                else:
                    self.player.send_message(f"You skillfully skin the {corpse_obj['original_name']}, producing {item_name}.")
        
        self.world.save_room(self.room)