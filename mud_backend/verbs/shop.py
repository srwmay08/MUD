# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import db
import random
import time
import uuid
import copy
from typing import Tuple, Optional, Dict, Any, Union
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.item_utils import find_item_in_hands, find_item_in_inventory
from mud_backend.core.economy import (
    get_shop_data, sync_shop_data_to_storage, get_item_buy_price, 
    get_item_sell_price, get_display_table_name, get_item_type
)
from mud_backend.core.shop_system import get_shop_flavor

def deliver_purchase(verb, item, shop_data):
    """
    Delivers a purchased item to the player.
    Prioritizes:
    1. Right Hand (Mainhand)
    2. Left Hand (Offhand)
    3. Bagged and placed on a Counter (if available) - Uses shop_stock.json flavor
    4. Bagged and placed on the Floor
    """
    player = verb.player
    room = verb.room
    keeper_name = shop_data.get("keeper_name", "The shopkeeper")
    
    # Get Item Name
    if isinstance(item, dict):
        item_name = item.get("name", "item")
    else:
        item_data = verb.world.game_items.get(item, {})
        item_name = item_data.get("name", "item")

    # 1. Check Hands
    if player.worn_items.get("mainhand") is None:
        player.worn_items["mainhand"] = item
        player.send_message(f"{keeper_name} takes your silver and hands you {item_name}.")
        verb.world.broadcast_to_room(room, f"{keeper_name} hands {item_name} to {player.name}.", exclude=[player.name])
        return

    if player.worn_items.get("offhand") is None:
        player.worn_items["offhand"] = item
        player.send_message(f"{keeper_name} takes your silver and hands you {item_name}.")
        verb.world.broadcast_to_room(room, f"{keeper_name} hands {item_name} to {player.name}.", exclude=[player.name])
        return

    # 2. Hands Full - Bag Logic
    # Retrieve flavor text based on the shopkeeper's name
    flavor = get_shop_flavor(keeper_name)
    
    # Format strings
    bag_name = flavor.get("bag_name", "{player}'s bag").format(player=player.name)
    bag_desc = flavor.get("bag_desc", "A bag for {player}.").format(player=player.name)
    emote_tmpl = flavor.get("bagging_emote", "{npc} puts {item} in a bag.")
    
    # Create the bag
    bag_uid = uuid.uuid4().hex
    bag = {
        "uid": bag_uid,
        "name": bag_name,
        "description": bag_desc,
        "keywords": ["bag", "shopping bag", "sack", "box", "package"],
        "item_type": "container",
        "is_container": True,
        "container_storage": {
            "in": [item]
        },
        "capacity": 50,
        "weight": 0.5,
        "max_weight": 50
    }
    
    # 3. Find Counter
    preferred_counter_key = flavor.get("counter_key", "counter")
    counter = None
    
    # Strategy A: Try specific match for preferred key (e.g. "anvil", "display case")
    for obj in room.objects:
        nm = obj.get("name", "").lower()
        kw = obj.get("keywords", [])
        if preferred_counter_key in nm or preferred_counter_key in kw:
            counter = obj
            break
            
    # Strategy B: Fallback generic match (if "counter" requested but only "display case" exists)
    if not counter:
        fallback_keywords = ["counter", "bar", "table", "desk", "case", "display", "shelf", "bench"]
        for obj in room.objects:
            kw = obj.get("keywords", [])
            nm = obj.get("name", "").lower()
            # Check if any fallback keyword is in name or keywords
            if any(k in nm or k in kw for k in fallback_keywords):
                counter = obj
                break
            
    if counter:
        if "container_storage" not in counter:
            counter["container_storage"] = {}
        if "on" not in counter["container_storage"]:
            counter["container_storage"]["on"] = []
            
        counter["container_storage"]["on"].append(bag)
        
        target_name = counter.get("name", "counter")
        
    else:
        # Strategy C: Floor (Last Resort)
        room.objects.append(bag)
        target_name = "the floor"

    # Send Emote (used for both Counter and Floor to ensure flavor is preserved)
    emote_msg = emote_tmpl.format(
        npc=keeper_name,
        player=player.name,
        item=item_name,
        bag=bag_name,
        counter=target_name # Will replace {bag} if template expects it, or just use context
    )
    
    # Some templates use {bag} for the placed object name
    emote_msg = emote_msg.replace("{bag}", bag_name)
    
    verb.world.broadcast_to_room(room, emote_msg)
    player.send_message(emote_msg)
    
    verb.world.save_room(room)

