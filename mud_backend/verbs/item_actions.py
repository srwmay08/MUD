# mud_backend/verbs/item_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.scripting import execute_script
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.item_utils import (
    clean_name, 
    get_item_data, 
    find_item_in_room, 
    find_item_in_inventory, 
    find_item_in_obj_storage, 
    find_container_on_player
)
# UPDATED: Import from core.economy
from mud_backend.core.economy import get_shop_data, get_item_buy_price
from mud_backend.core import db
import re

@VerbRegistry.register(["turn", "crank", "push", "pull", "touch", "press"])
class ObjectInteraction(BaseVerb):
    def execute(self):
        cmd_name = getattr(self, 'command', 'interact').lower()
        
        if not self.args:
            self.player.send_message(f"{cmd_name.capitalize()} what?")
            return

        target_name = " ".join(self.args).lower()
        clean_target = clean_name(target_name)
        
        found_obj = None
        
        # 1. Search Room Objects (Dynamic items/mobs)
        for obj in self.room.objects:
            n = obj.get("name", "").lower()
            k = obj.get("keywords", [])
            if clean_target == n or clean_target == clean_name(n) or clean_target in k:
                found_obj = obj
                break

        # 2. Search Room Details (Static features)
        if not found_obj:
            details = self.room.data.get("details", [])
            static_objs = self.room.data.get("objects", [])
            all_statics = details + static_objs
            
            for detail in all_statics:
                d_name = detail.get("name", "").lower()
                d_keys = detail.get("keywords", [])
                
                if clean_target in d_keys:
                    found_obj = detail
                    break
                if d_name and (clean_target == d_name or clean_target == clean_name(d_name)):
                    found_obj = detail
                    break

        if not found_obj:
            self.player.send_message(f"You don't see a '{target_name}' here.")
            return

        # 3. Check Interactions
        interactions = found_obj.get("interactions", {})
        
        if cmd_name in interactions:
            # --- BROADCAST ACTION TO ROOM ---
            # This ensures observers see "Sevax turns the windlass."
            if not self.player.is_hidden:
                # Resolve a nice display name
                obj_display_name = found_obj.get("name", target_name)
                # Helper to conjugate verb roughly (turns vs turn) - simplistic approach:
                verb_display = cmd_name + "s"
                msg = f"{self.player.name} {verb_display} the {obj_display_name}."
                self.world.broadcast_to_room(
                    self.room.room_id, 
                    msg, 
                    "message", 
                    skip_player=self.player # The actor gets specific feedback from the interaction logic below
                )
            # --------------------------------

            action = interactions[cmd_name]
            act_type = action.get("type")
            act_val = action.get("value")
            
            if act_type == "text":
                self.player.send_message(act_val)
            elif act_type == "script":
                # Ensure the script engine is imported correctly at the top
                from mud_backend.core.scripting import execute_script
                execute_script(self.world, self.player, self.room, act_val)
            elif act_type == "move":
                self.player.move_to_room(act_val)
            return

        self.player.send_message(f"You can't {cmd_name} that.")

@VerbRegistry.register(["get", "take"])
class Get(BaseVerb):
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
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
            clean_t = clean_name(target)

            for i, item in enumerate(locker["items"]):
                i_name = item["name"].lower()
                if clean_t == i_name or clean_t == clean_name(i_name) or clean_t in item.get("keywords", []):
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
            clean_cont = clean_name(target_container_name)
            container_obj = None
            for obj in self.room.objects:
                o_name = obj.get("name", "").lower()
                if clean_cont == o_name or clean_cont == clean_name(o_name) or clean_cont in obj.get("keywords", []):
                    container_obj = obj
                    break

            if container_obj:
                # Shop Table Check
                if "table" in container_obj.get("keywords", []):
                    shop_data = get_shop_data(self.room)
                    if shop_data:
                        clean_item = clean_name(target_item_name)
                        for item_ref in shop_data.get("inventory", []):
                            item_data = get_item_data(item_ref, game_items)
                            if item_data:
                                i_name = item_data.get("name", "").lower()
                                if clean_item == i_name or clean_item in item_data.get("keywords", []):
                                    price = get_item_buy_price(item_ref, game_items, shop_data)
                                    self.player.send_message(f"The pawnbroker notices your interest. 'That {item_data.get('name')} costs {price} silvers.'")
                                    return

                # Container Storage Check
                item_ref, found_prep, idx = find_item_in_obj_storage(container_obj, target_item_name, game_items, specific_prep=target_prep)
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
                    item_data = get_item_data(item_ref, game_items)
                    self.player.send_message(f"You get {item_data.get('name', 'item')} from {found_prep} the {container_obj['name']}.")
                    self.world.save_room(self.room)
                    set_action_roundtime(self.player, 1.0); return

                loc_str = f"{target_prep} " if target_prep else "on/in "
                self.player.send_message(f"You don't see a '{target_item_name}' {loc_str}the {container_obj['name']}."); return

            # Player Containers
            container_data = find_container_on_player(self.player, game_items, target_container_name)
            if not container_data:
                self.player.send_message(f"You don't have a container called '{target_container_name}'."); return

            item_ref = find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref:
                self.player.send_message(f"You don't have a {target_item_name} in your {container_data.get('name')}."); return

            if not target_hand_slot:
                self.player.send_message("Your hands are full."); return
            self.player.inventory.remove(item_ref)
            self.player.worn_items[target_hand_slot] = item_ref
            item_data = get_item_data(item_ref, game_items)
            self.player.send_message(f"You get {item_data.get('name', 'item')} from your {container_data.get('name')} and hold it.")
            set_action_roundtime(self.player, 1.0)

        # --- GET FROM GROUND / SURFACES ---
        else:
            item_obj = find_item_in_room(self.room.objects, target_item_name)
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
                item_ref, found_prep, idx = find_item_in_obj_storage(obj, target_item_name, game_items, specific_prep="on")
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
                    item_data = get_item_data(item_ref, game_items)
                    self.player.send_message(f"You get {item_data.get('name', 'item')} from {found_prep} the {obj['name']}.")
                    self.world.save_room(self.room)
                    set_action_roundtime(self.player, 1.0); return

            # Shop Inventory
            shop_data = get_shop_data(self.room)
            if shop_data:
                for item_ref in shop_data.get("inventory", []):
                    item_data = get_item_data(item_ref, game_items)
                    if item_data and (target_item_name == item_data.get("name", "").lower() or target_item_name in item_data.get("keywords", [])):
                        price = get_item_buy_price(item_ref, game_items, shop_data)
                        self.player.send_message(f"The pawnbroker notices your interest. 'That {item_data.get('name')} will cost you {price} silvers.'"); return

            # Inventory Unstow
            item_ref_from_pack = find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here."); return
            if not target_hand_slot:
                self.player.send_message("Your hands are full."); return
            self.player.inventory.remove(item_ref_from_pack)
            self.player.worn_items[target_hand_slot] = item_ref_from_pack
            item_data = get_item_data(item_ref_from_pack, game_items)
            self.player.send_message(f"You get {item_data.get('name', 'item')} from your pack and hold it.")
            set_action_roundtime(self.player, 1.0)