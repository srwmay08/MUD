# mud_backend/verbs/shop.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import db
import math
import random
import time
from typing import Tuple, Optional, Dict, Any, Union
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.foraging import _set_action_roundtime
import uuid

def _find_item_in_hands(player, game_items_data: Dict[str, Any], target_name: str) -> Tuple[Optional[Any], Optional[str]]:
    for slot in ["mainhand", "offhand"]:
        item_ref = player.worn_items.get(slot)
        if item_ref:
            if isinstance(item_ref, dict):
                item_data = item_ref
            else:
                item_data = game_items_data.get(item_ref)

            if item_data:
                if (target_name == item_data.get("name", "").lower() or
                        target_name in item_data.get("keywords", [])):
                    return item_ref, slot
    return None, None

def _find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> Any | None:
    for item_ref in player.inventory:
        if isinstance(item_ref, dict):
            item_data = item_ref
        else:
            item_data = game_items_data.get(item_ref)

        if item_data:
            if (target_name == item_data.get("name", "").lower() or
                    target_name in item_data.get("keywords", [])):
                return item_ref
    return None

def _get_shop_data(room) -> dict | None:
    """Helper to get shop data from a room."""
    for obj in room.objects:
        if "shop_data" in obj:
            s_data = obj.get("shop_data")

            # Fix: Handle empty list from JSON by initializing defaults
            if isinstance(s_data, list):
                s_data = {"inventory": [], "sold_counts": {}}
                obj["shop_data"] = s_data
                return s_data

            if s_data is not None and isinstance(s_data, dict):
                # Ensure keys exist
                if "inventory" not in s_data: s_data["inventory"] = []
                if "sold_counts" not in s_data: s_data["sold_counts"] = {}
                return s_data
    return None

def _sync_shop_data_to_storage(room, updated_shop_data):
    """
    CRITICAL FIX: Syncs the modified shop_data from the live object (room.objects)
    back to the raw persistent storage (room.data['objects']).
    Without this, hydrate_room_objects() overwrites changes on the next 'look'.
    """
    # 1. Find the pawnbroker in the live objects to get their name/id
    target_name = None
    for obj in room.objects:
        if obj.get("shop_data") is updated_shop_data:
            target_name = obj.get("name")
            break
            
    if not target_name:
        return

    # 2. Find the matching stub in room.data['objects'] and update it
    raw_objects = room.data.get("objects", [])
    for stub in raw_objects:
        if stub.get("name") == target_name and "shop_data" in stub:
            stub["shop_data"] = updated_shop_data
            break

def _get_item_type(item_data: dict) -> str:
    """Helper to safely determine item type from various schema versions."""
    base_type = item_data.get("item_type") or item_data.get("type", "misc")
    
    if "weapon_type" in item_data: return "weapon"
    if "armor_type" in item_data: return "armor"
    if "spell" in item_data or "scroll" in item_data.get("keywords", []): return "magic"
    
    return base_type

def _get_supply_demand_modifier(shop_data: dict, item_type: str) -> float:
    counts = shop_data.get("sold_counts", {})
    count = counts.get(item_type, 0)
    reduction = count * 0.05
    return max(0.5, 1.0 - reduction)

def _get_item_buy_price(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any], shop_data: Optional[dict] = None) -> int:
    if isinstance(item_ref, dict):
        item_data = item_ref
    else:
        item_data = game_items_data.get(item_ref)

    if not item_data:
        return 0

    base = item_data.get("base_value", 0) * 2

    if shop_data:
        itype = _get_item_type(item_data)
        mod = _get_supply_demand_modifier(shop_data, itype)
        return int(base * mod)

    return base

def _get_item_sell_price(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any], shop_data: Optional[dict] = None) -> int:
    if isinstance(item_ref, dict):
        item_data = item_ref
    else:
        item_data = game_items_data.get(item_ref)

    if not item_data:
        return 0

    base_val = item_data.get("base_value", 0)

    if shop_data:
        itype = _get_item_type(item_data)
        mod = _get_supply_demand_modifier(shop_data, itype)
        base_val = int(base_val * mod)

    max_val = item_data.get("max_value")
    if max_val and max_val > base_val:
        return random.randint(base_val, max_val)

    return base_val

