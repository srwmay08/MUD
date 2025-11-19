import random
import time
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import loot_system
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime # We can re-use these
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend import config
from typing import Dict, Any

# This helper is copied from the new mining.py
def _find_target_node(room_objects: list, target_name: str, node_type: str) -> Dict[str, Any] | None:
    """Helper to find a gathering node by name and type."""
    for obj in room_objects:
        if (obj.get("is_gathering_node") and 
            obj.get("node_type") == node_type):
            
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                return obj
    return None

def _has_tool(player, required_tool_type: str) -> bool:
    """Checks if the player is wielding a tool of the required type."""
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            item_data = player.world.game_items.get(item_id)
            if item_data and item_data.get("tool_type") == required_tool_type:
                return True
    return False

class Harvest(BaseVerb):
    """
    Handles the 'harvest' command.
    Attempts to harvest a plant node.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

        # --- Tool Check ---
        if not _has_tool(self.player, "herbalism"):
            # Allow "starter_dagger" as a fallback if it counts as small_edged? 
            # The config check in `_has_tool` needs logic, but for now sticking to simple check:
            if not _has_tool(self.player, "small_edged"): # Check for any small edged weapon
                 self.player.send_message("You need to be wielding a sickle or knife to harvest plants.")
                 return

        if not self.args:
            self.player.send_message("Harvest what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Find the node
        node_obj = _find_target_node(self.room.objects, target_name, "herbalism")

        if not node_obj:
            self.player.send_message(f"You don't see a {target_name} here to harvest.")
            return
            
        # 2. Check depletion
        player_name = self.player.name
        
        # Get/initialize the player-specific hit data for this node instance
        player_hit_data = node_obj.setdefault("player_hits", {})
        if player_name not in player_hit_data:
            player_hit_data[player_name] = {
                "max_hits": random.randint(1, 5), # Roll 1-5 attempts for this player
                "hits_made": 0
            }
        
        my_data = player_hit_data[player_name]

        # 2a. Check if PLAYER has attempts left
        if my_data["hits_made"] >= my_data["max_hits"]:
            self.player.send_message(f"You have already harvested {node_obj['name']}.")
            return
            
        # 2b. Check if NODE has global taps left
        global_hits_made = node_obj.get("global_hits_made", 0)
        global_max_taps = node_obj.get("default_taps", 1)
        
        if global_hits_made >= global_max_taps:
            self.player.send_message(f"The {node_obj['name']} is depleted.")
            if node_obj in self.room.objects:
                self.room.objects.remove(node_obj)
                self.world.save_room(self.room)
            return
            
        # 3. Set Roundtime (based on 'botany' skill)
        botany_skill = self.player.skills.get("botany", 0) 
        base_rt = 5.0 # Faster than mining
        rt_reduction = botany_skill / 20.0 
        rt = max(1.5, base_rt - rt_reduction)
        
        _set_action_roundtime(self.player, rt, f"You begin harvesting {node_obj['name']}...", rt_type="hard")

        # 4. Roll for Success
        skill_dc = node_obj.get("skill_dc", 10)
        attempt_skill_learning(self.player, "herbalism") # <-- LBD on primary skill
        roll = botany_skill + random.randint(1, 100) # <-- Roll on secondary skill
        
        if roll < skill_dc:
            self.player.send_message(f"You try to harvest {node_obj['name']} but fail to get anything.")
            
            # Mark this attempt as used
            my_data["hits_made"] += 1
            node_obj["global_hits_made"] = node_obj.get("global_hits_made", 0) + 1
            
            # Check for node depletion
            if node_obj["global_hits_made"] >= node_obj.get("default_taps", 1):
                self.player.send_message(f"The {node_obj['name']} is now depleted.")
                if node_obj in self.room.objects:
                    self.room.objects.remove(node_obj)
            
            self.world.save_room(self.room)
            return

        # 5. Get Loot
        loot_table_id = node_obj.get("loot_table_id")
        if not loot_table_id:
            self.player.send_message("You harvest the plant, but it yields nothing.")
            # Even if empty, consume tap
        else:
            item_ids_to_give = loot_system.generate_loot_from_table(
                loot_table_id,
                self.world.game_loot_tables,
                self.world.game_items
            )

            if not item_ids_to_give:
                self.player.send_message("You harvest the plant, but it yields nothing.")
            else:
                self.player.send_message(f"You harvest {node_obj['name']} and receive:")
                for item_id in item_ids_to_give:
                    item_data = self.world.game_items.get(item_id, {})
                    item_name = item_data.get("name", "an item")
                    self.player.inventory.append(item_id)
                    self.player.send_message(f"- {item_name}")
        
        # ---
        # --- NEW: XP Calculation (1/10th Monster Rate + Band Sharing)
        # ---
        player_level = self.player.level
        node_level = node_obj.get("level", 1)
        level_diff = player_level - node_level 
        
        nominal_xp = 0
        if level_diff >= 10:
            nominal_xp = 0
        elif 1 <= level_diff <= 9:
            # Monster: 100 - (10 * diff)  -> Node: 10 - (1 * diff)
            nominal_xp = 10 - (1 * level_diff)
        elif level_diff == 0:
            # Monster: 100 -> Node: 10
            nominal_xp = 10
        elif -4 <= level_diff <= -1:
            # Monster: 100 + (10 * abs(diff)) -> Node: 10 + (1 * abs(diff))
            nominal_xp = 10 + (1 * abs(level_diff))
        elif level_diff <= -5:
            # Monster: 150 -> Node: 15
            nominal_xp = 15
        
        nominal_xp = max(0, nominal_xp)
        
        if nominal_xp > 0:
            self.player.send_message(f"You have gained {nominal_xp} experience from harvesting.")
            self.player.grant_experience(nominal_xp, source="herbalism")
        # ---
        # --- END NEW XP LOGIC
        # ---
        
        # 6. Mark hit as used for this player
        my_data["hits_made"] += 1
        
        # 7. Mark global hit as used
        global_hits_made = node_obj.get("global_hits_made", 0) + 1
        node_obj["global_hits_made"] = global_hits_made
        global_max_taps = node_obj.get("default_taps", 1)

        # 8. Deplete the node if global taps run out
        if global_hits_made >= global_max_taps:
            self.player.send_message(f"The {node_obj['name']} is now depleted.")
            if node_obj in self.room.objects:
                self.room.objects.remove(node_obj)
            
        self.world.save_room(self.room)