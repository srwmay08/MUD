# mud_backend/verbs/mining.py
import random
import time
import math
import copy
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import loot_system
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend import config
from typing import Dict, Any
from mud_backend.core.room_handler import show_room_to_player

def _find_target_node(room_objects: list, target_name: str, node_type: str) -> Dict[str, Any] | None:
    """Helper to find a gathering node by name and type."""
    # This helper only needs to search room.objects,
    # because nodes must be "sensed" (moved to room.objects) before harvesting.
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

@VerbRegistry.register(["mine"]) 
@VerbRegistry.register(["prospect"])

class Mine(BaseVerb):
    """
    Handles the 'mine' command.
    Attempts to mine an ore/gem node.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

        # 1. Check for required tool
        if not _has_tool(self.player, "mining"):
            self.player.send_message("You need to be wielding a pickaxe to mine.")
            return

        if not self.args:
            self.player.send_message("Mine what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 2. Find the node
        node_obj = _find_target_node(self.room.objects, target_name, "mining")

        if not node_obj:
            self.player.send_message(f"You don't see a {target_name} here to mine.")
            return
            
        # 3. Check depletion
        player_name = self.player.name
        
        # Get/initialize the player-specific hit data for this node instance
        player_hit_data = node_obj.setdefault("player_hits", {})
        if player_name not in player_hit_data:
            player_hit_data[player_name] = {
                "max_hits": random.randint(1, 5), # Roll 1-5 attempts for this player
                "hits_made": 0
            }
        
        my_data = player_hit_data[player_name]

        # 3a. Check if PLAYER has attempts left
        if my_data["hits_made"] >= my_data["max_hits"]:
            self.player.send_message(f"You have already mined {node_obj['name']}.") 
            return
            
        # 3b. Check if NODE has global taps left
        global_hits_made = node_obj.get("global_hits_made", 0)
        global_max_taps = node_obj.get("default_taps", 1)
        
        if global_hits_made >= global_max_taps:
            self.player.send_message(f"The {node_obj['name']} is depleted.")
            if node_obj in self.room.objects:
                self.room.objects.remove(node_obj)
                self.world.save_room(self.room)
            return
            
        # 4. Set Roundtime (based on Mining skill)
        mining_skill = self.player.skills.get("mining", 0)
        base_rt = 8.0 # Example: 8s base time
        rt_reduction = mining_skill / 20.0 # 1s off per 20 ranks
        rt = max(2.0, base_rt - rt_reduction) # 2s minimum
        
        _set_action_roundtime(self.player, rt, f"You begin mining {node_obj['name']}...", rt_type="hard")

        # 5. Roll for Success (Skill vs. DC)
        skill_dc = node_obj.get("skill_dc", 20)
        
        attempt_skill_learning(self.player, "mining")
        
        geology_skill = self.player.skills.get("geology", 0)
        
        # Roll: Skill + d100 vs DC
        roll = geology_skill + random.randint(1, 100) # <-- Use geology   

        if roll < skill_dc:
            self.player.send_message(f"You try to mine {node_obj['name']} but fail to get any ore.")
            
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

        # 6. Get Loot
        loot_table_id = node_obj.get("loot_table_id")
        if not loot_table_id:
            self.player.send_message("You mine the vein, but it seems to be empty.")
            # We still consume a tap even if empty to prevent infinite loops on bad data
        else:
            item_ids_to_give = loot_system.generate_loot_from_table(
                loot_table_id,
                self.world.game_loot_tables,
                self.world.game_items
            )

            if not item_ids_to_give:
                self.player.send_message("You mine the vein, but it seems to be empty.")
            else:
                self.player.send_message(f"You mine {node_obj['name']} and receive:")
                for item_id in item_ids_to_give:
                    item_data = self.world.game_items.get(item_id, {})
                    item_name = item_data.get("name", "an item")
                    self.player.inventory.append(item_id) # Add directly to inventory
                    self.player.send_message(f"- {item_name}")

        # ---
        # --- NEW: XP Calculation (1/10th Monster Rate + Band Sharing)
        # ---
        player_level = self.player.level
        node_level = node_obj.get("level", 1)
        level_diff = player_level - node_level 
        
        # Base logic: Monster XP formula divided by 10
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
        
        nominal_xp = max(0, nominal_xp) # Ensure non-negative
        
        if nominal_xp > 0:
            # Grant XP using the central method that handles Band Splitting & Death's Sting
            self.player.grant_experience(nominal_xp, source="mining")
        # ---
        # --- END NEW XP LOGIC
        # ---
        
        # 7. Mark hit as used for this player
        my_data["hits_made"] += 1
        
        # 8. Mark global hit as used
        global_hits_made = node_obj.get("global_hits_made", 0) + 1
        node_obj["global_hits_made"] = global_hits_made
        global_max_taps = node_obj.get("default_taps", 1)

        # 9. Deplete the node if global taps run out
        if global_hits_made >= global_max_taps:
            self.player.send_message(f"The {node_obj['name']} is now depleted.")
            if node_obj in self.room.objects:
                self.room.objects.remove(node_obj)
        
        self.world.save_room(self.room)

class Prospect(BaseVerb):
    """
    Handles the 'prospect' (sense) command for mining.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return
            
        geology_skill = self.player.skills.get("geology", 0) # <-- Use geology
        
        # No tool check needed for prospecting

        _set_action_roundtime(self.player, 3.0, rt_type="hard")
        
        self.player.send_message("You scan the area for mineral deposits...") 
        
        # --- NEW REVEAL LOGIC ---
        found_nodes_list = []
        refresh_room = False
        
        # Iterate backwards so we can pop items
        hidden_objects = self.room.db_data.get("hidden_objects", [])
        for i in range(len(hidden_objects) - 1, -1, -1):
            obj_stub = hidden_objects[i]
            
            if obj_stub.get("node_type") == "mining":
                dc = obj_stub.get("perception_dc", 999)
                roll = geology_skill + random.randint(1, 100)
                
                if roll >= dc:
                    # Success! Pop from hidden and add to live
                    found_stub = self.room.db_data["hidden_objects"].pop(i)
                    
                    # Get full template
                    full_node = copy.deepcopy(self.world.game_nodes.get(found_stub["node_id"]))
                    if not full_node: continue
                    
                    full_node.update(found_stub) # Apply instance data (like taps)
                    self.room.objects.append(full_node) # Add to live room
                    
                    found_nodes_list.append(full_node.get("name", "a node"))
                    refresh_room = True

        if refresh_room:
            # 1. Save the room so the node is persistent
            self.world.save_room(self.room)
            
            # 2. Get the player's SID to skip them in the broadcast
            player_info = self.world.get_player_info(self.player.name.lower())
            sid = player_info.get("sid") if player_info else None
            
            # 3. Broadcast to *everyone else* in the room
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} spots {found_nodes_list[0]}!", 
                "message",
                skip_sid=sid # Send to everyone *except* the player
            )
            
            # 4. Send a simple message *only* to the player
            self.player.send_message(f"You spot {found_nodes_list[0]}!")
            
        else:
            self.player.send_message("You do not sense any deposits here.")