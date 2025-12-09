# mud_backend/verbs/item_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import db
from typing import Dict, Any, Union, Tuple, Optional
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.shop import _get_shop_data, _get_item_buy_price
import time
import uuid

def _get_item_data(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(item_ref, dict): return item_ref
    return game_items_data.get(item_ref, {})

def _find_item_in_room(room_objects: list, target_name: str) -> Dict[str, Any] | None:
    matches = []
    for obj in room_objects:
        if not obj.get("is_item"): continue
        if (target_name == obj.get("name", "").lower() or target_name in obj.get("keywords", [])):
            matches.append(obj)
    return matches[0] if matches else None

def _find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> Union[str, Dict[str, Any], None]:
    for item in player.inventory:
        item_data = _get_item_data(item, game_items_data)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or target_name in item_data.get("keywords", [])):
                return item
    return None

def _find_item_in_hands(player, game_items_data: Dict[str, Any], target_name: str) -> Tuple[Any, Optional[str]]:
    for slot in ["mainhand", "offhand"]:
        item_ref = player.worn_items.get(slot)
        if item_ref:
            item_data = _get_item_data(item_ref, game_items_data)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or target_name in item_data.get("keywords", [])):
                    return item_ref, slot
    return None, None

def _find_item_worn(player, target_name: str) -> Tuple[str | None, str | None]:
    """Returns (item_id, slot_name) if found worn."""
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = _get_item_data(item_id, player.world.game_items)
            if item_data:
                if (target_name == item_data.get("name", "").lower() or target_name in item_data.get("keywords", [])):
                    return item_id, slot
    return None, None

def _find_container_on_player(player, game_items_data: Dict[str, Any], target_name: str) -> Dict[str, Any] | None:
    # Check worn items
    for slot, item in player.worn_items.items():
        if item:
            item_data = _get_item_data(item, game_items_data)
            if item_data and item_data.get("is_container"):
                item_id = item.get("uid") if isinstance(item, dict) else item
                search_keywords = item_data.get("keywords", []) + [str(item_id)]
                if (target_name == item_data.get("name", "").lower() or target_name in search_keywords):
                    item_data_with_id = item_data.copy(); item_data_with_id["_runtime_item_ref"] = item
                    return item_data_with_id
    # Check inventory (nested containers)
    for item in player.inventory:
        item_data = _get_item_data(item, game_items_data)
        if item_data and item_data.get("is_container"):
             item_id = item.get("uid") if isinstance(item, dict) else item
             search_keywords = item_data.get("keywords", []) + [str(item_id)]
             if (target_name == item_data.get("name", "").lower() or target_name in search_keywords):
                item_data_with_id = item_data.copy(); item_data_with_id["_runtime_item_ref"] = item
                return item_data_with_id
    return None

