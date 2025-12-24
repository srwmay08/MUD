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
        print(f"Warning: Restock pools file not found at {json_path}")
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
    """
    found = False
    for obj in room.objects:
        if obj.get("is_npc") and "shop_data" in obj:
            # We assume the shop_data passed in IS the reference from the object,
            # but this ensures we mark the room dirty if needed.
            # Since objects are typically dicts in a list, modifying shop_data in place works.
            # We just need to ensure the room saves.
            found = True
            break
    
    if not found and "shop_data" in room.data:
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
    
    target_table = "counter"
    
    for table in tables:
        t_keys = table.get("keywords", [])
        if itype == "weapon" and ("weapon" in t_keys or "weapons" in t_keys):
            return table.get("name")
        if itype == "armor" and ("armor" in t_keys or "armors" in t_keys):
            return table.get("name")
        if itype == "magic" and ("magic" in t_keys or "scrolls" in t_keys):
            return table.get("name")
            
    # Default to first table if found, else generic
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
    Called by observation verbs (look/examine).
    """
    # Reload pools periodically? For now, static load is safer for performance.
    # To enable hot-reloading, call load_restock_pools() here or verify timestamp.
    # sticking to module-level load for efficiency as per standard request.
    
    updated = False
    
    for obj in room.objects:
        if not obj.get("is_dynamic_display"):
            continue
            
        pool_id = obj.get("restock_id")
        if not pool_id or pool_id not in SHOP_RESTOCK_POOLS:
            continue
            
        pool_config = SHOP_RESTOCK_POOLS[pool_id]
        last_update = obj.get("last_restock_time", 0)
        interval = pool_config.get("interval", 300)
        
        if time.time() - last_update < interval:
            continue
            
        # Perform Restock
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
            
        obj["container_storage"] = {"in": new_stock}
        obj["last_restock_time"] = time.time()
        
        # Ambient Message
        msg = pool_config.get("message")
        if msg:
            world.broadcast_to_room(room.room_id, msg, "message")
            
        updated = True
        
    if updated:
        world.save_room(room)