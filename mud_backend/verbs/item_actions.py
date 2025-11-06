# mud_backend/verbs/item_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import db
from mud_backend.core import game_state
from typing import Dict, Any

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
        return matches[0] # Return the first item that matches
        
    return None

def _find_item_in_inventory(player, target_name: str) -> str | None:
    """Finds the first item_id in a player's inventory that matches."""
    for item_id in player.inventory:
        item_data = game_state.GAME_ITEMS.get(item_id)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_id
    return None

def _find_container_on_player(player, target_name: str) -> Dict[str, Any] | None:
    """Finds a container item on the player (worn or in inventory)."""
    # Check worn containers (like a backpack)
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = game_state.GAME_ITEMS.get(item_id)
            if item_data and item_data.get("is_container"):
                # --- FIX: Add 'item_id' to search keywords for exact matching ---
                search_keywords = item_data.get("keywords", []) + [item_id]
                if (target_name == item_data.get("name", "").lower() or
                    target_name in search_keywords):
                    # Attach the item_id to the returned dict for easy ID checks later
                    item_data_with_id = item_data.copy()
                    item_data_with_id["_runtime_item_id"] = item_id
                    return item_data_with_id

    # Check inventory containers (like a small pouch)
    for item_id in player.inventory:
        item_data = game_state.GAME_ITEMS.get(item_id)
        if item_data and item_data.get("is_container"):
             search_keywords = item_data.get("keywords", []) + [item_id]
             if (target_name == item_data.get("name", "").lower() or
                target_name in search_keywords):
                item_data_with_id = item_data.copy()
                item_data_with_id["_runtime_item_id"] = item_id
                return item_data_with_id
    return None


class Get(BaseVerb):
    """
    Handles 'get' and 'take'.
    GET <item> (from ground first, then inventory)
    GET <item> FROM <container>
    """
    
    def execute(self):
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

        # 1. Determine free hand
        right_hand_slot = "mainhand"
        left_hand_slot = "offhand"
        target_hand_slot = None
        if self.player.worn_items.get(right_hand_slot) is None:
            target_hand_slot = right_hand_slot
        elif self.player.worn_items.get(left_hand_slot) is None:
            target_hand_slot = left_hand_slot

        # ---
        # BRANCH 1: GET <item> FROM <container>
        # ---
        if target_container_name:
            container = _find_container_on_player(self.player, target_container_name)
            
            # For now, we only support getting from the 'backpack' (main inventory)
            if not container or container.get("wearable_slot") != "back":
                self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                return

            # Find the item in the player's inventory
            item_id = _find_item_in_inventory(self.player, target_item_name)
            
            if not item_id:
                self.player.send_message(f"You don't have a {target_item_name} in your {container.get('name')}.")
                return
            
            item_data = game_state.GAME_ITEMS.get(item_id, {})
            item_name = item_data.get("name", "an item")

            # Check for free hands
            if not target_hand_slot:
                self.player.send_message("Your hands are full. You must free a hand to get that.")
                return
                
            # Move from inventory to hand
            self.player.inventory.remove(item_id)
            self.player.worn_items[target_hand_slot] = item_id
            self.player.send_message(f"You get {item_name} from your {container.get('name')} and hold it.")
            
        # ---
        # BRANCH 2: GET <item> (from GROUND first, then inventory)
        # ---
        else:
            # Check ground first
            item_obj = _find_item_in_room(self.room.objects, target_item_name)
            
            if item_obj:
                item_id = item_obj.get("item_id")
                item_name = item_obj.get("name", "an item")
                
                if not item_id:
                    self.player.send_message(f"You can't seem to pick up the {item_name}.")
                    return

                if not target_hand_slot:
                     # Auto-stow if hands full? For now, just fail if standard GET.
                     # Or we can implement the "put in pack" logic if hands full.
                     # Let's do standard MUD: must have hand free to GET, unless we add GET X AND STOW.
                     # Re-reading your prompt: you liked "Both hands are full. You get... and put it in your pack."
                     self.player.inventory.append(item_id)
                     self.player.send_message(f"Both hands are full. You get {item_name} and put it in your pack.")
                else:
                     self.player.worn_items[target_hand_slot] = item_id
                     self.player.send_message(f"You get {item_name} and hold it.")
                
                self.room.objects.remove(item_obj)
                db.save_room_state(self.room)
                return

            # If not on ground, try to find item in inventory (to hold it)
            item_id_from_pack = _find_item_in_inventory(self.player, target_item_name)
            if not item_id_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here or in your pack.")
                return

            if not target_hand_slot:
                self.player.send_message("Your hands are full. You must free a hand to get that from your pack.")
                return

            # Move from inventory to hand
            self.player.inventory.remove(item_id_from_pack)
            self.player.worn_items[target_hand_slot] = item_id_from_pack
            item_name = game_state.GAME_ITEMS.get(item_id_from_pack, {}).get("name", "an item")
            self.player.send_message(f"You get {item_name} from your pack and hold it.")


