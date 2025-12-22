# mud_backend/verbs/item_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import db
from mud_backend.core.scripting import execute_script
from typing import Dict, Any, Union, Tuple, Optional
import re

def _clean_name(name: str) -> str:
    """Helper to strip articles from names using regex."""
    if not name:
        return ""
    # Remove 'my', 'the', 'a', 'an' at the start of the string
    cleaned = re.sub(r'^(my|the|a|an)\s+', '', name.strip().lower())
    return cleaned.strip()

def _get_item_data(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(item_ref, dict):
        return item_ref
    return game_items_data.get(item_ref, {})

def _find_item_in_room(room_objects: list, target_name: str) -> Dict[str, Any] | None:
    clean_target = _clean_name(target_name)
    matches = []
    for obj in room_objects:
        if not obj.get("is_item"):
            continue
        obj_name = obj.get("name", "").lower()
        if clean_target == obj_name or clean_target == _clean_name(obj_name) or clean_target in obj.get("keywords", []):
            matches.append(obj)
    return matches[0] if matches else None

def _find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> Union[str, Dict[str, Any], None]:
    clean_target = _clean_name(target_name)
    for item in player.inventory:
        item_data = _get_item_data(item, game_items_data)
        if item_data:
            i_name = item_data.get("name", "").lower()
            if clean_target == i_name or clean_target == _clean_name(i_name) or clean_target in item_data.get("keywords", []):
                return item
    return None

def _find_item_in_hands(player, game_items_data: Dict[str, Any], target_name: str) -> Tuple[Any, Optional[str]]:
    clean_target = _clean_name(target_name)
    for slot in ["mainhand", "offhand"]:
        item_ref = player.worn_items.get(slot)
        if item_ref:
            item_data = _get_item_data(item_ref, game_items_data)
            if item_data:
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == _clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    return item_ref, slot
    return None, None

def _find_item_worn(player, target_name: str) -> Tuple[str | None, str | None]:
    clean_target = _clean_name(target_name)
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = _get_item_data(item_id, player.world.game_items)
            if item_data:
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == _clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    return item_id, slot
    return None, None

def _find_container_on_player(player, game_items_data: Dict[str, Any], target_name: str) -> Dict[str, Any] | None:
    clean_target = _clean_name(target_name)
    # Worn
    for slot, item in player.worn_items.items():
        if item:
            item_data = _get_item_data(item, game_items_data)
            if item_data and item_data.get("is_container"):
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == _clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    # Attach ref for runtime use
                    item_data_copy = item_data.copy()
                    item_data_copy["_runtime_item_ref"] = item
                    return item_data_copy
    # Inventory
    for item in player.inventory:
        item_data = _get_item_data(item, game_items_data)
        if item_data and item_data.get("is_container"):
            i_name = item_data.get("name", "").lower()
            if clean_target == i_name or clean_target == _clean_name(i_name) or clean_target in item_data.get("keywords", []):
                item_data_copy = item_data.copy()
                item_data_copy["_runtime_item_ref"] = item
                return item_data_copy
    return None

def _find_item_in_obj_storage(obj, target_item_name, game_items, specific_prep=None):
    clean_target = _clean_name(target_item_name)
    storage = obj.get("container_storage", {})
    preps_to_check = [specific_prep] if specific_prep else storage.keys()

    for prep in preps_to_check:
        items_list = storage.get(prep, [])
        for i, item_ref in enumerate(items_list):
            item_data = _get_item_data(item_ref, game_items)
            if item_data:
                i_name = item_data.get("name", "").lower()
                if clean_target == i_name or clean_target == _clean_name(i_name) or clean_target in item_data.get("keywords", []):
                    return item_ref, prep, i
    return None, None, -1

@VerbRegistry.register(["turn", "crank", "push", "pull", "touch", "press"])
class ObjectInteraction(BaseVerb):
    def execute(self):
        print(f"\n[DEBUG] ObjectInteraction: Trigger='{self.command_trigger}' Args={self.args}")
        if not self.args:
            self.player.send_message(f"{self.command_trigger.capitalize()} what?")
            return

        target_name = " ".join(self.args).lower()
        clean_target = _clean_name(target_name)
        print(f"[DEBUG] Target Input: '{target_name}' | Cleaned: '{clean_target}'")
        
        # 1. Find the target object in the room (Dynamic Objects)
        found_obj = None
        
        print("[DEBUG] Checking Room Objects (items/mobs)...")
        for obj in self.room.objects:
            obj_name = obj.get("name", "").lower()
            keywords = obj.get("keywords", [])
            print(f"  > Checking Item: Name='{obj_name}' Keywords={keywords}")
            
            if clean_target == obj_name or clean_target == _clean_name(obj_name) or clean_target in keywords:
                found_obj = obj
                print("  >> MATCH FOUND in Room Objects!")
                break

        # 2. Check Room Details (Static Features) if not found in objects
        if not found_obj:
            details = self.room.data.get("details", [])
            print(f"[DEBUG] Checking {len(details)} Room Details (features)...")
            
            for detail in details:
                d_name = detail.get("name", "").lower()
                d_keywords = detail.get("keywords", [])
                print(f"  > Checking Detail: Name='{d_name}' Keywords={d_keywords}")

                # Check keywords (most common for details)
                if clean_target in d_keywords:
                    found_obj = detail
                    print("  >> MATCH FOUND in Room Details (via Keyword)!")
                    break
                # Check explicit name if present
                if d_name and (clean_target == d_name or clean_target == _clean_name(d_name)):
                    found_obj = detail
                    print("  >> MATCH FOUND in Room Details (via Name)!")
                    break

        if not found_obj:
            print("[DEBUG] RESULT: No matching object or detail found.")
            self.player.send_message(f"You don't see a '{target_name}' here.")
            return

        # 3. Check for defined interactions
        interactions = found_obj.get("interactions", {})
        verb = self.command_trigger.lower()
        print(f"[DEBUG] Interactions Defined on Target: {list(interactions.keys())}")
        
        if verb in interactions:
            action = interactions[verb]
            act_type = action.get("type")
            act_val = action.get("value")
            
            print(f"[DEBUG] Executing Action: Type='{act_type}' Value='{act_val}'")
            
            if act_type == "text":
                self.player.send_message(act_val)
            elif act_type == "script":
                execute_script(self.world, self.player, self.room, act_val)
            elif act_type == "move":
                self.player.move_to_room(act_val)
            return

        print(f"[DEBUG] RESULT: Verb '{verb}' not found in target's interactions.")
        self.player.send_message(f"You can't {verb} that.")

@VerbRegistry.register(["get", "take"])
class Get(BaseVerb):
    def execute(self):
        # Delayed Import to avoid circular dependency
        from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
        from mud_backend.verbs.shop import _get_shop_data, _get_item_buy_price

        if _check_action_roundtime(self.player, action_type="other"):
            return
        if not self.args:
            self.player.send_message("Get what?")
            return

        args_str = " ".join(self.args).lower()

        # --- LOCKER ---
        if "from locker" in args_str or "from vault" in args_str:
            if "vault" not in self.room.name.lower() and "locker" not in self.room.name.lower():
                self.player.send_message("You must be at the Town Hall Vaults to access your locker.")
                return
            target = args_str.replace("from locker", "").replace("from vault", "").strip()
            if target.startswith("get "):
                target = target[4:].strip()
            if target.startswith("take "):
                target = target[5:].strip()

            locker = self.player.locker
            found_item = None; found_idx = -1
            clean_t = _clean_name(target)

            for i, item in enumerate(locker["items"]):
                i_name = item["name"].lower()
                if clean_t == i_name or clean_t == _clean_name(i_name) or clean_t in item.get("keywords", []):
                    found_item = item; found_idx = i; break

            if not found_item:
                self.player.send_message("You don't see that in your locker."); return
            if self.player.current_encumbrance + found_item.get("weight", 1) > self.player.max_carry_weight:
                self.player.send_message("That is too heavy."); return

            locker["items"].pop(found_idx)
            self.player.inventory.append(found_item)
            db.update_player_locker(self.player.name, locker)
            self.player.send_message(f"You get {found_item['name']} from your locker."); return

        # --- PARSE ARGS (Item vs Container) ---
        target_item_name = args_str
        target_container_name = None
        target_prep = None

        if " from " in args_str:
            parts = args_str.split(" from ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()

            # Check for preposition in container name
            match = re.search(r'^(inside|into|under|behind|beneath|in|on)\s+(.+)', target_container_name, re.IGNORECASE)
            if match:
                target_prep = match.group(1)
                target_container_name = match.group(2)

        target_hand_slot = None
        if self.player.worn_items.get("mainhand") is None:
            target_hand_slot = "mainhand"
        elif self.player.worn_items.get("offhand") is None:
            target_hand_slot = "offhand"
        game_items = self.world.game_items

        # --- GET FROM CONTAINER / OBJECT ---
        if target_container_name:
            clean_cont = _clean_name(target_container_name)
            container_obj = None
            for obj in self.room.objects:
                o_name = obj.get("name", "").lower()
                if clean_cont == o_name or clean_cont == _clean_name(o_name) or clean_cont in obj.get("keywords", []):
                    container_obj = obj
                    break

            if container_obj:
                # Shop Table Check
                if "table" in container_obj.get("keywords", []):
                    shop_data = _get_shop_data(self.room)
                    if shop_data:
                        # Shop retrieval logic not fully implemented for GET, usually handled by BUY
                        clean_item = _clean_name(target_item_name)
                        for item_ref in shop_data.get("inventory", []):
                            item_data = _get_item_data(item_ref, game_items)
                            if item_data:
                                i_name = item_data.get("name", "").lower()
                                if clean_item == i_name or clean_item in item_data.get("keywords", []):
                                    price = _get_item_buy_price(item_ref, game_items, shop_data)
                                    self.player.send_message(f"The pawnbroker notices your interest. 'That {item_data.get('name')} costs {price} silvers.'")
                                    return

                # Container Storage Check
                item_ref, found_prep, idx = _find_item_in_obj_storage(container_obj, target_item_name, game_items, specific_prep=target_prep)
                if item_ref:
                    if not target_hand_slot:
                        self.player.send_message("Your hands are full."); return
                    
                    # Remove from active object
                    container_obj["container_storage"][found_prep].pop(idx)
                    
                    # --- SYNC WITH PERSISTENT DATA ---
                    if "uid" in container_obj:
                        persistent_objs = self.room.data.get("objects", [])
                        for p_obj in persistent_objs:
                            if p_obj.get("uid") == container_obj["uid"]:
                                if "container_storage" in p_obj and found_prep in p_obj["container_storage"]:
                                    try:
                                        if len(p_obj["container_storage"][found_prep]) > idx:
                                            p_obj["container_storage"][found_prep].pop(idx)
                                    except:
                                        pass
                                break
                    # ---------------------------------

                    self.player.worn_items[target_hand_slot] = item_ref
                    item_data = _get_item_data(item_ref, game_items)
                    self.player.send_message(f"You get {item_data.get('name', 'item')} from {found_prep} the {container_obj['name']}.")
                    self.world.save_room(self.room)
                    _set_action_roundtime(self.player, 1.0); return

                loc_str = f"{target_prep} " if target_prep else "on/in "
                self.player.send_message(f"You don't see a '{target_item_name}' {loc_str}the {container_obj['name']}."); return

            # Player Containers
            container_data = _find_container_on_player(self.player, game_items, target_container_name)
            if not container_data:
                self.player.send_message(f"You don't have a container called '{target_container_name}'."); return

            item_ref = _find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref:
                self.player.send_message(f"You don't have a {target_item_name} in your {container_data.get('name')}."); return

            if not target_hand_slot:
                self.player.send_message("Your hands are full."); return
            self.player.inventory.remove(item_ref)
            self.player.worn_items[target_hand_slot] = item_ref
            item_data = _get_item_data(item_ref, game_items)
            self.player.send_message(f"You get {item_data.get('name', 'item')} from your {container_data.get('name')} and hold it.")
            _set_action_roundtime(self.player, 1.0)

        # --- GET FROM GROUND / SURFACES ---
        else:
            item_obj = _find_item_in_room(self.room.objects, target_item_name)
            if item_obj:
                if item_obj.get("dynamic") or "temp" in item_obj or "quality" in item_obj:
                    item_to_pickup = item_obj
                else:
                    item_to_pickup = item_obj.get("item_id")

                if not item_to_pickup and item_obj.get("is_item"):
                    item_to_pickup = item_obj
                item_name = item_obj.get("name", "an item")

                if not item_to_pickup:
                    self.player.send_message(f"You can't seem to pick up the {item_name}."); return
                
                if not target_hand_slot:
                    self.player.inventory.append(item_to_pickup)
                    self.player.send_message(f"Both hands are full. You get {item_name} and put it in your pack.")
                else:
                    self.player.worn_items[target_hand_slot] = item_to_pickup
                    self.player.send_message(f"You get {item_name} and hold it.")
                
                # --- REMOVE FROM ROOM (Persistent Sync) ---
                if item_obj in self.room.objects:
                    self.room.objects.remove(item_obj)
                
                # Remove from room.data["objects"] using UID
                target_uid = item_obj.get("uid")
                if target_uid:
                    persistent_objs = self.room.data.get("objects", [])
                    for i, obj in enumerate(persistent_objs):
                        if obj.get("uid") == target_uid:
                            persistent_objs.pop(i)
                            break
                # -------------------------------------------

                self.world.save_room(self.room)
                return

            # Check Surfaces (ON) - Implicit check
            for obj in self.room.objects:
                item_ref, found_prep, idx = _find_item_in_obj_storage(obj, target_item_name, game_items, specific_prep="on")
                if item_ref:
                    if not target_hand_slot:
                        self.player.send_message("Your hands are full."); return
                    
                    # Remove from active
                    obj["container_storage"][found_prep].pop(idx)
                    
                    # --- SYNC WITH PERSISTENT DATA ---
                    if "uid" in obj:
                        persistent_objs = self.room.data.get("objects", [])
                        for p_obj in persistent_objs:
                            if p_obj.get("uid") == obj["uid"]:
                                if "container_storage" in p_obj and found_prep in p_obj["container_storage"]:
                                    try:
                                        if len(p_obj["container_storage"][found_prep]) > idx:
                                            p_obj["container_storage"][found_prep].pop(idx)
                                    except:
                                        pass
                                break
                    # ---------------------------------

                    self.player.worn_items[target_hand_slot] = item_ref
                    item_data = _get_item_data(item_ref, game_items)
                    self.player.send_message(f"You get {item_data.get('name', 'item')} from {found_prep} the {obj['name']}.")
                    self.world.save_room(self.room)
                    _set_action_roundtime(self.player, 1.0); return

            # Shop Inventory
            shop_data = _get_shop_data(self.room)
            if shop_data:
                for item_ref in shop_data.get("inventory", []):
                    item_data = _get_item_data(item_ref, game_items)
                    if item_data and (target_item_name == item_data.get("name", "").lower() or target_item_name in item_data.get("keywords", [])):
                        price = _get_item_buy_price(item_ref, game_items, shop_data)
                        self.player.send_message(f"The pawnbroker notices your interest. 'That {item_data.get('name')} will cost you {price} silvers.'"); return

            # Inventory Unstow
            item_ref_from_pack = _find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here."); return
            if not target_hand_slot:
                self.player.send_message("Your hands are full."); return
            self.player.inventory.remove(item_ref_from_pack)
            self.player.worn_items[target_hand_slot] = item_ref_from_pack
            item_data = _get_item_data(item_ref_from_pack, game_items)
            self.player.send_message(f"You get {item_data.get('name', 'item')} from your pack and hold it.")
            _set_action_roundtime(self.player, 1.0)