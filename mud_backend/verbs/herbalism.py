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

class Harvest(BaseVerb):
    """
    Handles the 'harvest' command.
    Attempts to harvest a plant node.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
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
            
        # 2. Check depletion (Hybrid Model)
        player_name = self.player.name
        if player_name in node_obj.get("players_tapped", []):
            self.player.send_message(f"You have already harvested {node_obj['name']}.")
            return
            
        # 3. Set Roundtime (based on 'survival' skill)
        botany_skill = self.player.skills.get("botany", 0) # <-- Use botany
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
            node_obj.setdefault("players_tapped", []).append(player_name)
            self.world.save_room(self.room)
            return

        # 5. Get Loot
        loot_table_id = node_obj.get("loot_table_id")
        if not loot_table_id:
            self.player.send_message("You harvest the plant, but it yields nothing.")
            return
            
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
        
        # 6. Mark node as "tapped"
        node_obj.setdefault("players_tapped", []).append(player_name)
        
        taps_left = node_obj.get("default_taps", 1) - len(node_obj.get("players_tapped", []))
        if taps_left <= 0:
            self.player.send_message(f"The {node_obj['name']} is now depleted.")
            # (Add respawn logic here)
            
        self.world.save_room(self.room)