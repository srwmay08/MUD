# mud_backend/core/economy.py
import random
from typing import Dict, Any, Optional, Union

def get_shop_data(room) -> dict | None:
    """Helper to get shop data from a room."""
    for obj in room.objects:
        if "shop_data" in obj:
            s_data = obj.get("shop_data")
            # Handle empty list from JSON by initializing defaults
            if isinstance(s_data, list):
                s_data = {"inventory": [], "sold_counts": {}}
                obj["shop_data"] = s_data
                return s_data

            if s_data is not None and isinstance(s_data, dict):
                if "inventory" not in s_data: s_data["inventory"] = []
                if "sold_counts" not in s_data: s_data["sold_counts"] = {}
                return s_data
    return None

def sync_shop_data_to_storage(room, updated_shop_data):
    """
    Syncs the modified shop_data from the live object (room.objects)
    back to the raw persistent storage (room.data['objects']).
    """
    target_name = None
    for obj in room.objects:
        if obj.get("shop_data") is updated_shop_data:
            target_name = obj.get("name")
            break
            
    if not target_name:
        return

    raw_objects = room.data.get("objects", [])
    for stub in raw_objects:
        if stub.get("name") == target_name and "shop_data" in stub:
            stub["shop_data"] = updated_shop_data
            break

def get_item_type(item_data: dict) -> str:
    """Helper to safely determine item type from various schema versions."""
    base_type = item_data.get("item_type") or item_data.get("type", "misc")
    if "weapon_type" in item_data: return "weapon"
    if "armor_type" in item_data: return "armor"
    if "spell" in item_data or "scroll" in item_data.get("keywords", []): return "magic"
    return base_type

def get_supply_demand_modifier(shop_data: dict, item_type: str) -> float:
    counts = shop_data.get("sold_counts", {})
    count = counts.get(item_type, 0)
    reduction = count * 0.05
    return max(0.5, 1.0 - reduction)

def get_item_buy_price(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any], shop_data: Optional[dict] = None) -> int:
    if isinstance(item_ref, dict):
        item_data = item_ref
    else:
        item_data = game_items_data.get(item_ref)

    if not item_data:
        return 0

    base = item_data.get("base_value", 0) * 2

    if shop_data:
        itype = get_item_type(item_data)
        mod = get_supply_demand_modifier(shop_data, itype)
        return int(base * mod)

    return base

def get_item_sell_price(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any], shop_data: Optional[dict] = None) -> int:
    if isinstance(item_ref, dict):
        item_data = item_ref
    else:
        item_data = game_items_data.get(item_ref)

    if not item_data:
        return 0

    base_val = item_data.get("base_value", 0)

    if shop_data:
        itype = get_item_type(item_data)
        mod = get_supply_demand_modifier(shop_data, itype)
        base_val = int(base_val * mod)

    max_val = item_data.get("max_value")
    if max_val and max_val > base_val:
        return random.randint(base_val, max_val)

    return base_val

def get_display_table_name(room, item_data) -> str:
    """Finds the name of the table appropriate for the item."""
    itype = get_item_type(item_data)

    for obj in room.objects:
        keywords = obj.get("keywords", [])
        if "table" not in keywords: continue

        if itype == "weapon" and ("weapon" in keywords or "weapons" in keywords): return obj.get("name", "table")
        if itype == "armor" and ("armor" in keywords or "armors" in keywords): return obj.get("name", "table")
        if itype == "magic" and ("magic" in keywords or "arcane" in keywords): return obj.get("name", "table")
        if itype == "misc" and "goods" in keywords: return obj.get("name", "table")
    
    return "display table"