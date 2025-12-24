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
        # Patterns: 
        # ORDER #
        # ORDER # of #
        
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
            # If they just typed "ORDER 1", we show info. 
            if len(self.args) == 1:
                self._show_item_info(target_index, inventory, game_items, shop_data)
                return
        else:
            self.player.send_message("Usage: ORDER <#> or ORDER <qty> OF <#>. Type ORDER HELP for details.")
            return

        # 3. Execute Order (Purchase)
        # Adjust index to 0-based
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
        price_per_unit = get_item_buy_price(item_ref, game_items, shop_data)
        total_cost = price_per_unit * quantity
        
        player_silver = self.player.wealth.get("silvers", 0)

        if player_silver < total_cost:
            self.player.send_message(f"You can't afford that. It costs {total_cost} silver for {quantity}, and you have {player_silver}.")
            return

        # Deduct Money
        self.player.wealth["silvers"] = player_silver - total_cost

        # Create Items
        item_name = ""
        for _ in range(quantity):
            if isinstance(item_ref, dict):
                new_item = copy.deepcopy(item_ref)
                new_item["uid"] = uuid.uuid4().hex
                self.player.inventory.append(new_item)
                item_name = new_item.get("name")
            else:
                self.player.inventory.append(item_ref)
                item_name = game_items.get(item_ref, {}).get("name", "the item")

        # Handle Shop Inventory (Limited Stock Logic)
        if quantity > 1:
            self.player.send_message("You can only order 1 of that item at a time from this shop.")
            # Refund
            self.player.wealth["silvers"] += total_cost
            return
        
        # Only remove from stock if it's a unique pawn item. 
        # Standard catalogs are infinite unless defined otherwise.
        # Assuming simple pawn shop behavior for now based on previous code.
        shop_data["inventory"].pop(inventory_idx)

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

        self.player.send_message(f"You buy {item_name} for {total_cost} silver.")


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
                self.player.inventory.append(new_item)
                name = new_item.get("name")
            else:
                self.player.inventory.append(item_to_buy)
                name = game_items.get(item_to_buy, {}).get("name", "the item")

            shop_data["inventory"].pop(idx)
            sync_shop_data_to_storage(self.room, shop_data)
            self.world.save_room(self.room)
            self.player.send_message(f"You buy {name} for {price} silver.")
            return

        # --- Standard Name-based Buy ---
        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items
        
        item_to_buy = None
        item_index = -1
        is_dynamic_item = False
        source_container = None

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
                                source_container = obj
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

        # Give Item to Player
        if isinstance(item_to_buy, dict):
            # If dynamic, it likely already has a unique ID, but if it's from catalog, it needs one.
            # If from dynamic container, we MOVE the item, we don't copy it (it's limited).
            if is_dynamic_item:
                new_item = item_to_buy
            else:
                new_item = copy.deepcopy(item_to_buy)
                new_item["uid"] = uuid.uuid4().hex
            
            self.player.inventory.append(new_item)
            name = new_item.get("name")
        else:
            self.player.inventory.append(item_to_buy)
            name = game_items.get(item_to_buy, {}).get("name", "the item")

        # Remove from Source
        if is_dynamic_item and source_container:
            source_container["container_storage"]["in"].pop(item_index)
            # Save room to persist removal from container
            self.world.save_room(self.room)
        else:
            # Remove from Catalog
            shop_data["inventory"].pop(item_index)
            
            # Update Sold Counts (Only for catalog sales usually, but tracking all is fine)
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

        self.player.send_message(f"You buy {name} for {price} silver.")

