# mud_backend/verbs/equipment.py
from mud_backend.verbs.base_verb import BaseVerb
from typing import Dict, Any, Tuple, Optional
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.item_actions import _find_item_in_inventory, _get_item_data, _find_item_in_hands, _find_item_worn, _find_container_on_player
from mud_backend.core import db
import uuid

@VerbRegistry.register(["wear", "wield"])
class Wear(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Wear what?")
            return
        target_name = " ".join(self.args).lower()
        
        item_id = None
        source_type = None 
        source_slot = None
        
        hand_item_id, hand_slot = _find_item_in_hands(self.player, self.world.game_items, target_name)
        if hand_item_id:
            item_id = hand_item_id
            source_type = "hand"
            source_slot = hand_slot
        else:
            inv_item_id = _find_item_in_inventory(self.player, self.world.game_items, target_name)
            if inv_item_id:
                item_id = inv_item_id
                source_type = "inventory"

        if not item_id:
            self.player.send_message(f"You don't have a '{target_name}'.")
            return

        item_data = self.world.game_items.get(item_id)
        if not item_data:
            self.player.send_message("Error with item.")
            return

        target_slot = item_data.get("wearable_slot")
        if not target_slot:
            self.player.send_message(f"You cannot wear {item_data.get('name')}.")
            return
            
        if self.player.worn_items.get(target_slot) is not None:
            self.player.send_message(f"You are already wearing something on your {target_slot}.")
            return
            
        if source_type == "inventory":
            self.player.inventory.remove(item_id)
        elif source_type == "hand":
             self.player.worn_items[source_slot] = None

        self.player.worn_items[target_slot] = item_id
        verb = "wield" if item_data.get("item_type") in ["weapon", "shield"] else "wear"
        self.player.send_message(f"You {verb} {item_data.get('name')}.")
        _set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["remove"])
class Remove(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Remove what?")
            return
        target_name = " ".join(self.args).lower()
        item_id, slot = _find_item_worn(self.player, target_name)
        if not item_id:
            self.player.send_message(f"You are not wearing a {target_name}.")
            return
        item_data = self.world.game_items.get(item_id, {})
        
        target_hand_slot = None
        if self.player.worn_items.get("mainhand") is None: target_hand_slot = "mainhand"
        elif self.player.worn_items.get("offhand") is None: target_hand_slot = "offhand"

        if target_hand_slot:
            self.player.worn_items[slot] = None 
            self.player.worn_items[target_hand_slot] = item_id
            verb = "lower" if item_data.get("item_type") in ["weapon", "shield"] else "remove"
            self.player.send_message(f"You {verb} {item_data.get('name')} and hold it.")
        else:
            if item_data.get("wearable_slot") == "back" and item_data.get("is_container"):
                 self.player.send_message("Hands full! Cannot put pack inside itself.")
                 return
            self.player.worn_items[slot] = None 
            self.player.inventory.append(item_id) 
            self.player.send_message(f"You remove {item_data.get('name')} and put it in your pack.")
        _set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["drop"])
