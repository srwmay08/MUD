# mud_backend/core/shop_system.py
import os
from mud_backend.core.shop_controller import ShopController

def get_or_create_shop_controller(room, world):
    """
    Retrieves the existing ShopController for a room, or creates one
    if the room has a configured shop_config_id.
    """
    if hasattr(room, "shop_controller"):
        # Periodically check schedule on access
        room.shop_controller.check_schedule()
        return room.shop_controller
        
    # Check if room has a shop configuration ID
    shop_config_id = room.data.get("shop_config_id")
    
    if shop_config_id:
        controller = ShopController(f"{shop_config_id}.json", room, world)
        room.shop_controller = controller
        return controller
        
    return None

def get_shop_flavor(npc_name):
    """
    Legacy helper for generic flavor text.
    """
    return {
        "bag_name": "{player}'s bag",
        "bag_desc": "A simple bag with '{player}' written on it.",
        "bagging_emote": "{npc} puts the {item} into a bag and sets it on the {counter}.",
        "counter_key": "counter"
    }