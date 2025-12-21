# mud_backend/verbs/put.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import db
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.item_actions import (
    _clean_name, 
    _find_item_in_hands, 
    _find_item_in_inventory, 
    _get_item_data, 
    _find_container_on_player
)
import re
import uuid

@VerbRegistry.register(["put", "stow"])
class Put(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return
        if not self.args:
            self.player.send_message("Put what where? (e.g., PUT DAGGER ON BENCH)")
            return

        args_str = " ".join(self.args).lower()

        # --- LOCKER LOGIC ---
        if "in locker" in args_str or "in vault" in args_str:
            if "vault" not in self.room.name.lower() and "locker" not in self.room.name.lower():
                 self.player.send_message("You must be at the Town Hall Vaults to access your locker.")
                 return

            target_item_name = args_str.replace("in locker", "").replace("in vault", "").strip()
            if target_item_name.startswith("put "): target_item_name = target_item_name[4:].strip()
            
            locker = self.player.locker
            if len(locker["items"]) >= locker["capacity"]:
                self.player.send_message("Your locker is full.")
                return

            item_id_hand, hand_slot = _find_item_in_hands(self.player, self.world.game_items, target_item_name)
            item_id_inv = None
            item_id = None
            item_source = None

            if item_id_hand:
                item_id = item_id_hand
                item_source = "hand"
            else:
                item_id_inv = _find_item_in_inventory(self.player, self.world.game_items, target_item_name)
                if item_id_inv:
                    item_id = item_id_inv
                    item_source = "inventory"

            if not item_id:
                self.player.send_message("You don't have that.")
                return
                
            item_data = None
            if isinstance(item_id, dict):
                item_data = item_id
            else:
                template = self.world.game_items.get(item_id)
                if template:
                    item_data = template.copy()
                    if "uid" not in item_data: item_data["uid"] = uuid.uuid4().hex

            if item_source == "hand":
                self.player.worn_items[hand_slot] = None
            else:
                self.player.inventory.remove(item_id)

            if item_data:
                locker["items"].append(item_data)
                db.update_player_locker(self.player.name, locker)
                self.player.send_message(f"You put {item_data['name']} in your locker.")
            return

        # --- REGULAR PUT LOGIC ---
        
        # 1. Regex to split ITEM and CONTAINER using a preposition
        match = re.search(r'\s+(inside|into|under|behind|beneath|in|on)\s+', args_str, re.IGNORECASE)

        if match:
            target_prep = match.group(1).lower()
            start, end = match.span()
            target_item_name = args_str[:start].strip()
            target_container_name = args_str[end:].strip()
        else:
            # Fallback for "put item container" (implicit IN)
            parts = args_str.rsplit(' ', 1)
            if len(parts) == 2:
                 target_item_name = parts[0].strip()
                 target_container_name = parts[1].strip()
                 target_prep = "in"
            else:
                 # Handle STOW (put in backpack)
                 if self.command == "stow":
                     backpack = _find_container_on_player(self.player, self.world.game_items, "backpack")
                     if backpack:
                         target_container_name = backpack.get("keywords", ["backpack"])[0]
                         target_item_name = args_str
                         target_prep = "in"
                     else:
                         self.player.send_message("You don't have a backpack to stow items in.")
                         return
                 else:
                     self.player.send_message("Put it where? (e.g., PUT DAGGER ON BENCH)")
                     return

        if not target_item_name or not target_container_name:
             self.player.send_message("Put it where? (e.g., PUT DAGGER ON BENCH)")
             return

        target_item_name = _clean_name(target_item_name)
        target_container_name = _clean_name(target_container_name)
        
        game_items = self.world.game_items
        
        # --- 2. FIND THE ITEM (Hands or Inventory) ---
        item_ref = None; hand_slot = None; from_inventory = False

        # Check Hands
        item_ref, hand_slot = _find_item_in_hands(self.player, game_items, target_item_name)

        # Check Inventory (if not in hands)
        if not item_ref:
            item_ref = _find_item_in_inventory(self.player, game_items, target_item_name)
            if item_ref:
                from_inventory = True
        
        # Must be holding it to place it (except for stowing from inventory)
        if not item_ref:
            self.player.send_message(f"You aren't holding a '{target_item_name}'.")
            return

        item_data = _get_item_data(item_ref, game_items)
        item_name = item_data.get("name", "the item")

        # --- 3. FIND THE CONTAINER/SURFACE ---
        container_obj = None
        
        # Check Room Objects (Bench, Table, etc.)
        for obj in self.room.objects:
            o_name = obj.get("name", "").lower()
            if target_container_name == o_name or target_container_name == _clean_name(o_name) or target_container_name in obj.get("keywords", []):
                container_obj = obj
                break
        
        # Check worn containers if not found in room
        if not container_obj:
             container_obj = _find_container_on_player(self.player, game_items, target_container_name)

        if not container_obj:
            self.player.send_message(f"You don't see a {target_container_name} here.")
            return

        # --- 4. VALIDATE PLACEMENT ---
        if target_prep in ["inside", "into"]:
            target_prep = "in"
        if target_prep == "beneath":
            target_prep = "under"
            
        supported = False
        interactions = container_obj.get("interactions", {})
        look_key = f"look {target_prep}".lower()

        # Check if interaction exists (e.g., "look behind")
        for key in interactions.keys():
            if key.lower() == look_key:
                supported = True
                break
        
        # Check if storage already exists or logic implies it
        if not supported:
            if "container_storage" in container_obj and target_prep in container_obj["container_storage"]:
                supported = True
            elif target_prep == "on" and ("table" in container_obj.get("keywords", []) or container_obj.get("is_table")):
                supported = True
            elif target_prep == "in" and container_obj.get("is_container"):
                supported = True

        # Trash logic
        trash_keywords = ["bin", "trash", "barrel", "crate", "urn", "coffin", "case"]
        is_trash = any(k in container_obj.get("keywords", []) for k in trash_keywords) and target_prep == "in"
        if is_trash: supported = True

        if not supported and not is_trash:
            self.player.send_message(f"You can't put things {target_prep} the {container_obj['name']}.")
            return

        # --- 5. EXECUTE MOVE ---
        
        # Remove from source
        if from_inventory:
            self.player.inventory.remove(item_ref)
        else:
            self.player.worn_items[hand_slot] = None

        # Add to destination
        if is_trash:
             self.player.send_message(f"You discard {item_name} into the {container_obj['name']}.")
             _set_action_roundtime(self.player, 1.0)
             return

        # Update Active Object
        if "container_storage" not in container_obj:
            container_obj["container_storage"] = {}
        if target_prep not in container_obj["container_storage"]:
            container_obj["container_storage"][target_prep] = []
        
        container_obj["container_storage"][target_prep].append(item_ref)

        self.player.send_message(f"You put {item_name} {target_prep} the {container_obj['name']}.")
        
        # --- SYNC WITH PERSISTENT DATA ---
        if container_obj.get("_runtime_item_ref"):
             pass 
        else:
             # Find persistent object by UID
             target_uid = container_obj.get("uid")
             if target_uid:
                 persistent_objs = self.room.data.get("objects", [])
                 for p_obj in persistent_objs:
                     if p_obj.get("uid") == target_uid:
                         if "container_storage" not in p_obj:
                             p_obj["container_storage"] = {}
                         if target_prep not in p_obj["container_storage"]:
                             p_obj["container_storage"][target_prep] = []
                         p_obj["container_storage"][target_prep].append(item_ref)
                         break
             
             self.world.save_room(self.room)
             
        _set_action_roundtime(self.player, 0.5)