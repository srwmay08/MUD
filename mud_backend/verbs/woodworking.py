# mud_backend/verbs/woodworking.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.item_actions import _get_item_data, _find_item_in_hands
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend.core.registry import VerbRegistry # <-- Added

RECIPES = {
    "ash_wood": [
        {"result_id": "wooden_club", "name": "club", "difficulty": 10, "xp": 15},
        {"result_id": "spear_shaft", "name": "shaft", "difficulty": 20, "xp": 20}
    ]
}

@VerbRegistry.register(["carve"]) 
class Carve(BaseVerb):
    """
    CARVE <wood> INTO <item>
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        
        if len(self.args) < 3 or " into " not in " ".join(self.args).lower():
            self.player.send_message("Usage: CARVE <wood item> INTO <result> (e.g., CARVE LOG INTO CLUB)")
            return
            
        args_str = " ".join(self.args).lower()
        parts = args_str.split(" into ")
        wood_target = parts[0].strip()
        result_target = parts[1].strip()
        
        has_knife = False
        knife_ref = None
        for slot in ["mainhand", "offhand"]:
            item_ref = self.player.worn_items.get(slot)
            if item_ref:
                data = _get_item_data(item_ref, self.world.game_items)
                if data.get("skill") == "small_edged" or data.get("tool_type") == "knife":
                    has_knife = True
                    knife_ref = item_ref
                    break
                    
        if not has_knife:
            self.player.send_message("You need a knife or dagger to carve wood.")
            return

        # --- FIX: Pass world.game_items to _find_item_in_hands ---
        wood_ref, wood_slot = _find_item_in_hands(self.player, self.world.game_items, wood_target)
        # ---------------------------------------------------------
        
        if not wood_ref:
            self.player.send_message(f"You aren't holding '{wood_target}'.")
            return
            
        wood_data = _get_item_data(wood_ref, self.world.game_items)
        
        recipe_key = wood_ref 
        if isinstance(wood_ref, dict):
             recipe_key = wood_ref.get("item_id") or wood_ref.get("template_id")
             
        possible_outputs = RECIPES.get(recipe_key)
        
        if not possible_outputs:
             self.player.send_message("That type of wood cannot be carved into anything useful.")
             return
             
        target_recipe = None
        for recipe in possible_outputs:
            if result_target == recipe["name"] or result_target in recipe.get("keywords", []):
                target_recipe = recipe
                break
                
        if not target_recipe:
             valid_outputs = ", ".join([r["name"] for r in possible_outputs])
             self.player.send_message(f"You can't carve that into '{result_target}'. Valid options: {valid_outputs}.")
             return

        self.player.send_message(f"You begin whittling the {wood_data['name']} into a {target_recipe['name']}...")
        
        self.player.worn_items[wood_slot] = None
        
        result_id = target_recipe["result_id"]
        
        if not self.player.worn_items[wood_slot]:
             self.player.worn_items[wood_slot] = result_id
             self.player.send_message(f"You finish carving the {target_recipe['name']} and hold it.")
        else:
             self.player.inventory.append(result_id)
             self.player.send_message(f"You finish carving the {target_recipe['name']} and put it in your pack.")
             
        xp = target_recipe["xp"]
        self.player.grant_experience(xp, source="crafting")
        self.player.send_message(f"You gain {xp} experience.")
        
        _set_action_roundtime(self.player, 10.0)