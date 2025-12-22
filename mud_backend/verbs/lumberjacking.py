# mud_backend/verbs/lumberjacking.py
import random
import time
import math
import copy
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import loot_system
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.skill_handler import attempt_skill_learning
from mud_backend import config
from typing import Dict, Any
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core.registry import VerbRegistry

def _find_target_node(room_objects: list, target_name: str, node_type: str) -> Dict[str, Any] | None:
    for obj in room_objects:
        if (obj.get("is_gathering_node") and 
            obj.get("node_type") == node_type):
            if (target_name == obj.get("name", "").lower() or 
                target_name in obj.get("keywords", [])):
                return obj
    return None

def _has_tool(player, required_tool_type: str) -> bool:
    for slot in ["mainhand", "offhand"]:
        item_id = player.worn_items.get(slot)
        if item_id:
            item_data = player.world.game_items.get(item_id)
            if item_data and item_data.get("tool_type") == required_tool_type:
                return True
    return False

@VerbRegistry.register(["chop", "cut"]) 
class Chop(BaseVerb):
    """Handles the 'chop' command."""
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return
        if not _has_tool(self.player, "lumberjacking"):
            self.player.send_message("You need to be wielding an axe to chop wood.")
            return
        if not self.args:
            self.player.send_message("Chop what?")
            return

        target_name = " ".join(self.args).lower()
        node_obj = _find_target_node(self.room.objects, target_name, "lumberjacking") 

        if not node_obj:
            self.player.send_message(f"You don't see a {target_name} here to chop.")
            return
            
        player_name = self.player.name
        player_hit_data = node_obj.setdefault("player_hits", {})
        if player_name not in player_hit_data:
            player_hit_data[player_name] = {
                "max_hits": random.randint(1, 5),
                "hits_made": 0
            }
        my_data = player_hit_data[player_name]

        if my_data["hits_made"] >= my_data["max_hits"]:
            self.player.send_message(f"You have already chopped {node_obj['name']}.") 
            return
            
        global_hits_made = node_obj.get("global_hits_made", 0)
        global_max_taps = node_obj.get("default_taps", 1)
        if global_hits_made >= global_max_taps:
            self.player.send_message(f"The {node_obj['name']} is depleted.")
            if node_obj in self.room.objects:
                self.room.objects.remove(node_obj)
                self.world.save_room(self.room)
            return

        forestry_skill = self.player.skills.get("forestry", 0) 
        base_rt = 8.0 
        rt_reduction = forestry_skill / 20.0 
        rt = max(2.0, base_rt - rt_reduction) 
        set_action_roundtime(self.player, rt, f"You begin chopping {node_obj['name']}...", rt_type="hard")

        skill_dc = node_obj.get("skill_dc", 20)
        attempt_skill_learning(self.player, "lumberjacking") 
        roll = forestry_skill + random.randint(1, 100) 

        if roll < skill_dc:
            self.player.send_message(f"You try to chop {node_obj['name']} but fail to get any wood.")
            my_data["hits_made"] += 1
            node_obj["global_hits_made"] = node_obj.get("global_hits_made", 0) + 1
            if node_obj["global_hits_made"] >= node_obj.get("default_taps", 1):
                self.player.send_message(f"The {node_obj['name']} is now depleted.")
                if node_obj in self.room.objects:
                    self.room.objects.remove(node_obj)
            self.world.save_room(self.room)
            return
        
        loot_table_id = node_obj.get("loot_table_id")
        if not loot_table_id:
            self.player.send_message("You chop the tree, but it seems to be empty.") 
        else:
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

        player_level = self.player.level
        node_level = node_obj.get("level", 1)
        level_diff = player_level - node_level 
        nominal_xp = 0
        if level_diff >= 10: nominal_xp = 0
        elif 1 <= level_diff <= 9: nominal_xp = 10 - (1 * level_diff)
        elif level_diff == 0: nominal_xp = 10
        elif -4 <= level_diff <= -1: nominal_xp = 10 + (1 * abs(level_diff))
        elif level_diff <= -5: nominal_xp = 15
        nominal_xp = max(0, nominal_xp)
        if nominal_xp > 0:
            self.player.send_message(f"You have gained {nominal_xp} experience from chopping wood.")
            self.player.grant_experience(nominal_xp, source="lumberjacking")

        my_data["hits_made"] += 1
        global_hits_made = node_obj.get("global_hits_made", 0) + 1
        node_obj["global_hits_made"] = global_hits_made
        global_max_taps = node_obj.get("default_taps", 1)
        if global_hits_made >= global_max_taps:
            self.player.send_message(f"The {node_obj['name']} is now depleted.")
            if node_obj in self.room.objects:
                self.room.objects.remove(node_obj)
        self.world.save_room(self.room)

@VerbRegistry.register(["survey"]) 
class Survey(BaseVerb):
    """Handles the 'survey' (sense) command for lumberjacking."""
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return
        forestry_skill = self.player.skills.get("forestry", 0) 
        set_action_roundtime(self.player, 3.0, rt_type="hard")
        self.player.send_message("You scan the area for useable trees...") 

        found_nodes_list = []
        refresh_room = False
        hidden_objects = self.room.db_data.get("hidden_objects", [])
        for i in range(len(hidden_objects) - 1, -1, -1):
            obj_stub = hidden_objects[i]
            if obj_stub.get("node_type") == "lumberjacking":
                dc = obj_stub.get("perception_dc", 999)
                roll = forestry_skill + random.randint(1, 100)
                if roll >= dc:
                    found_stub = self.room.db_data["hidden_objects"].pop(i)
                    full_node = copy.deepcopy(self.world.game_nodes.get(found_stub["node_id"]))
                    if not full_node: continue
                    full_node.update(found_stub)
                    self.room.objects.append(full_node)
                    found_nodes_list.append(full_node.get("name", "a tree"))
                    refresh_room = True

        if refresh_room:
            self.world.save_room(self.room)
            player_info = self.world.get_player_info(self.player.name.lower())
            sid = player_info.get("sid") if player_info else None
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} spots {found_nodes_list[0]}!", 
                "message",
                skip_sid=sid
            )
            self.player.send_message(f"You spot {found_nodes_list[0]}!")
        else:
            self.player.send_message("You do not sense any useable trees here.")