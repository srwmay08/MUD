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
        self.player.send_message("Use 'LOOK ON <CATEGORY> TABLE' to browse specific items.")

        game_items = self.world.game_items
        
        seen_items = set()
        count = 0
        
        for item_ref in inventory:
            if count > 15:
                self.player.send_message("... and more (check tables).")
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

@VerbRegistry.register(["buy", "order"])
class Buy(BaseVerb):
    def execute(self):
        shop_data = get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("What do you want to buy?")
            return

        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items

        item_to_buy = None
        item_index = -1

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

        if not item_to_buy:
            self.player.send_message("That item is not for sale here.")
            return

        price = get_item_buy_price(item_to_buy, game_items, shop_data)
        player_silver = self.player.wealth.get("silvers", 0)

        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver and you have {player_silver}.")
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

        shop_data["inventory"].pop(item_index)

        # Reduce sold count
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