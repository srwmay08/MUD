import random
import time
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import loot_system
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend import config
from typing import Dict, Any

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

class Chop(BaseVerb):
    """
    Handles the 'chop' command.
    Attempts to chop a tree or wood node.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

        # 1. Check for required tool
        if not _has_tool(self.player, "lumberjacking"):
            self.player.send_message("You need to be wielding an axe to chop wood.")
            return

        if not self.args:
            self.player.send_message("Chop what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 2. Find the node
        node_obj = _find_target_node(self.room.objects, target_name, "lumberjacking") 

        if not node_obj:
            self.player.send_message(f"You don't see a {target_name} here to chop.")
            return
            
        # 3. Check depletion (Hybrid Model)
        player_name = self.player.name
        if player_name in node_obj.get("players_tapped", []):
            self.player.send_message(f"You have already chopped {node_obj['name']}.")
            return
            
        # ... (inside Chop.execute) ...

        # 4. Set Roundtime (based on Forestry skill, not Lumberjacking)
        forestry_skill = self.player.skills.get("forestry", 0) # <-- USE SECONDARY SKILL
        base_rt = 8.0 
        rt_reduction = forestry_skill / 20.0 # 1s off per 20 ranks
        rt = max(2.0, base_rt - rt_reduction) 

        _set_action_roundtime(self.player, rt, f"You begin chopping {node_obj['name']}...", rt_type="hard")

        # 5. Roll for Success (Skill vs. DC)
        skill_dc = node_obj.get("skill_dc", 20)

        # The LBD attempt still goes to the *primary* skill
        attempt_skill_learning(self.player, "lumberjacking") 

        # But the success roll uses the *secondary* skill       
        roll = forestry_skill + random.randint(1, 100) # <-- USE SECONDARY SKILL

        if roll < skill_dc:
            self.player.send_message(f"You try to chop {node_obj['name']} but fail to get any wood.")
            node_obj.setdefault("players_tapped", []).append(player_name)
            self.world.save_room(self.room)
            return
        
    
        # 6. Get Loot
        loot_table_id = node_obj.get("loot_table_id")
        if not loot_table_id:
            self.player.send_message("You chop the tree, but it seems to be empty.") 
            return
            
        item_ids_to_give = loot_system.generate_loot_from_table(
            loot_table_id,
            self.world.game_loot_tables,
            self.world.game_items
        )

        if not item_ids_to_give:
            self.player.send_message("You chop the tree, but it yields nothing.") 
        else:
            self.player.send_message(f"You chop {node_obj['name']} and receive:") 
            for item_id in item_ids_to_give:
                item_data = self.world.game_items.get(item_id, {})
                item_name = item_data.get("name", "an item")
                self.player.inventory.append(item_id) 
                self.player.send_message(f"- {item_name}")
        
        # 7. Mark node as "tapped" for this player
        node_obj.setdefault("players_tapped", []).append(player_name)
        
        # 8. Deplete the node (if taps run out)
        taps_left = node_obj.get("default_taps", 1) - len(node_obj.get("players_tapped", []))
        if taps_left <= 0:
            self.player.send_message(f"The {node_obj['name']} is now depleted.")
            # (You'll add respawn logic for nodes here later)
            
        self.world.save_room(self.room)

class Survey(BaseVerb):
    """
    Handles the 'survey' (sense) command for lumberjacking.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return
            
        forestry_skill = self.player.skills.get("forestry", 0) 

        # --- NEW: Tool Check ---
        if not _has_tool(self.player, "lumberjacking"):
            self.player.send_message("You need to be wielding an axe to survey trees.")
            return
        # --- END NEW ---

        _set_action_roundtime(self.player, 3.0, rt_type="hard")
        
        if forestry_skill < 1: 
             self.player.send_message("You don't have the proper training to survey for trees.") 
             return

        self.player.send_message("You scan the area for useable trees...") 
        
        found_nodes = []
        for obj in self.room.objects:
            if (obj.get("is_gathering_node") and 
                obj.get("node_type") == "lumberjacking"): 
                found_nodes.append(obj)
        
        if not found_nodes:
            self.player.send_message("You do not sense any useable trees here.") 
            return
        
        self.player.send_message("You sense the following trees are present:") 
        for node in found_nodes:
            self.player.send_message(f"- {node.get('name', 'an unknown tree').title()}")