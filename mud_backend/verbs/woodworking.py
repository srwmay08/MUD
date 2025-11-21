# mud_backend/verbs/woodworking.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.item_actions import _get_item_data, _find_item_in_hands
from mud_backend.core.skill_handler import attempt_skill_learning

# Crafting Recipes
# Input Item ID -> List of potential outputs
# "result_id": item_id of the result
# "difficulty": generic difficulty (affects success/fail)
# "xp": Experience granted
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
    Converts raw wood into weapons or components.
    Requires a small edged weapon (knife/dagger).
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
        
        # 1. Check for Knife (Small Edged)
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

        # 2. Find Wood in hands
        wood_ref, wood_slot = _find_item_in_hands(self.player, wood_target)
        if not wood_ref:
            self.player.send_message(f"You aren't holding '{wood_target}'.")
            return
            
        wood_data = _get_item_data(wood_ref, self.world.game_items)
        # Check if it's a valid wood item (must be in RECIPES)
        # We check by item_id (if static) or some property.
        # For now, assume static item ID is the key in RECIPES.
        # If dynamic, we'd need a 'template_id' or similar.
        
        recipe_key = wood_ref # Assuming static ID for now (e.g., "ash_wood")
        if isinstance(wood_ref, dict):
             recipe_key = wood_ref.get("item_id") or wood_ref.get("template_id")
             
        possible_outputs = RECIPES.get(recipe_key)
        
        if not possible_outputs:
             self.player.send_message("That type of wood cannot be carved into anything useful.")
             return
             
        # 3. Find matching recipe
        target_recipe = None
        for recipe in possible_outputs:
            if result_target == recipe["name"] or result_target in recipe.get("keywords", []):
                target_recipe = recipe
                break
                
        if not target_recipe:
             valid_outputs = ", ".join([r["name"] for r in possible_outputs])
             self.player.send_message(f"You can't carve that into '{result_target}'. Valid options: {valid_outputs}.")
             return

        # 4. Execute Crafting
        self.player.send_message(f"You begin whittling the {wood_data['name']} into a {target_recipe['name']}...")
        
        # XP / Skill Check placeholder (Using forestry or generic DEX?)
        # Let's use 'forestry' as knowledge of wood, and DEX as the stat.
        # Since there isn't a 'woodworking' skill yet.
        
        # Consume the wood
        self.player.worn_items[wood_slot] = None
        
        # Create result
        result_id = target_recipe["result_id"]
        
        # If hands full (knife in one, wood was in other -> now empty), put in empty hand
        if not self.player.worn_items[wood_slot]:
             self.player.worn_items[wood_slot] = result_id
             self.player.send_message(f"You finish carving the {target_recipe['name']} and hold it.")
        else:
             self.player.inventory.append(result_id)
             self.player.send_message(f"You finish carving the {target_recipe['name']} and put it in your pack.")
             
        # Grant XP
        xp = target_recipe["xp"]
        self.player.grant_experience(xp, source="crafting")
        self.player.send_message(f"You gain {xp} experience.")
        
        _set_action_roundtime(self.player, 10.0)