@VerbRegistry.register(["list"])
class List(BaseVerb):
    def execute(self):
        shop_data = get_shop_data(self.room)
        if not shop_data:
            if self.player.game_state == "training":
                self.player.send_message("You must 'check in' at the inn to train.")
                return
            self.player.send_message("You can't seem to shop here.")
            return

        inventory = shop_data.get("inventory", [])
        if not inventory:
            self.player.send_message("The shop has nothing for sale right now.")
            return

        self.player.send_message("--- Items for Sale ---")
        self.player.send_message("Use 'LOOK ON <CATEGORY> TABLE' to browse specific items, or 'ORDER' to see a catalog.")

        game_items = self.world.game_items
        
        seen_items = set()
        count = 0
        
        for item_ref in inventory:
            if count > 15:
                self.player.send_message("... and more (check tables or type ORDER).")
                break
            
            if isinstance(item_ref, dict):
                name = item_ref.get("name")
            else:
                name = game_items.get(item_ref, {}).get("name", "An item")
            
            if name in seen_items:
                continue
            seen_items.add(name)

            price = get_item_buy_price(item_ref, game_items, shop_data)
            self.player.send_message(f"- {name:<30} {price} silver")
            count += 1

@VerbRegistry.register(["order"])
class Order(BaseVerb):
    def execute(self):
        shop_data = get_shop_data(self.room)
        
        # 0. Handle Help
        if self.args and self.args[0].lower() == "help":
            self._show_help()
            return

        if not shop_data:
            self.player.send_message("There is no merchant here to order anything from.")
            return

        inventory = shop_data.get("inventory", [])
        game_items = self.world.game_items
        
        # 1. Show Catalog (No Args)
        if not self.args:
            self._show_catalog(shop_data, inventory, game_items)
            return

        # 2. Parse Arguments
        target_index = -1
        quantity = 1
        
        args_str = " ".join(self.args).lower()
        
        # Check for "X of Y" pattern
        if " of " in args_str:
            parts = args_str.split(" of ")
            if len(parts) >= 2 and parts[0].strip().isdigit() and parts[1].strip().split()[0].isdigit():
                try:
                    quantity = int(parts[0].strip())
                    target_index = int(parts[1].strip().split()[0])
                except ValueError:
                    self.player.send_message("Usage: ORDER <quantity> OF <item number>")
                    return
        elif self.args[0].isdigit():
            target_index = int(self.args[0])
            if len(self.args) == 1:
                self._show_item_info(target_index, inventory, game_items, shop_data)
                return
        else:
            self.player.send_message("Usage: ORDER <#> or ORDER <qty> OF <#>. Type ORDER HELP for details.")
            return

        # 3. Execute Order (Purchase)
        idx = target_index - 1
        if idx < 0 or idx >= len(inventory):
            self.player.send_message(f"Item #{target_index} is not in the catalog.")
            return
            
        item_ref = inventory[idx]
        self._perform_purchase(item_ref, quantity, game_items, shop_data, idx)

    def _show_help(self):
        msg = """
ORDER displays the shop catalog.
ORDER #           = Get info and price about an item.
ORDER # of #      = Order a quantity of an item.

ORDER # COLOR {colorname}        = Order an item and have it dyed.
ORDER # MATERIAL {materialname} = Order an item made from custom material.

All above options may be combined into a single command. Example:
ORDER 5 of 3 COLOR red MATERIAL glaes

You can APPRAISE, INSPECT or DESCRIBE any item by number.
        """
        self.player.send_message(msg.strip())

    def _show_catalog(self, shop_data, inventory, game_items):
        shop_name = shop_data.get("name", "The Shop")
        keeper_name = shop_data.get("keeper_name", "The Shopkeeper")
        
        self.player.send_message(f"Welcome to {shop_name}!")
        self.player.send_message(f"{keeper_name} offers his catalog to browse.")
        self.player.send_message(f"{keeper_name} exclaims, \"Greetings stranger, have a look around!\"")
        self.player.send_message("")
        self.player.send_message("   Catalog")
        self.player.send_message("   " + "-" * 70)

        # Basic columnar layout (2 columns)
        col_width = 38
        lines = []
        for i, item_ref in enumerate(inventory):
            if isinstance(item_ref, dict):
                name = item_ref.get("name")
            else:
                name = game_items.get(item_ref, {}).get("name", "An item")
            
            entry = f"{i+1}. {name}"
            
            if i % 2 == 0:
                lines.append([entry])
            else:
                lines[-1].append(entry)
        
        for row in lines:
            line_str = ""
            for col in row:
                line_str += f"{col:<{col_width}}"
            self.player.send_message("   " + line_str)
            
        self.player.send_message("")
        self.player.send_message("You can APPRAISE, INSPECT or DESCRIBE any item by number, ORDER by number to get pricing")
        self.player.send_message("and customization options, or ORDER HELP for more info.")

    def _show_item_info(self, target_index, inventory, game_items, shop_data):
        idx = target_index - 1
        if idx < 0 or idx >= len(inventory):
            self.player.send_message(f"Item #{target_index} is not in the catalog.")
            return

        item_ref = inventory[idx]
        if isinstance(item_ref, dict):
            item_data = item_ref
        else:
            item_data = game_items.get(item_ref, {})

        name = item_data.get("name", "Item")
        price = get_item_buy_price(item_ref, game_items, shop_data)
        desc = item_data.get("description", "No description available.")
        
        self.player.send_message(f"--- Item #{target_index}: {name} ---")
        self.player.send_message(f"Price: {price} silver")
        self.player.send_message(f"Description: {desc}")
        self.player.send_message(f"(Type 'ORDER 1 OF {target_index}' to buy)")

    def _perform_purchase(self, item_ref, quantity, game_items, shop_data, inventory_idx):
        if quantity > 1:
            self.player.send_message("You can only order 1 of that item at a time from this shop.")
            return

        price_per_unit = get_item_buy_price(item_ref, game_items, shop_data)
        total_cost = price_per_unit * quantity
        
        player_silver = self.player.wealth.get("silvers", 0)

        if player_silver < total_cost:
            self.player.send_message(f"You can't afford that. It costs {total_cost} silver for {quantity}, and you have {player_silver}.")
            return

        # Deduct Money
        self.player.wealth["silvers"] = player_silver - total_cost

        # Create Items & Deliver via new Helper
        for _ in range(quantity):
            if isinstance(item_ref, dict):
                new_item = copy.deepcopy(item_ref)
                new_item["uid"] = uuid.uuid4().hex
                deliver_purchase(self, new_item, shop_data)
            else:
                deliver_purchase(self, item_ref, shop_data)

        # Update Stats
        if isinstance(item_ref, dict):
            id_data = item_ref
        else:
            id_data = game_items.get(item_ref, {})
        itype = get_item_type(id_data)
        if "sold_counts" not in shop_data:
            shop_data["sold_counts"] = {}
        shop_data["sold_counts"][itype] = shop_data["sold_counts"].get(itype, 0) + 1
        
        sync_shop_data_to_storage(self.room, shop_data)
        self.world.save_room(self.room)