@VerbRegistry.register(["get", "take"])
class Get(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Get what?")
            return

        args_str = " ".join(self.args).lower()
        
        # --- GET FROM LOCKER ---
        if "from locker" in args_str or "from vault" in args_str:
            if "vault" not in self.room.name.lower() and "locker" not in self.room.name.lower():
                 self.player.send_message("You must be at the Town Hall Vaults to access your locker.")
                 return
            
            target = args_str.replace("from locker", "").replace("from vault", "").strip()
            if target.startswith("get "): target = target[4:].strip()
            if target.startswith("take "): target = target[5:].strip()

            locker = self.player.locker
            found_item = None
            found_idx = -1
            
            for i, item in enumerate(locker["items"]):
                if target in item["name"].lower() or target in item.get("keywords", []):
                    found_item = item
                    found_idx = i
                    break
            
            if not found_item:
                self.player.send_message("You don't see that in your locker.")
                return
            
            # Weight Check
            weight = found_item.get("weight", 1)
            if self.player.current_encumbrance + weight > self.player.max_carry_weight:
                self.player.send_message("That is too heavy for you to carry right now.")
                return
                
            locker["items"].pop(found_idx)
            self.player.inventory.append(found_item) 
            db.update_player_locker(self.player.name, locker)
            self.player.send_message(f"You get {found_item['name']} from your locker.")
            return
        # ----------------------------

        target_item_name = args_str
        target_container_name = None

        if " from " in args_str:
            parts = args_str.split(" from ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
            if target_container_name.startswith("my "):
                target_container_name = target_container_name[3:].strip()

        # Determine hand
        target_hand_slot = None
        right_hand_slot = "mainhand"
        left_hand_slot = "offhand"
        if self.player.worn_items.get(right_hand_slot) is None: target_hand_slot = right_hand_slot
        elif self.player.worn_items.get(left_hand_slot) is None: target_hand_slot = left_hand_slot

        game_items = self.world.game_items

        # --- GET FROM CONTAINER ---
        if target_container_name:
            # First check if target_container_name is a TABLE in the room
            table_obj = None
            for obj in self.room.objects:
                if "table" in obj.get("keywords", []) and (target_container_name in obj.get("keywords", []) or target_container_name == obj.get("name", "").lower()):
                    table_obj = obj
                    break
            
            if table_obj:
                # Pawnshop Table Logic: Check shop inventory
                shop_data = _get_shop_data(self.room)
                if not shop_data:
                    self.player.send_message("You find nothing of interest on the table.")
                    return
                
                # Search shop inventory for item
                found_item_ref = None
                for item_ref in shop_data.get("inventory", []):
                    item_data = _get_item_data(item_ref, game_items)
                    if item_data:
                         if (target_item_name == item_data.get("name", "").lower() or target_item_name in item_data.get("keywords", [])):
                             found_item_ref = item_ref
                             break
                
                if found_item_ref:
                    price = _get_item_buy_price(found_item_ref, game_items, shop_data)
                    item_name = _get_item_data(found_item_ref, game_items).get("name", "that")
                    self.player.send_message(f"The pawnbroker notices your interest. 'That {item_name} will cost you {price} silvers.'")
                    return
                else:
                    self.player.send_message(f"You don't see a '{target_item_name}' on the {table_obj['name']}.")
                    return

            # Normal Container Logic
            container_data = _find_container_on_player(self.player, game_items, target_container_name)
            if not container_data:
                self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                return
            
            if container_data.get("wearable_slot") != "back" and "hand" not in str(container_data.get("_runtime_item_ref")):
                pass # Strict check bypass for now

            item_ref = _find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref:
                self.player.send_message(f"You don't have a {target_item_name} in your {container_data.get('name')}.")
                return
            
            item_data = _get_item_data(item_ref, game_items)
            item_name = item_data.get("name", "an item")

            if not target_hand_slot:
                self.player.send_message("Your hands are full. You must free a hand to get that.")
                return
                
            self.player.inventory.remove(item_ref)
            self.player.worn_items[target_hand_slot] = item_ref
            self.player.send_message(f"You get {item_name} from your {container_data.get('name')} and hold it.")
            _set_action_roundtime(self.player, 1.0)
            
        # --- GET FROM GROUND / SHOP DISPLAY ---
        else:
            # Check Room Objects
            item_obj = _find_item_in_room(self.room.objects, target_item_name)
            
            if item_obj:
                if item_obj.get("dynamic") or "temp" in item_obj or "quality" in item_obj:
                     item_to_pickup = item_obj 
                     item_name = item_obj.get("name", "an item")
                else:
                     item_to_pickup = item_obj.get("item_id")
                     item_name = item_obj.get("name", "an item")
                
                if not item_to_pickup and item_obj.get("item_id"):
                     item_to_pickup = item_obj.get("item_id")
                
                if not item_to_pickup and item_obj.get("is_item"):
                    item_to_pickup = item_obj

                if not item_to_pickup:
                    self.player.send_message(f"You can't seem to pick up the {item_name}.")
                    return

                if not target_hand_slot:
                     self.player.inventory.append(item_to_pickup)
                     self.player.send_message(f"Both hands are full. You get {item_name} and put it in your pack.")
                else:
                     self.player.worn_items[target_hand_slot] = item_to_pickup
                     self.player.send_message(f"You get {item_name} and hold it.")
                
                self.room.objects.remove(item_obj)
                self.world.save_room(self.room)
                return

            # --- Check Shop Inventory (Implicit Table Check) ---
            shop_data = _get_shop_data(self.room)
            if shop_data:
                for item_ref in shop_data.get("inventory", []):
                    item_data = _get_item_data(item_ref, game_items)
                    if item_data:
                         if (target_item_name == item_data.get("name", "").lower() or target_item_name in item_data.get("keywords", [])):
                             price = _get_item_buy_price(item_ref, game_items, shop_data)
                             self.player.send_message(f"The pawnbroker notices your interest. 'That {item_data.get('name')} will cost you {price} silvers.'")
                             return

            # --- GET FROM INVENTORY (Auto-wield/Unstow) ---
            item_ref_from_pack = _find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here or in your pack.")
                return

            if not target_hand_slot:
                self.player.send_message("Your hands are full.")
                return

            self.player.inventory.remove(item_ref_from_pack)
            self.player.worn_items[target_hand_slot] = item_ref_from_pack
            
            item_data = _get_item_data(item_ref_from_pack, game_items)
            item_name = item_data.get("name", "an item")
            
            self.player.send_message(f"You get {item_name} from your pack and hold it.")
            _set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["put", "drop", "discard"])
class Put(BaseVerb):
    """
    Handles PUT <item> IN <container> and DROP <item>.
    Includes TRASH logic for pawnshops.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        
        if not self.args:
            self.player.send_message("Put what where?")
            return
            
        args_str = " ".join(self.args).lower()
        
        # Parse: PUT item IN container
        target_item_name = args_str
        target_container_name = None
        
        if " in " in args_str:
            parts = args_str.split(" in ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
        elif self.command_root in ["drop", "discard"]:
            # Just dropping on ground?
            # Or dropping in a specific bin if args provided?
            if " in " in args_str:
                # Handle "drop item in bin" same as put
                parts = args_str.split(" in ", 1)
                target_item_name = parts[0].strip()
                target_container_name = parts[1].strip()
            else:
                # Actual drop on ground
                # TODO: Implement ground drop if desired, for now only Trash logic is requested
                # For safety, let's implement Drop logic similar to Get but reversed
                pass 
        
        # Find Item (Hands preferred)
        game_items = self.world.game_items
        item_ref, hand_slot = _find_item_in_hands(self.player, game_items, target_item_name)
        
        if not item_ref:
            self.player.send_message(f"You aren't holding a '{target_item_name}'.")
            return
            
        item_data = _get_item_data(item_ref, game_items)
        item_name = item_data.get("name", "the item")
        
        # If Drop/Discard without container
        if not target_container_name and self.command_root in ["drop", "discard"]:
            # Drop to room
            self.player.worn_items[hand_slot] = None
            
            # Construct room object
            if isinstance(item_ref, dict):
                obj = item_ref
                obj["is_item"] = True
            else:
                obj = {"item_id": item_ref, "name": item_name, "is_item": True, "keywords": item_data.get("keywords", [])}
                
            self.room.objects.append(obj)
            self.player.send_message(f"You drop {item_name} on the ground.")
            self.world.save_room(self.room)
            return

        if not target_container_name:
            self.player.send_message("Put it in what?")
            return
            
        # Find Container in Room (Trash Bins, Barrels, etc.)
        container_obj = None
        for obj in self.room.objects:
             if (target_container_name == obj.get("name", "").lower() or target_container_name in obj.get("keywords", [])):
                 container_obj = obj
                 break
        
        if container_obj:
            # Check for Trash keywords or flag
            trash_keywords = ["bin", "trash", "barrel", "crate", "urn", "coffin", "case"]
            is_trash = False
            for k in trash_keywords:
                if k in container_obj.get("keywords", []):
                    is_trash = True
                    break
            
            if is_trash:
                # Destroy Item
                self.player.worn_items[hand_slot] = None
                self.player.send_message(f"You discard {item_name} into the {container_obj['name']}.")
                _set_action_roundtime(self.player, 1.0)
                return
            else:
                self.player.send_message(f"You can't put things in the {container_obj['name']}.")
                return
        
        self.player.send_message(f"You don't see a {target_container_name} here.")