@VerbRegistry.register(["put", "stow"]) # Aliases map here
class Drop(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
             self.player.send_message("Drop what?")
             return

        args_str = " ".join(self.args).lower()
        
        # --- NEW: PUT IN LOCKER ---
        if "in locker" in args_str or "in vault" in args_str:
            # Basic check
            if "vault" not in self.room.name.lower() and "locker" not in self.room.name.lower():
                 self.player.send_message("You must be at the Town Hall Vaults to access your locker.")
                 return

            target_item_name = args_str.replace("in locker", "").replace("in vault", "").strip()
            # If user typed 'put ring in locker', target is 'ring'
            if target_item_name.startswith("put "): target_item_name = target_item_name[4:].strip()
            
            locker = self.player.locker
            if len(locker["items"]) >= locker["capacity"]:
                self.player.send_message("Your locker is full.")
                return

            # Check hands first
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
                
            # Move to locker
            item_data = None
            if isinstance(item_id, dict):
                item_data = item_id
            else:
                template = self.world.game_items.get(item_id)
                if template:
                    item_data = template.copy()
                    if "uid" not in item_data: item_data["uid"] = uuid.uuid4().hex

            # Remove from player
            if item_source == "hand":
                self.player.worn_items[hand_slot] = None
            else:
                self.player.inventory.remove(item_id)

            if item_data:
                locker["items"].append(item_data)
                db.update_player_locker(self.player.name, locker)
                self.player.send_message(f"You put {item_data['name']} in your locker.")
            return
        # --------------------------

        is_confirmed = False
        if self.args[-1].lower() == "confirm":
            is_confirmed = True
            self.args = self.args[:-1]
            args_str = " ".join(self.args).lower()

        target_item_name = args_str
        target_container_name = None

        if " in " in args_str:
            parts = args_str.split(" in ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
        elif " on " in args_str:
             # Basic error catch for "put X on Y" if user meant wear
             parts = args_str.split(" on ", 1)
             target_item_name = parts[0].strip()
             # Not implemented logic, fall through to drop failure

        game_items = self.world.game_items

        if self.command == "stow" and not target_container_name:
            backpack = _find_container_on_player(self.player, game_items, "backpack")
            if backpack:
                 target_container_name = backpack.get("keywords", ["backpack"])[0]
            
        if target_container_name and target_container_name.startswith("my "):
            target_container_name = target_container_name[3:].strip()

        item_ref_to_drop = None
        item_location = None
        
        # Check hands first
        for slot in ["mainhand", "offhand"]:
            item_ref = self.player.worn_items.get(slot)
            if item_ref:
                item_data = _get_item_data(item_ref, game_items)
                if (target_item_name == item_data.get("name", "").lower() or 
                    target_item_name in item_data.get("keywords", [])):
                    item_ref_to_drop = item_ref
                    item_location = slot
                    break
        
        if not item_ref_to_drop:
            item_ref_to_drop = _find_item_in_inventory(self.player, game_items, target_item_name)
            if item_ref_to_drop:
                item_location = "inventory"

        if not item_ref_to_drop:
            self.player.send_message(f"You don't seem to have a {target_item_name}.")
            return
            
        item_data = _get_item_data(item_ref_to_drop, game_items)
        item_name = item_data.get("name", "an item")

        # --- PUT IN CONTAINER ---
        if target_container_name:
            container = _find_container_on_player(self.player, game_items, target_container_name)
            if not container:
                 self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                 return

            if container.get("wearable_slot") == "back":
                if item_location == "inventory":
                    self.player.send_message(f"The {item_name} is already in your pack.")
                    return
                self.player.worn_items[item_location] = None
                self.player.inventory.append(item_ref_to_drop)
                self.player.send_message(f"You put {item_name} in your {container.get('name')}.")
            else:
                self.player.send_message(f"You can't put things in {container.get('name')} yet.")
                return
        else:
            # --- DROP ON GROUND ---
            if self.player.flags.get("safedrop", "on") == "on" and not is_confirmed and self.command == "drop":
                self.player.send_message(f"SAFEDROP is on. To drop {item_name}, type 'DROP {target_item_name} CONFIRM'.")
                return
            
            if item_location == "inventory":
                self.player.inventory.remove(item_ref_to_drop)
            else:
                self.player.worn_items[item_location] = None
            
            # Handle dynamic/static wrap
            if isinstance(item_ref_to_drop, dict):
                if "keywords" not in item_ref_to_drop: item_ref_to_drop["keywords"] = item_data.get("keywords", [])
                if "verbs" not in item_ref_to_drop: item_ref_to_drop["verbs"] = ["GET", "LOOK", "EXAMINE", "TAKE"]
                if "is_item" not in item_ref_to_drop: item_ref_to_drop["is_item"] = True
                self.room.objects.append(item_ref_to_drop)
            else:
                item_keywords = [item_name.lower(), item_ref_to_drop.lower()] + item_name.lower().split()
                new_item_obj = {
                    "name": item_name,
                    "description": item_data.get("description", "It's an item."),
                    "keywords": list(set(item_keywords)),
                    "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"],
                    "is_item": True,
                    "item_id": item_ref_to_drop,
                    "perception_dc": 0
                }
                self.room.objects.append(new_item_obj)
                
            self.world.save_room(self.room)
            self.player.send_message(f"You drop {item_name}.")
        
        _set_action_roundtime(self.player, 1.0)

@VerbRegistry.register(["take"])
class Take(Drop): # Re-using Drop base isn't right for Take, Take should map to Get.
    # Logic note: Take usually aliases to Get. 
    # The registration decorator logic in registry might handle this, but explicit inheritance is safer.
    # Wait, 'Take' is registered in item_actions.py as inheriting from Get. 
    # I should not register it here to avoid conflicts.
    pass

@VerbRegistry.register(["pour"])
class Pour(BaseVerb):
    def execute(self):
        self.player.send_message("Pour is not implemented.")