# mud_backend/core/game_loop/shop_restock.py
import json
import os
import random
import time
import copy
from mud_backend import config
from mud_backend.core.game_objects import Item

# Path to the unified shop configuration
SHOP_STOCK_PATH = os.path.join(config.ASSETS_PATH, "economy", "shop_stock.json")

class ShopRestockSystem:
    def __init__(self):
        self.last_run = time.time()
        self.shops_cache = {}

    def update(self, world_rooms):
        """
        Called by the main game loop to check restock timers.
        Args:
            world_rooms (dict): Dictionary of room_id: room_obj
        """
        current_time = time.time()
        
        # Only check every 10 seconds to save performance
        if current_time - self.last_run < 10:
            return

        self.last_run = current_time
        
        # Reload config to catch updates
        shop_data = self._load_config()
        if not shop_data:
            return

        # Iterate through data to find matching NPCs in the world
        for shop_key, config in shop_data.items():
            self._process_shop(shop_key, config, world_rooms)

    def _process_shop(self, shop_key, config, world_rooms):
        # Scan rooms for an NPC matching the shop_key name.
        
        # Determine strictness of match
        target_name = shop_key.lower().replace("_", " ")

        for room in world_rooms.values():
            # Ensure room has NPCs list initialized
            if not hasattr(room, 'objects'):
                continue
                
            for obj in room.objects:
                if not obj.get("is_npc", False):
                    continue

                npc_name = obj.get("name", "").lower()
                
                # Loose matching: "apothecary" matches "The Apothecary"
                if target_name in npc_name:
                    self._restock_npc(obj, config, room)

    def _restock_npc(self, npc, config, room):
        min_items = config.get("min_items", 3)
        max_items = config.get("max_items", 10)
        
        # Count actual items in inventory (ignoring equipped/system props)
        inventory = npc.get("inventory", [])
        current_count = len(inventory)
        
        if current_count >= max_items:
            return

        # Restock
        items_needed = max_items - current_count
        
        # FIX: Key mismatch ("restock_items" vs "items")
        item_refs = config.get("restock_items", [])
        
        if not item_refs:
            return

        added_any = False
        for _ in range(items_needed):
            item_ref = random.choice(item_refs)
            
            # Since we only have the string ID here, we just append the reference.
            # The shop logic (get_shop_data) handles resolving strings to game items.
            inventory.append(item_ref)
            added_any = True

        if added_any:
            msg_template = config.get("restock_message", "{npc} restocks their wares.")
            msg = msg_template.format(npc=npc.get("name", "The shopkeeper"))
            
            # Broadcast availability check
            # Assuming 'world' is available via some global or room link, 
            # otherwise simplistic print for now (broadcast requires world instance)
            pass 

    def _load_config(self):
        if not os.path.exists(SHOP_STOCK_PATH):
            return None
        try:
            with open(SHOP_STOCK_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None