@VerbRegistry.register(["buy"])
class Buy(BaseVerb):
    def execute(self):
        shop_data = get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("What do you want to buy?")
            return

        # Check if arg is a number (Alias to Order # logic)
        if self.args[0].isdigit():
            idx = int(self.args[0]) - 1
            inventory = shop_data.get("inventory", [])
            game_items = self.world.game_items
            
            if idx < 0 or idx >= len(inventory):
                self.player.send_message(f"Item #{self.args[0]} is not in the catalog.")
                return
            
            # Use Order logic to buy from catalog (infinite)
            self._buy_from_catalog_by_index(idx, inventory, game_items, shop_data)
            return

        # --- Standard Name-based Buy ---
        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items
        
        item_to_buy = None
        item_index = -1
        is_dynamic_item = False
        source_container_view = None

        # 1. Search Catalog (Inventory)
        for idx, item_ref in enumerate(shop_data.get("inventory", [])):
            if isinstance(item_ref, dict):
                item_data = item_ref
            else:
                item_data = game_items.get(item_ref)

            if item_data:
                if (target_name == item_data.get("name", "").lower() or
                        target_name in item_data.get("keywords", [])):
                    item_to_buy = item_ref
                    item_index = idx
                    break
        
        # 2. Search Dynamic Displays (Limited Stock)
        if not item_to_buy:
            for obj in self.room.objects:
                if obj.get("is_dynamic_display"):
                    storage = obj.get("container_storage", {}).get("in", [])
                    for i, item_ref in enumerate(storage):
                        if isinstance(item_ref, dict):
                            item_data = item_ref
                        else:
                            item_data = game_items.get(item_ref, {})
                        
                        if item_data:
                            if (target_name == item_data.get("name", "").lower() or
                                    target_name in item_data.get("keywords", [])):
                                item_to_buy = item_ref
                                item_index = i
                                is_dynamic_item = True
                                source_container_view = obj
                                break
                    if item_to_buy:
                        break

        if not item_to_buy:
            self.player.send_message("That item is not for sale here.")
            return

        # 3. Calculate Price & Transact
        price = get_item_buy_price(item_to_buy, game_items, shop_data)
        player_silver = self.player.wealth.get("silvers", 0)

        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver and you have {player_silver}.")
            return

        self.player.wealth["silvers"] = player_silver - price

        # Give Item to Player via helper
        if isinstance(item_to_buy, dict):
            if is_dynamic_item:
                new_item = item_to_buy 
            else:
                new_item = copy.deepcopy(item_to_buy)
                new_item["uid"] = uuid.uuid4().hex
            
            deliver_purchase(self, new_item, shop_data)
        else:
            deliver_purchase(self, item_to_buy, shop_data)

        # Remove from Source
        if is_dynamic_item and source_container_view:
            source_container_view["container_storage"]["in"].pop(item_index)
            
            if "objects" in self.room.data:
                for stub in self.room.data["objects"]:
                    matched = False
                    if stub.get("uid") and stub["uid"] == source_container_view.get("uid"):
                        matched = True
                    elif stub.get("restock_id") and stub["restock_id"] == source_container_view.get("restock_id"):
                        matched = True
                        
                    if matched:
                        if "container_storage" in stub and "in" in stub["container_storage"]:
                            if item_index < len(stub["container_storage"]["in"]):
                                stub["container_storage"]["in"].pop(item_index)
                        break
            
            self.world.save_room(self.room)
        else:
            # Catalog buy - usually infinite
            if isinstance(item_to_buy, dict):
                item_data = item_to_buy
            else:
                item_data = game_items.get(item_to_buy, {})
            itype = get_item_type(item_data)
            if "sold_counts" in shop_data:
                if itype in shop_data["sold_counts"] and shop_data["sold_counts"][itype] > 0:
                    shop_data["sold_counts"][itype] -= 1
            
            sync_shop_data_to_storage(self.room, shop_data)
            self.world.save_room(self.room)

    def _buy_from_catalog_by_index(self, idx, inventory, game_items, shop_data):
        item_to_buy = inventory[idx]
        price = get_item_buy_price(item_to_buy, game_items, shop_data)
        player_silver = self.player.wealth.get("silvers", 0)

        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver.")
            return

        self.player.wealth["silvers"] = player_silver - price
        
        if isinstance(item_to_buy, dict):
            new_item = copy.deepcopy(item_to_buy)
            new_item["uid"] = uuid.uuid4().hex
            deliver_purchase(self, new_item, shop_data)
        else:
            deliver_purchase(self, item_to_buy, shop_data)
            
        sync_shop_data_to_storage(self.room, shop_data)
        self.world.save_room(self.room)