class Drop(BaseVerb):
    """
    Handles 'drop' and 'put'.
    DROP <item>
    PUT <item> IN <container>
    STOW <item> (defaults to 'put in backpack')
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Drop what?")
            return

        args_str = " ".join(self.args).lower()
        target_item_name = args_str
        target_container_name = None

        if " in " in args_str:
            parts = args_str.split(" in ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
        elif " on " in args_str:
             # Handle "put backpack on back" as a WEAR alias if it matches a slot
             parts = args_str.split(" on ", 1)
             possible_item = parts[0].strip()
             possible_slot = parts[1].strip()
             
             # Very basic check if the second part is a slot name
             # This is a hacky way to support "put X on Y" as wear without a full parser.
             # If they try "put backpack on back", we tell them to use WEAR for now to avoid complexity.
             if possible_slot in ["back", "head", "torso", "legs", "feet", "hands", "waist"]:
                  self.player.send_message(f"To wear items, please use 'WEAR {possible_item}'.")
                  return
             
             # Otherwise treat "on" as "in" for things like tables
             target_item_name = possible_item
             target_container_name = possible_slot

        elif self.command == "stow":
            target_item_name = args_str
            backpack = _find_container_on_player(self.player, "backpack")
            if backpack:
                 # We use the main keyword to ensure we find it again easily
                 target_container_name = backpack.get("keywords", ["backpack"])[0]
            else:
                 self.player.send_message("You don't seem to have a backpack to stow things in.")
                 return
            
        if target_container_name and target_container_name.startswith("my "):
            target_container_name = target_container_name[3:].strip()

        # 1. Find the item on the player
        item_id_to_drop = None
        item_location = None
        
        for slot in ["mainhand", "offhand"]:
            item_id = self.player.worn_items.get(slot)
            if item_id:
                item_data = game_state.GAME_ITEMS.get(item_id, {})
                if (target_item_name == item_data.get("name", "").lower() or 
                    target_item_name in item_data.get("keywords", [])):
                    item_id_to_drop = item_id
                    item_location = slot
                    break
        
        if not item_id_to_drop:
            item_id_to_drop = _find_item_in_inventory(self.player, target_item_name)
            if item_id_to_drop:
                item_location = "inventory"

        if not item_id_to_drop:
            self.player.send_message(f"You don't seem to have a {target_item_name}.")
            return
            
        item_data = game_state.GAME_ITEMS.get(item_id_to_drop)
        item_name = item_data.get("name", "an item")

        # 2. Handle destination
        if target_container_name:
            # --- PUT IN CONTAINER ---
            container = _find_container_on_player(self.player, target_container_name)
            
            if not container:
                 self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                 return

            # --- RECURSION CHECK ---
            # Check if the container we found is the SAME item we are trying to drop.
            # We attached _runtime_item_id in _find_container_on_player for this exact check.
            if container.get("_runtime_item_id") == item_id_to_drop:
                 self.player.send_message("You can't put something inside itself!")
                 return
            # -----------------------

            # For now, we only support putting things in the 'backpack' (main inventory)
            if container.get("wearable_slot") == "back":
                if item_location == "inventory":
                    self.player.send_message(f"The {item_name} is already in your pack.")
                    return
                
                self.player.worn_items[item_location] = None
                self.player.inventory.append(item_id_to_drop)
                self.player.send_message(f"You put {item_name} in your {container.get('name')}.")
            else:
                # Future: support putting items into other containers (pouches, etc.)
                self.player.send_message(f"You can't put things in {container.get('name')} yet.")
                return
        else:
            # --- DROP ON GROUND ---
            if item_location == "inventory":
                self.player.inventory.remove(item_id_to_drop)
            else:
                self.player.worn_items[item_location] = None
            
            item_keywords = [item_name.lower(), item_id_to_drop.lower()] + item_name.lower().split()
            new_item_obj = {
                "name": item_name,
                "description": item_data.get("description", "It's an item."),
                "keywords": list(set(item_keywords)),
                "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"],
                "is_item": True,
                "item_id": item_id_to_drop,
                "perception_dc": 0
            }
            self.room.objects.append(new_item_obj)
            db.save_room_state(self.room)
            self.player.send_message(f"You drop {item_name}.")

class Take(Get):
    pass

class Put(Drop):
    pass

class Pour(BaseVerb):
    """
    Handles 'pour'
    POUR <item> IN <target>
    """
    def execute(self):
        args_str = " ".join(self.args).lower()
        if " in " not in args_str:
            self.player.send_message("Usage: POUR <item> IN <target>")
            return
            
        parts = args_str.split(" in ", 1)
        target_item_name = parts[0].strip()
        target_container_name = parts[1].strip()
        
        # For now, just find item and fail gracefully since we don't have potion logic here yet
        item_id = _find_item_in_inventory(self.player, target_item_name)
        if not item_id:
             # Check hands too
             for slot in ["mainhand", "offhand"]:
                  hid = self.player.worn_items.get(slot)
                  if hid:
                       hdata = game_state.GAME_ITEMS.get(hid, {})
                       if target_item_name in hdata.get("keywords", []):
                            item_id = hid
                            break

        if not item_id:
            self.player.send_message(f"You don't have a '{target_item_name}'.")
            return

        self.player.send_message(f"You can't seem to find '{target_container_name}' to pour into.")