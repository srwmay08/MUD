# mud_backend/verbs/harvesting.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import loot_system
from typing import Dict, Any
from mud_backend.core import db 
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
import time
import math
from mud_backend import config

@VerbRegistry.register(["search"]) 
@VerbRegistry.register(["skin", "butcher"])

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

def _spill_item_into_room(world: 'World', room_objects: list, item_data_or_id) -> str | None:
    """
    Creates an item object and adds it to the room's object list.
    Handles both ID string (static loot) and Dict (dynamic loot).
    """
    item_data = None
    
    if isinstance(item_data_or_id, str):
        item_data = world.game_items.get(item_data_or_id)
        if not item_data:
            print(f"[LOOT_SYSTEM] WARNING: Could not find item_id '{item_data_or_id}' in GAME_ITEMS.")
            return None
        
        # Create instance from template
        item_name = item_data.get("name", "an unknown item")
        item_keywords = [item_name.lower(), item_data_or_id.lower()] + item_name.lower().split()

        new_item_obj = {
            "name": item_name,
            "description": item_data.get("description", "It's an item."),
            "keywords": list(set(item_keywords)),
            "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"],
            "is_item": True,
            "item_id": item_data_or_id,
            "perception_dc": 0
        }
        room_objects.append(new_item_obj)
        return item_name
        
    elif isinstance(item_data_or_id, dict):
        # It's already an instance (dynamic loot)
        item_obj = item_data_or_id
        room_objects.append(item_obj)
        return item_obj.get("name", "an item")

    return None


class Search(BaseVerb):
    """
    Handles the 'search' command.
    Searches a corpse for items (generating dynamic loot if needed), 
    spilling them onto the ground, and removes the corpse.
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return

        if not self.args:
            self.player.send_message("Search what?")
            return

        target_name = " ".join(self.args).lower()
        
        corpse_obj = _find_target_corpse(self.room.objects, target_name)

        if not corpse_obj:
            self.player.send_message(f"You don't see a **{target_name}** here to search.")
            return

        set_action_roundtime(self.player, 5.0, rt_type="hard") 

        if corpse_obj.get("searched_and_emptied", False):
            self.player.send_message(f"You search the {corpse_obj['name']} but find nothing left.")
            if corpse_obj in self.room.objects:
                self.room.objects.remove(corpse_obj)
            self.world.save_room(self.room)
            return

        # --- NEW: Dynamic Loot Generation ---
        if not corpse_obj.get("dynamic_loot_generated", False):
             original_template = corpse_obj.get("original_template")
             if original_template:
                 # Generate Dynamic Loot based on Treasure System
                 dynamic_loot = self.world.treasure_manager.generate_dynamic_loot(original_template)
                 if dynamic_loot:
                     if "items" not in corpse_obj: corpse_obj["items"] = []
                     corpse_obj["items"].extend(dynamic_loot)
                 
                 # Mark as generated
                 corpse_obj["dynamic_loot_generated"] = True
        # ------------------------------------

        corpse_obj["searched_and_emptied"] = True
        
        items_to_drop = corpse_obj.get("items", [])
        
        if not items_to_drop:
            self.player.send_message(f"You search the {corpse_obj['name']} but find nothing.")
            
            if corpse_obj in self.room.objects:
                self.room.objects.remove(corpse_obj)
            self.world.save_room(self.room) 
            return

        self.player.send_message(f"You search the {corpse_obj['name']} and find:")
        
        found_items_names = []
        for item_data in items_to_drop:
            item_name = _spill_item_into_room(self.world, self.room.objects, item_data)
            if item_name:
                found_items_names.append(item_name)
        
        for name in found_items_names:
            self.player.send_message(f"- {name}")

        corpse_obj["items"] = [] # Empty it
        if corpse_obj in self.room.objects:
            self.room.objects.remove(corpse_obj)
        
        self.world.save_room(self.room)


class Skin(BaseVerb):
    """
    Handles the 'skin' command.
    Attempts to skin a corpse for pelts or hides.
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
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

        survival_skill = self.player.skills.get("survival", 0)
        base_rt = getattr(config, 'SKINNING_BASE_RT', 15.0) 
        rt_reduction = survival_skill / 10.0
        rt = max(3.0, base_rt - rt_reduction)
        
        set_action_roundtime(self.player, rt, rt_type="hard")

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