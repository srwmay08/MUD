# mud_backend/verbs/item_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import db
from typing import Dict, Any, Union, Tuple, Optional
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.shop import _get_shop_data, _get_item_buy_price
import time
import uuid

def _clean_name(name: str) -> str:
    """Helper to strip articles from names."""
    name = name.strip()
    if name.startswith("my "): name = name[3:].strip()
    if name.startswith("the "): name = name[4:].strip()
    if name.startswith("a "): name = name[2:].strip()
    if name.startswith("an "): name = name[3:].strip()
    return name

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

def _find_item_in_obj_storage(obj, target_item_name, game_items, specific_prep=None):
    """
    Searches for an item inside an object's 'container_storage'.
    Returns (item_ref, found_prep, index)
    """
    storage = obj.get("container_storage", {})
    
    # Define which prepositions to search
    preps_to_check = [specific_prep] if specific_prep else storage.keys()
    
    for prep in preps_to_check:
        items_list = storage.get(prep, [])
        for i, item_ref in enumerate(items_list):
            item_data = _get_item_data(item_ref, game_items)
            if item_data:
                if (target_item_name == item_data.get("name", "").lower() or 
                    target_item_name in item_data.get("keywords", [])):
                    return item_ref, prep, i
    return None, None, -1

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
        target_prep = None

        if " from " in args_str:
            parts = args_str.split(" from ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
            
            # Check for preposition in container name (e.g. "from under bed")
            # Order matters (longer first)
            prepositions = ["inside", "into", "under", "behind", "beneath", "in", "on"]
            for prep in prepositions:
                if target_container_name.startswith(f"{prep} "):
                    target_prep = prep
                    target_container_name = target_container_name[len(prep)+1:].strip()
                    break
        
        # --- FIX: Clean names ---
        if target_item_name: target_item_name = _clean_name(target_item_name)
        if target_container_name: target_container_name = _clean_name(target_container_name)
        # ------------------------

        # Determine hand
        target_hand_slot = None
        right_hand_slot = "mainhand"
        left_hand_slot = "offhand"
        if self.player.worn_items.get(right_hand_slot) is None: target_hand_slot = right_hand_slot
        elif self.player.worn_items.get(left_hand_slot) is None: target_hand_slot = left_hand_slot

        game_items = self.world.game_items

        # --- GET FROM CONTAINER / OBJECT ---
        if target_container_name:
            # 1. Check Room Objects (Tables, Beds, etc.)
            container_obj = None
            for obj in self.room.objects:
                if (target_container_name == obj.get("name", "").lower() or 
                    target_container_name in obj.get("keywords", [])):
                    container_obj = obj
                    break
            
            if container_obj:
                # A) Check Shop Inventory (Tables)
                if "table" in container_obj.get("keywords", []):
                    shop_data = _get_shop_data(self.room)
                    if shop_data:
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

                # B) Check Container Storage (User placed items: On/Under/In/Behind)
                item_ref, found_prep, idx = _find_item_in_obj_storage(
                    container_obj, target_item_name, game_items, specific_prep=target_prep
                )
                
                if item_ref:
                    # Found it!
                    if not target_hand_slot:
                        self.player.send_message("Your hands are full. You must free a hand to get that.")
                        return

                    # Remove from storage
                    container_obj["container_storage"][found_prep].pop(idx)
                    # If list empty, cleanup key? Optional.
                    
                    # Add to hand
                    self.player.worn_items[target_hand_slot] = item_ref
                    
                    item_data = _get_item_data(item_ref, game_items)
                    self.player.send_message(f"You get {item_data.get('name', 'item')} from {found_prep} the {container_obj['name']}.")
                    self.world.save_room(self.room)
                    _set_action_roundtime(self.player, 1.0)
                    return

                # C) Fallback message
                loc_str = f"{target_prep} " if target_prep else "on/in "
                self.player.send_message(f"You don't see a '{target_item_name}' {loc_str}the {container_obj['name']}.")
                return

            # 2. Check Player Containers (Backpacks)
            container_data = _find_container_on_player(self.player, game_items, target_container_name)
            if not container_data:
                self.player.send_message(f"You don't have a container called '{target_container_name}' and don't see one here.")
                return
            
            # Strict back slot check (optional, kept from original)
            if container_data.get("wearable_slot") != "back" and "hand" not in str(container_data.get("_runtime_item_ref")):
                pass 

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
            # Check Room Objects (Floor)
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

            # Check Shop Inventory (Implicit)
            shop_data = _get_shop_data(self.room)
            if shop_data:
                for item_ref in shop_data.get("inventory", []):
                    item_data = _get_item_data(item_ref, game_items)
                    if item_data:
                         if (target_item_name == item_data.get("name", "").lower() or target_item_name in item_data.get("keywords", [])):
                             price = _get_item_buy_price(item_ref, game_items, shop_data)
                             self.player.send_message(f"The pawnbroker notices your interest. 'That {item_data.get('name')} will cost you {price} silvers.'")
                             return

            # Check Inventory (Unstow)
            item_ref_from_pack = _find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here, in your pack, or in a visible container.")
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
    Handles PUT/DROP logic.
    Supports putting items IN/ON/UNDER/BEHIND/BENEATH objects if they support it via LOOK interactions.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        
        if not self.args:
            self.player.send_message("Put what where?")
            return
            
        args_str = " ".join(self.args).lower()
        
        prepositions = ["inside", "into", "under", "behind", "beneath", "in", "on"]
        
        target_item_name = args_str
        target_container_name = None
        target_prep = None
        
        # 1. Parse Prepositions
        for prep in prepositions:
            # Look for " <prep> " with spaces to avoid partial matches
            check_str = f" {prep} "
            if check_str in args_str:
                parts = args_str.split(check_str, 1)
                target_item_name = parts[0].strip()
                target_container_name = parts[1].strip()
                target_prep = prep
                break
        
        # Default for DROP/DISCARD if no prep found
        if not target_container_name and self.command_root in ["drop", "discard"]:
            pass # Will fall through to drop logic
        elif not target_container_name:
            self.player.send_message("Put it where? (e.g., PUT DAGGER IN CHEST, PUT COIN ON TABLE)")
            return
        
        # --- FIX: Clean names ---
        if target_item_name: target_item_name = _clean_name(target_item_name)
        if target_container_name: target_container_name = _clean_name(target_container_name)
        # ------------------------

        # 2. Find Item in Hands
        game_items = self.world.game_items
        item_ref, hand_slot = _find_item_in_hands(self.player, game_items, target_item_name)
        
        if not item_ref:
            self.player.send_message(f"You aren't holding a '{target_item_name}'.")
            return
            
        item_data = _get_item_data(item_ref, game_items)
        item_name = item_data.get("name", "the item")
        
        # 3. Handle Ground Drop (No container)
        if not target_container_name and self.command_root in ["drop", "discard"]:
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

        # 4. Find Target Object
        container_obj = None
        for obj in self.room.objects:
             if (target_container_name == obj.get("name", "").lower() or 
                 target_container_name in obj.get("keywords", [])):
                 container_obj = obj
                 break
        
        if not container_obj:
            # Optional: Check player containers? (Not implemented in this step, focusing on Room Objects)
            self.player.send_message(f"You don't see a {target_container_name} here.")
            return

        # 5. Check Trash (Special case)
        trash_keywords = ["bin", "trash", "barrel", "crate", "urn", "coffin", "case"]
        is_trash = any(k in container_obj.get("keywords", []) for k in trash_keywords)
        
        if is_trash and target_prep in [None, "in", "inside", "into"]:
            self.player.worn_items[hand_slot] = None
            self.player.send_message(f"You discard {item_name} into the {container_obj['name']}.")
            _set_action_roundtime(self.player, 1.0)
            return

        # 6. Validate Placement Support (Interactions)
        # normalize prep
        if target_prep in ["inside", "into"]: target_prep = "in"
        
        # We need to verify if the object supports "LOOK <PREP>"
        # Interactions keys are usually stored as "look <prep>"
        # or we check keyword properties (e.g. tables implicitly support "on")
        
        supported = False
        
        # Check explicit interactions
        interactions = container_obj.get("interactions", {})
        look_key = f"look {target_prep}"
        if look_key in interactions:
            supported = True
            
        # Check implicit support (Tables)
        if not supported and target_prep == "on":
            if "table" in container_obj.get("keywords", []) or container_obj.get("is_table"):
                supported = True
        
        # Check implicit support (Containers)
        if not supported and target_prep == "in":
            if container_obj.get("is_container"):
                supported = True

        if not supported:
            self.player.send_message(f"You can't put things {target_prep} the {container_obj['name']}.")
            return

        # 7. Execute Placement
        self.player.worn_items[hand_slot] = None
        
        # Convert item ref to full dict if needed for storage to persist properties
        if isinstance(item_ref, str):
            # It's an ID, verify if we should convert to dict instance or keep ref
            # For simplicity, we keep it as is. Room storage handles mixed types.
            item_to_store = item_ref
        else:
            item_to_store = item_ref
            
        # Initialize storage if missing
        if "container_storage" not in container_obj:
            container_obj["container_storage"] = {}
            
        if target_prep not in container_obj["container_storage"]:
            container_obj["container_storage"][target_prep] = []
            
        container_obj["container_storage"][target_prep].append(item_to_store)
        
        self.player.send_message(f"You put {item_name} {target_prep} the {container_obj['name']}.")
        self.world.save_room(self.room)
        _set_action_roundtime(self.player, 0.5)