def _get_display_table_name(room, item_data) -> str:
    """Finds the name of the table appropriate for the item."""
    itype = _get_item_type(item_data)

    for obj in room.objects:
        keywords = obj.get("keywords", [])
        if "table" not in keywords: continue

        if itype == "weapon" and ("weapon" in keywords or "weapons" in keywords): return obj.get("name", "table")
        if itype == "armor" and ("armor" in keywords or "armors" in keywords): return obj.get("name", "table")
        if itype == "magic" and ("magic" in keywords or "arcane" in keywords): return obj.get("name", "table")
        if itype == "misc" and "goods" in keywords: return obj.get("name", "table")
    
    return "display table"

@VerbRegistry.register(["list"])
class List(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
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

            price = _get_item_buy_price(item_ref, game_items, shop_data)
            self.player.send_message(f"- {name:<30} {price} silver")
            count += 1

@VerbRegistry.register(["buy", "order"])
class Buy(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
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

        price = _get_item_buy_price(item_to_buy, game_items, shop_data)
        player_silver = self.player.wealth.get("silvers", 0)

        if player_silver < price:
            self.player.send_message(f"You can't afford that. It costs {price} silver and you have {player_silver}.")
            return

        self.player.wealth["silvers"] = player_silver - price

        if isinstance(item_to_buy, dict):
            import copy
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
            
        itype = _get_item_type(item_data)

        if "sold_counts" in shop_data:
            if itype in shop_data["sold_counts"] and shop_data["sold_counts"][itype] > 0:
                shop_data["sold_counts"][itype] -= 1
        
        _sync_shop_data_to_storage(self.room, shop_data)
        self.world.save_room(self.room)

        self.player.send_message(f"You buy {name} for {price} silver.")

@VerbRegistry.register(["appraise"])
class Appraise(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("Appraise what?")
            return

        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items

        item_ref, loc = _find_item_in_hands(self.player, game_items, target_name)
        if not item_ref:
            item_ref = _find_item_in_inventory(self.player, game_items, target_name)

        if item_ref:
            price = _get_item_sell_price(item_ref, game_items, shop_data)
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
                price = _get_item_buy_price(item_ref, game_items, shop_data)
                self.player.send_message(f"The pawnbroker says, 'That {t_data['name']} is worth {price} silver.'")
                return

        self.player.send_message(f"You don't have or see a '{target_name}'.")

@VerbRegistry.register(["sell"])
class Sell(BaseVerb):
    def execute(self):
        shop_data = _get_shop_data(self.room)
        if not shop_data:
            self.player.send_message("You can't seem to shop here.")
            return

        if not self.args:
            self.player.send_message("What do you want to sell?")
            return

        target_name = " ".join(self.args).lower()
        game_items = self.world.game_items

        item_ref, hand_slot = _find_item_in_hands(self.player, game_items, target_name)
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

        price = _get_item_sell_price(item_ref, game_items, shop_data)

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
            # --- 1. Immediate Transaction (No Delay, No Queue) ---
            self.player.worn_items[hand_slot] = None
            self.player.wealth["silvers"] = self.player.wealth.get("silvers", 0) + price
            new_stock["sold_timestamp"] = time.time()

            # Fix: Use direct send via world to bypass player's message queue lag
            # Updated phrasing as requested
            self.world.send_message_to_player(
                self.player.name,
                f"The pawnbroker takes {new_stock['name']} from you and hands you {price} silver.",
                "message"
            )
            
            # Broadcast to room (exclude player)
            player_info = self.world.get_player_info(self.player.name)
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
            itype = _get_item_type(new_stock)
            if "sold_counts" not in shop_data:
                shop_data["sold_counts"] = {}
            shop_data["sold_counts"][itype] = shop_data["sold_counts"].get(itype, 0) + 1

            # --- 4. Final Action (Ambient) ---
            table_name = _get_display_table_name(self.room, new_stock)
            
            if already_in_stock:
                action_msg = f"The pawnbroker checks his ledger, nods, and adds the {new_stock['name']} to the stock on the {table_name}."
            else:
                action_msg = f"The pawnbroker inspects the {new_stock['name']} closely, tags it, and places it on display on the {table_name}."

            # Broadcast to everyone (including player, as this is an ambient event)
            self.world.broadcast_to_room(self.room.room_id, action_msg, "message")

            # --- 5. Save & Sync ---
            _sync_shop_data_to_storage(self.room, shop_data)
            self.world.save_room(self.room)
        else:
            self.player.send_message("Error transferring item.")