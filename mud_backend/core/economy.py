# mud_backend/core/economy.py
import time
import random
import uuid
import copy
import json
import os
from typing import Dict, Any, List, Optional

# --- Configuration for Dynamic Shop Displays ---

def load_restock_pools() -> Dict[str, Any]:
    """
    Loads restock pools from the JSON asset file.
    Expected path: ../data/assets/economy/restock_pools.json relative to this file.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one level (to mud_backend), then down to data/assets/economy
    json_path = os.path.join(current_dir, "..", "data", "assets", "economy", "restock_pools.json")
    json_path = os.path.normpath(json_path)
    
    if not os.path.exists(json_path):
        return {}
        
    try:
        with open(json_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading restock pools: {e}")
        return {}

# Load once at module import time
SHOP_RESTOCK_POOLS = load_restock_pools()

def get_shop_data(room) -> Optional[Dict[str, Any]]:
    """
    Retrieves the shop metadata from a room. 
    It looks for an object with "is_npc": true and "shop_data".
    """
    for obj in room.objects:
        if obj.get("is_npc") and "shop_data" in obj:
            return obj["shop_data"]
    
    # Fallback: Check room data itself (for unstaffed shops)
    if "shop_data" in room.data:
        return room.data["shop_data"]
        
    return None

def sync_shop_data_to_storage(room, shop_data: Dict[str, Any]):
    """
    Saves the modified shop_data back to the room/NPC object.
    Updates both the hydrated view (room.objects) and the persistent source (room.data).
    """
    # 1. Update View
    found_in_view = False
    for obj in room.objects:
        if obj.get("is_npc") and "shop_data" in obj:
            obj["shop_data"] = shop_data
            found_in_view = True
            break
            
    # 2. Update Persistence (room.data)
    # Since hydration deep-copies objects, we must explicitly write back to room.data
    found_in_data = False
    if "objects" in room.data:
        for stub in room.data["objects"]:
            # Heuristic match: if view object has a UID, match it. 
            # Otherwise match by name/npc flag.
            matched = False
            if "uid" in stub and found_in_view:
                # Iterate view to find matching UID
                for v_obj in room.objects:
                    if v_obj.get("is_npc") and v_obj.get("uid") == stub.get("uid"):
                        matched = True
                        break
            
            # Fallback simple match if UID not ready
            if not matched and stub.get("is_npc") and stub.get("name") == shop_data.get("name"):
                matched = True
            
            if matched:
                stub["shop_data"] = shop_data
                found_in_data = True
                break

    if not found_in_data and "shop_data" in room.data:
        room.data["shop_data"] = shop_data

def get_item_buy_price(item_ref: Any, game_items: Dict[str, Any], shop_data: Dict[str, Any]) -> int:
    """
    Calculates the price a player pays to buy an item.
    """
    if isinstance(item_ref, dict):
        base_value = item_ref.get("base_value", 0)
    else:
        base_value = game_items.get(item_ref, {}).get("base_value", 0)
        
    markup = shop_data.get("markup", 1.2)
    return int(base_value * markup)

def get_item_sell_price(item_ref: Any, game_items: Dict[str, Any], shop_data: Dict[str, Any]) -> int:
    """
    Calculates the price a shop pays to buy an item from a player.
    """
    if isinstance(item_ref, dict):
        base_value = item_ref.get("base_value", 0)
    else:
        base_value = game_items.get(item_ref, {}).get("base_value", 0)
        
    markdown = shop_data.get("markdown", 0.5)
    return int(base_value * markdown)

def get_display_table_name(room, item_data: Dict[str, Any]) -> str:
    """
    Determines which table/display an item should go on based on keywords.
    """
    itype = get_item_type(item_data)
    
    # Find tables in room
    tables = [obj for obj in room.objects if "table" in obj.get("keywords", []) or obj.get("is_table_proxy")]
    
    for table in tables:
        t_keys = table.get("keywords", [])
        if itype == "weapon" and ("weapon" in t_keys or "weapons" in t_keys):
            return table.get("name")
        if itype == "armor" and ("armor" in t_keys or "armors" in t_keys):
            return table.get("name")
        if itype == "magic" and ("magic" in t_keys or "scrolls" in t_keys):
            return table.get("name")
            
    if tables:
        return tables[0].get("name")
        
    return "shop counter"

def get_item_type(item_data: Dict[str, Any]) -> str:
    if not item_data: return "misc"
    
    t = item_data.get("type", "misc")
    if t in ["weapon", "ammo"]: return "weapon"
    if t in ["armor", "shield"]: return "armor"
    if t in ["scroll", "potion", "wand", "staff"]: return "magic"
    return "misc"

def check_dynamic_restock(room, world):
    """
    Generic system to restock display cases based on 'restock_id'.
    Updates both the hydrated view object AND the persistent room.data stub.
    """
    updated = False
    current_time = time.time()
    
    global SHOP_RESTOCK_POOLS
    if not SHOP_RESTOCK_POOLS:
        SHOP_RESTOCK_POOLS = load_restock_pools()

    # Iterate over hydrated objects to find targets
    for obj in room.objects:
        if not obj.get("is_dynamic_display"):
            continue
            
        pool_id = obj.get("restock_id")
        if not pool_id or pool_id not in SHOP_RESTOCK_POOLS:
            continue
            
        # CRITICAL: Find the persistent stub in room.data["objects"]
        # We need to read the TIME from the stub, and write ITEMS back to the stub.
        persistent_stub = None
        if "objects" in room.data:
            for stub in room.data["objects"]:
                # Match by UID
                if stub.get("uid") and stub["uid"] == obj.get("uid"):
                    persistent_stub = stub
                    break
                # Fallback Match by ID
                if stub.get("restock_id") == pool_id:
                    persistent_stub = stub
                    break
        
        if not persistent_stub:
            continue

        pool_config = SHOP_RESTOCK_POOLS[pool_id]
        
        last_update = persistent_stub.get("last_restock_time", 0)
        interval = pool_config.get("interval", 300)
        
        # Check current inventory state
        # If last_update is 0 and inventory is empty, treat as "Needs Init"
        # If last_update is 0 and inventory exists (manual edit?), treat as "Stocked" but track time now.
        storage = persistent_stub.get("container_storage", {}).get("in", [])
        
        if last_update == 0 and not storage:
            # Need initial stock
            pass
        elif last_update == 0 and storage:
            # Has items but no timestamp. Set timestamp to avoid instant re-roll.
            persistent_stub["last_restock_time"] = current_time
            obj["last_restock_time"] = current_time
            updated = True
            continue
        elif current_time - last_update < interval:
            # Not time yet
            continue
            
        # --- Perform Restock ---
        min_i = pool_config.get("min_items", 1)
        max_i = pool_config.get("max_items", 5)
        count = random.randint(min_i, max_i)
        
        candidates = pool_config.get("items", [])
        if not candidates:
            continue
            
        selected_items = random.sample(candidates, min(len(candidates), count))
        
        new_stock = []
        for item_def in selected_items:
            # Instantiate
            new_item = copy.deepcopy(item_def)
            new_item["uid"] = uuid.uuid4().hex
            new_stock.append(new_item)
            
        # Update Persistent Stub
        if "container_storage" not in persistent_stub:
            persistent_stub["container_storage"] = {}
        persistent_stub["container_storage"]["in"] = new_stock
        persistent_stub["last_restock_time"] = current_time
        
        # Update Hydrated View (so player sees it immediately)
        obj["container_storage"] = persistent_stub["container_storage"]
        obj["last_restock_time"] = current_time
        
        # Ambient Message
        msg = pool_config.get("message")
        if msg:
            world.broadcast_to_room(room.room_id, msg, "message")
            
        updated = True
        
    if updated:
        world.save_room(room)