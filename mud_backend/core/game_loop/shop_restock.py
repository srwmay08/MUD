import json
import os
import random
import time
from mud_backend.config import Config
from mud_backend.core.game_objects import Item

# Path to the unified shop configuration
SHOP_STOCK_PATH = os.path.join(Config.ASSETS_PATH, "economy", "shop_stock.json")

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
        # This is a simplified lookup. In a real DB, you'd query by NPC ID.
        # Here we scan rooms for an NPC matching the shop_key name.
        
        interval = config.get("restock_interval", 300)
        # TODO: Store 'last_restock_time' on the NPC object itself to track individual cooldowns
        
        for room in world_rooms.values():
            for npc in room.npcs:
                # Loose matching for "Apothecary" vs "apothecary"
                if shop_key.lower() in npc.name.lower():
                    self._restock_npc(npc, config)

    def _restock_npc(self, npc, config):
        min_items = config.get("min_items", 3)
        max_items = config.get("max_items", 10)
        
        current_stock = [i for i in npc.inventory if isinstance(i, Item)]
        
        if len(current_stock) >= max_items:
            return

        # Restock
        items_needed = max_items - len(current_stock)
        item_templates = config.get("items", [])
        
        if not item_templates:
            return

        added_any = False
        for _ in range(items_needed):
            template = random.choice(item_templates)
            new_item = self._create_item_from_template(template)
            npc.add_item(new_item)
            added_any = True

        if added_any:
            msg = config.get("restock_message", f"{npc.name} restocks their wares.")
            if hasattr(npc.room, 'broadcast'):
                npc.room.broadcast(msg)

    def _create_item_from_template(self, template):
        """Creates an Item object from JSON definition."""
        item = Item()
        item.name = template.get("name", "Unknown")
        item.description = template.get("description", "")
        item.keywords = template.get("keywords", [])
        item.weight = template.get("weight", 0.0)
        item.value = template.get("base_value", 0)
        # item.type = template.get("type", "misc") 
        return item

    def _load_config(self):
        if not os.path.exists(SHOP_STOCK_PATH):
            return None
        try:
            with open(SHOP_STOCK_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None