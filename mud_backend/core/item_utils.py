# mud_backend/core/item_utils.py
import re
from typing import Dict, Any, Union, Tuple, Optional, TYPE_CHECKING
from mud_backend.core.utils import clean_name

if TYPE_CHECKING:
    from mud_backend.core.game_objects import Player

def get_item_data(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(item_ref, dict):
        return item_ref
    return game_items_data.get(item_ref, {})

def find_item_in_room(room_objects: list, target_name: str) -> Dict[str, Any] | None:
    # 1. ID Match (Precision Lookup)
    if target_name.startswith('#'):
        target_uid = target_name[1:]
        for obj in room_objects:
            # Check if obj has a UID and it matches
            if str(obj.get("uid")) == target_uid:
                return obj
        # If specific ID requested but not found, do not fall back to name matching
        return None

    # 2. Name/Keyword Match (Standard Lookup)
    clean_target = clean_name(target_name)
    for obj in room_objects:
        if not obj.get("is_item"):
            continue
        obj_name = obj.get("name", "").lower()
        if clean_target == obj_name or clean_target == clean_name(obj_name) or clean_target in obj.get("keywords", []):
            return obj
    return None

def find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> Union[str, Dict[str, Any], None]:
    # 1. ID Match
    if target_name.startswith('#'):
        target_uid = target_name[1:]
        for item in player.inventory:
            # Item might be a dict (instanced) or string (ref)
            # Only dict items have UIDs usually
            if isinstance(item, dict) and str(item.get("uid")) == target_uid:
                return item
        return None

    # 2. Name Match
    clean_target = clean_name(target_name)
    for item in player.inventory:
        item_data = get_item_data(item, game_items_data)
        if item_data:
            i_name = item_data.get("name", "").lower()
            if clean_target == i_name or clean_target == clean_name(i_name) or clean_target in item_data.get("keywords", []):
                return item
    return None

def find_item_in_hands(player, game_items_data: Dict[str, Any], target_name: str) -> Tuple[Any, Optional[str]]:
    # ID matching for hands is tricky as they are usually refs in worn_items, 
    # but we can try if the worn item is a dict with UID.
    if target_name.startswith('#'):
        target_uid = target_name[1:]
        for slot in ["mainhand", "offhand"]:
            item_ref = player.worn_items.get(slot)
            if isinstance(item_ref, dict) and str(item_ref.get("uid")) == target_uid:
                return item_ref, slot
        return None, None

    clean_target = clean_name(target_name)
    for slot in ["mainhand", "offhand"]:
        item_ref = player.worn_items.get(slot)
        if item_ref:
            item_data = get_item_data(item_ref, game_items_data)
            if item_data:
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    return item_ref, slot
    return None, None

def find_item_worn(player, target_name: str) -> Tuple[str | None, str | None]:
    if target_name.startswith('#'):
        target_uid = target_name[1:]
        for slot, item_id in player.worn_items.items():
            if isinstance(item_id, dict) and str(item_id.get("uid")) == target_uid:
                return item_id, slot
        return None, None

    clean_target = clean_name(target_name)
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = get_item_data(item_id, player.world.game_items)
            if item_data:
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    return item_id, slot
    return None, None

def find_container_on_player(player, game_items_data: Dict[str, Any], target_name: str) -> Dict[str, Any] | None:
    # 1. ID Match
    if target_name.startswith('#'):
        target_uid = target_name[1:]
        # Worn
        for slot, item in player.worn_items.items():
            if isinstance(item, dict) and str(item.get("uid")) == target_uid:
                item_data_copy = item.copy()
                item_data_copy["_runtime_item_ref"] = item
                return item_data_copy
        # Inventory
        for item in player.inventory:
            if isinstance(item, dict) and str(item.get("uid")) == target_uid:
                item_data_copy = item.copy()
                item_data_copy["_runtime_item_ref"] = item
                return item_data_copy
        return None

    # 2. Name Match
    clean_target = clean_name(target_name)
    # Worn
    for slot, item in player.worn_items.items():
        if item:
            item_data = get_item_data(item, game_items_data)
            if item_data and item_data.get("is_container"):
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    # Attach ref for runtime use
                    item_data_copy = item_data.copy()
                    item_data_copy["_runtime_item_ref"] = item
                    return item_data_copy
    # Inventory
    for item in player.inventory:
        item_data = get_item_data(item, game_items_data)
        if item_data and item_data.get("is_container"):
            i_name = item_data.get("name", "").lower()
            if clean_target == i_name or clean_target == clean_name(i_name) or clean_target in item_data.get("keywords", []):
                item_data_copy = item_data.copy()
                item_data_copy["_runtime_item_ref"] = item
                return item_data_copy
    return None

def find_item_in_obj_storage(obj, target_item_name, game_items, specific_prep=None):
    # 1. ID Match
    if target_item_name.startswith('#'):
        target_uid = target_item_name[1:]
        storage = obj.get("container_storage", {})
        preps_to_check = [specific_prep] if specific_prep else storage.keys()
        
        for prep in preps_to_check:
            items_list = storage.get(prep, [])
            for i, item_ref in enumerate(items_list):
                # Check if item_ref is a dict with UID (common for unique items)
                if isinstance(item_ref, dict) and str(item_ref.get("uid")) == target_uid:
                    return item_ref, prep, i
                # Note: if item is just a string ref ID, we can't match a specific UID
        return None, None, -1

    # 2. Name Match
    clean_target = clean_name(target_item_name)
    storage = obj.get("container_storage", {})
    preps_to_check = [specific_prep] if specific_prep else storage.keys()

    for prep in preps_to_check:
        items_list = storage.get(prep, [])
        for i, item_ref in enumerate(items_list):
            item_data = get_item_data(item_ref, game_items)
            if item_data:
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    return item_ref, prep, i
    return None, None, -1

def has_tool_equipped(player: 'Player', required_tool_type: str, game_items: Dict[str, Any]) -> bool:
    """
    Checks if the player is wielding a tool of the required type in either hand.
    Checks 'tool_type' (e.g., 'knife', 'hammer') or 'skill' (e.g., 'small_edged').
    """
    for slot in ["mainhand", "offhand"]:
        item_ref = player.worn_items.get(slot)
        if item_ref:
            # Handle both string IDs and dictionary item instances
            item_data = get_item_data(item_ref, game_items)
            
            if item_data:
                # Check specific tool type tag
                if item_data.get("tool_type") == required_tool_type:
                    return True
                # Fallback: Some knives might just be weapons with small_edged skill
                if required_tool_type == "knife" and item_data.get("skill") == "small_edged":
                    return True
    return False