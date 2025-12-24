# mud_backend/core/shop_system.py
import json
import os
from mud_backend import config

# Correct path to the unified shop configuration
SHOP_STOCK_PATH = os.path.join(config.ASSETS_PATH, "economy", "shop_stock.json")

def _load_shop_config():
    """
    Internal helper to load shop configuration from JSON.
    """
    if not os.path.exists(SHOP_STOCK_PATH):
        return {}

    try:
        with open(SHOP_STOCK_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

def get_shop_flavor(npc_name):
    """
    Retrieves the flavor configuration (bags, emotes) for a specific NPC.
    Normalizes names (e.g. "The Apothecary" -> "apothecary").
    """
    data = _load_shop_config()
    if not data:
        return _get_default_config()

    # Normalize name: remove "The ", lowercase, replace spaces with underscores
    clean_name = npc_name.lower().replace("the ", "").strip()
    
    # Try exact match first
    if clean_name in data:
        return data[clean_name]
    
    # Try partial match (e.g. "apothecary" in "master apothecary")
    for key, config in data.items():
        if key in clean_name:
            return config
            
    return _get_default_config()

def _get_default_config():
    """
    Returns a generic fallback configuration.
    """
    return {
        "bag_name": "{player}'s bag",
        "bag_desc": "A simple bag with '{player}' written on it.",
        "bagging_emote": "{npc} puts the {item} into a bag and sets it on the counter.",
        "counter_key": "counter"
    }