# mud_backend/verbs/item_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import db
from typing import Dict, Any, Union
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time

def _get_item_data(item_ref: Union[str, Dict[str, Any]], game_items_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolves an item reference (string ID or dynamic dict) to its data dictionary.
    """
    if isinstance(item_ref, dict):
        return item_ref
    return game_items_data.get(item_ref, {})

def _find_item_in_room(room_objects: list, target_name: str) -> Dict[str, Any] | None:
    """Helper function to find a gettable item object by name or keywords."""
    matches = []
    for obj in room_objects:
        if not obj.get("is_item"):
            continue
            
        if (target_name == obj.get("name", "").lower() or 
            target_name in obj.get("keywords", [])):
            matches.append(obj)
    
    if matches:
        return matches[0]
        
    return None

def _find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> Union[str, Dict[str, Any], None]:
    """
    Finds the first item in a player's inventory that matches.
    Returns the item_id (str) OR the item object (dict) if dynamic.
    """
    for item in player.inventory:
        item_data = _get_item_data(item, game_items_data)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item
    return None

def _find_container_on_player(player, game_items_data: Dict[str, Any], target_name: str) -> Dict[str, Any] | None:
    """Finds a container item on the player (worn or in inventory)."""
    # Check worn
    for slot, item in player.worn_items.items():
        if item:
            item_data = _get_item_data(item, game_items_data)
            if item_data and item_data.get("is_container"):
                item_id = item.get("uid") if isinstance(item, dict) else item
                search_keywords = item_data.get("keywords", []) + [item_id]
                
                if (target_name == item_data.get("name", "").lower() or
                    target_name in search_keywords):
                    item_data_with_id = item_data.copy()
                    item_data_with_id["_runtime_item_ref"] = item
                    return item_data_with_id

    # Check inventory
    for item in player.inventory:
        item_data = _get_item_data(item, game_items_data)
        if item_data and item_data.get("is_container"):
             item_id = item.get("uid") if isinstance(item, dict) else item
             search_keywords = item_data.get("keywords", []) + [item_id]
             if (target_name == item_data.get("name", "").lower() or
                target_name in search_keywords):
                item_data_with_id = item_data.copy()
                item_data_with_id["_runtime_item_ref"] = item
                return item_data_with_id
    return None


class Get(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
            self.player.send_message("Get what?")
            return

        args_str = " ".join(self.args).lower()
        target_item_name = args_str
        target_container_name = None

        if " from " in args_str:
            parts = args_str.split(" from ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
            if target_container_name.startswith("my "):
                target_container_name = target_container_name[3:].strip()

        target_hand_slot = None
        right_hand_slot = "mainhand"
        left_hand_slot = "offhand"
        
        # Determine hand preference
        if self.player.flags.get("righthand", "on") == "on":
            if self.player.worn_items.get(right_hand_slot) is None: target_hand_slot = right_hand_slot
            elif self.player.worn_items.get(left_hand_slot) is None: target_hand_slot = left_hand_slot
        elif self.player.flags.get("lefthand", "on") == "on":
            if self.player.worn_items.get(left_hand_slot) is None: target_hand_slot = left_hand_slot
            elif self.player.worn_items.get(right_hand_slot) is None: target_hand_slot = right_hand_slot
        else:
            if self.player.worn_items.get(right_hand_slot) is None: target_hand_slot = right_hand_slot
            elif self.player.worn_items.get(left_hand_slot) is None: target_hand_slot = left_hand_slot

        game_items = self.world.game_items

        # --- GET FROM CONTAINER ---
        if target_container_name:
            container_data = _find_container_on_player(self.player, game_items, target_container_name)
            if not container_data:
                self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                return
            
            if container_data.get("wearable_slot") != "back":
                self.player.send_message(f"You can only retrieve items from your main backpack currently.")
                return

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
            
        # --- GET FROM GROUND ---
        else:
            item_obj = _find_item_in_room(self.room.objects, target_item_name)
            
            if item_obj:
                # If it's dynamic (has temp/quality) or explicitly marked, keep as dict
                if item_obj.get("dynamic") or "temp" in item_obj or "quality" in item_obj:
                     item_to_pickup = item_obj 
                     item_name = item_obj.get("name", "an item")
                else:
                     item_to_pickup = item_obj.get("item_id")
                     item_name = item_obj.get("name", "an item")
                
                if not item_to_pickup:
                     if item_obj.get("item_id"):
                         item_to_pickup = item_obj.get("item_id")
                     else:
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

            # --- GET FROM INVENTORY (Auto-wield) ---
            item_ref_from_pack = _find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_ref_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here or in your pack.")
                return

            if not target_hand_slot:
                self.player.send_message("Your hands are full. You must free a hand to get that from your pack.")
                return

            self.player.inventory.remove(item_ref_from_pack)
            self.player.worn_items[target_hand_slot] = item_ref_from_pack
            
            item_data = _get_item_data(item_ref_from_pack, game_items)
            item_name = item_data.get("name", "an item")
            
            self.player.send_message(f"You get {item_name} from your pack and hold it.")
            _set_action_roundtime(self.player, 1.0)


class Drop(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"): return
        if not self.args:
             self.player.send_message("Drop what?")
             return

        # SAFEDROP Check
        args_str = " ".join(self.args).lower()
        is_confirmed = False
        if self.args and self.args[-1].lower() == "confirm":
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
             parts = args_str.split(" on ", 1)
             possible_item = parts[0].strip()
             possible_slot = parts[1].strip()
             if possible_slot in ["back", "head", "torso", "legs", "feet", "hands", "waist"]:
                  self.player.send_message(f"To wear items, please use 'WEAR {possible_item}'.")
                  return
             target_item_name = possible_item
             target_container_name = possible_slot

        game_items = self.world.game_items

        if self.command == "stow":
            target_item_name = args_str
            backpack = _find_container_on_player(self.player, game_items, "backpack")
            if backpack:
                 target_container_name = backpack.get("keywords", ["backpack"])[0]
            else:
                 self.player.send_message("You don't seem to have a backpack to stow things in.")
                 return
            
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

            container_runtime_ref = container.get("_runtime_item_ref")
            if container_runtime_ref == item_ref_to_drop:
                 self.player.send_message("You can't put something inside itself!")
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

        # --- DROP ON GROUND ---
        else:
            if self.player.flags.get("safedrop", "on") == "on" and not is_confirmed:
                self.player.send_message(f"SAFEDROP is on. To drop {item_name}, type 'DROP {target_item_name} CONFIRM'.")
                return
            
            if item_location == "inventory":
                self.player.inventory.remove(item_ref_to_drop)
            else:
                self.player.worn_items[item_location] = None
            
            # Handle dynamic items
            if isinstance(item_ref_to_drop, dict):
                if "keywords" not in item_ref_to_drop:
                     item_ref_to_drop["keywords"] = item_data.get("keywords", [])
                if "verbs" not in item_ref_to_drop:
                     item_ref_to_drop["verbs"] = ["GET", "LOOK", "EXAMINE", "TAKE"]
                if "is_item" not in item_ref_to_drop:
                     item_ref_to_drop["is_item"] = True
                self.room.objects.append(item_ref_to_drop)
            else:
                # Handle static items (wrap in dict)
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

class Take(Get): pass
class Put(Drop): pass
class Pour(BaseVerb):
    def execute(self):
        self.player.send_message("Pour is not implemented.")