@VerbRegistry.register(["appraise"])
class Appraise(BaseVerb):
    def execute(self):
        shop_data = get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("Appraise what?")
            return

        # Check for numeric catalog appraisal
        if self.args[0].isdigit():
            idx = int(self.args[0]) - 1
            inventory = shop_data.get("inventory", [])
            game_items = self.world.game_items
            
            if idx < 0 or idx >= len(inventory):
                self.player.send_message(f"Item #{self.args[0]} is not in the catalog.")
                return
            
            item_ref = inventory[idx]
            price = get_item_buy_price(item_ref, game_items, shop_data)
            if isinstance(item_ref, dict):
                name = item_ref.get("name")
            else:
                name = game_items.get(item_ref, {}).get("name", "Item")
            
            self.player.send_message(f"The shopkeeper says, 'That {name} costs {price} silver.'")
            return

        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items

        item_ref, loc = find_item_in_hands(self.player, game_items, target_name)
        if not item_ref:
            item_ref = find_item_in_inventory(self.player, game_items, target_name)

        if item_ref:
            price = get_item_sell_price(item_ref, game_items, shop_data)
            name = ""
            if isinstance(item_ref, dict):
                name = item_ref.get("name")
            else:
                name = game_items.get(item_ref, {}).get("name")

            self.player.send_message(f"The pawnbroker glances at your {name}. 'I'd give you {price} silver for that.'")
            return

        for item_ref in shop_data.get("inventory", []):
            if isinstance(item_ref, dict):
                t_data = item_ref
            else:
                t_data = game_items.get(item_ref)

            if t_data and (target_name == t_data.get("name", "").lower() or target_name in t_data.get("keywords", [])):
                price = get_item_buy_price(item_ref, game_items, shop_data)
                self.player.send_message(f"The pawnbroker says, 'That {t_data['name']} is worth {price} silver.'")
                return

        self.player.send_message(f"You don't have or see a '{target_name}'.")

@VerbRegistry.register(["sell"])
class Sell(BaseVerb):
    def execute(self):
        shop_data = get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("What do you want to sell?")
            return

        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items

        item_ref, hand_slot = find_item_in_hands(self.player, game_items, target_name)
        if not item_ref:
            self.player.send_message(f"You aren't holding a '{target_name}'.")
            return

        if isinstance(item_ref, dict):
            item_uid = item_ref.get("uid")
        else:
            item_uid = item_ref

        if item_uid in self.player.flags.get("marked_items", []):
            self.player.send_message(f"You have marked that item. You cannot sell it until you UNMARK it.")
            return

        price = get_item_sell_price(item_ref, game_items, shop_data)

        if price <= 0:
            self.player.send_message("The pawnbroker shakes their head. 'Not worth my time.'")
            return

        # Prepare item for shop inventory
        if isinstance(item_ref, dict):
            new_stock = item_ref
        else:
            base_data = game_items.get(item_ref)
            if base_data:
                new_stock = base_data.copy()
                new_stock["uid"] = uuid.uuid4().hex
            else:
                new_stock = None

        if new_stock:
            # --- 1. Immediate Transaction ---
            self.player.worn_items[hand_slot] = None
            self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + price
            new_stock["sold_timestamp"] = time.time()

            self.world.send_message_to_player(
                self.player.name.lower(),
                f"The pawnbroker takes {new_stock['name']} from you and hands you {price} silver.",
                "message"
            )
            
            # Broadcast
            player_info = self.world.get_player_info(self.player.name.lower())
            skip_sids = []
            if player_info and "sid" in player_info:
                skip_sids.append(player_info["sid"])
                
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"The pawnbroker takes {new_stock['name']} from {self.player.name} and hands them some coins.", 
                "message", 
                skip_sid=skip_sids
            )

            # --- 2. Delay ---
            time.sleep(1.5)

            # --- 3. Shop Logic ---
            already_in_stock = False
            for existing_item in shop_data.get("inventory", []):
                e_name = existing_item.get("name") if isinstance(existing_item, dict) else game_items.get(existing_item, {}).get("name")
                if e_name == new_stock["name"]:
                    already_in_stock = True
                    break

            shop_data["inventory"].append(new_stock)

            # Update Counts
            itype = get_item_type(new_stock)
            if "sold_counts" not in shop_data:
                shop_data["sold_counts"] = {}
            shop_data["sold_counts"][itype] = shop_data["sold_counts"].get(itype, 0) + 1

            # --- 4. Final Action (Ambient) ---
            table_name = get_display_table_name(self.room, new_stock)
            
            if already_in_stock:
                action_msg = f"The pawnbroker checks his ledger, nods, and adds {new_stock['name']} to the stock on the {table_name}."
            else:
                action_msg = f"The pawnbroker inspects {new_stock['name']} closely, tags it, and places it on display on the {table_name}."

            self.world.broadcast_to_room(self.room.room_id, action_msg, "message")

            # --- 5. Save & Sync ---
            sync_shop_data_to_storage(self.room, shop_data)
            self.world.save_room(self.room)
        else:
            self.player.send_message("Error transferring item.")