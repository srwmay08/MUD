# mud_backend/verbs/fishing.py
import random
import time
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import loot_system
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend import config
from typing import Dict, Any

@VerbRegistry.register(["fish"])

def _has_tool(player, required_tool_type: str) -> bool:
    """Checks if the player is wielding a tool of the required type."""
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            item_data = player.world.game_items.get(item_id)
            if item_data and item_data.get("tool_type") == required_tool_type:
                return True
    return False

class Fish(BaseVerb):
    """
    Handles the 'fish' command.
    Attempts to catch fish from a valid water source.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

        # 1. Check for required tool
        if not _has_tool(self.player, "fishing"):
            self.player.send_message("You need to be wielding a fishing pole to fish.")
            return

        # 2. Check if this is a valid fishing spot
        # --- FIX: Use self.room.data ---
        if not self.room.data.get("is_fishing_spot", False):
            self.player.send_message("You can't fish here.")
            return
            
        if self.args:
            self.player.send_message("You just need to type 'FISH'.")
            return

        # 3. Set Roundtime (based on Fishing skill)
        fishing_skill = self.player.skills.get("fishing", 0)
        base_rt = 15.0 # Fishing takes time
        rt_reduction = fishing_skill / 10.0 # 1s off per 10 ranks
        rt = max(5.0, base_rt - rt_reduction) # 5s minimum
        
        _set_action_roundtime(self.player, rt, "You cast your line and wait...", rt_type="hard")

        # 4. Roll for Success
        attempt_skill_learning(self.player, "fishing")
        
        # Roll: Skill + d100 vs Room DC
        # --- FIX: Use self.room.data ---
        skill_dc = self.room.data.get("fishing_dc", 50)
        roll = fishing_skill + random.randint(1, 100)
        
        if roll < skill_dc:
            self.player.send_message("...but you don't get any bites.")
            return

        # 5. Get Loot
        # --- FIX: Use self.room.data ---
        loot_table_id = self.room.data.get("fishing_loot_table_id")
        if not loot_table_id:
            self.player.send_message("...but nothing seems to be biting.")
            return
            
        item_ids_to_give = loot_system.generate_loot_from_table(
            loot_table_id,
            self.world.game_loot_tables,
            self.world.game_items
        )

        if not item_ids_to_give:
            self.player.send_message("You reel in your line, but it's empty.")
        else:
            self.player.send_message("You get a bite! You reel in your line and find:")
            for item_id in item_ids_to_give:
                item_data = self.world.game_items.get(item_id, {})
                item_name = item_data.get("name", "an item")
                self.player.inventory.append(item_id)
                self.player.send_message(f"- {item_name}")

        # Note: No node to update, as this is a zone-based skill.