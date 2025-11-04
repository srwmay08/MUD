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
                if (target_name == item_data.get("name", "").lower() or
                    target_name in item_data.get("keywords", [])):
                    return item_data

    # Check inventory containers (like a small pouch)
    for item_id in player.inventory:
        item_data = game_state.GAME_ITEMS.get(item_id)
        if item_data and item_data.get("is_container"):
            if (target_name == item_data.get("name", "").lower() or
                target_name in item_data.get("keywords", [])):
                return item_data
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

        # --- NEW PARSER ---
        args_str = " ".join(self.args).lower()
        target_item_name = args_str
        target_container_name = None

        if " from " in args_str:
            parts = args_str.split(" from ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
            # --- THIS IS THE FIX ---
            if target_container_name.startswith("my "):
                target_container_name = target_container_name[3:].strip()
            # --- END FIX ---
        # --- END NEW PARSER ---

        # 1. Determine which hand to put it in (helper logic)
        right_hand_slot = "mainhand"
        left_hand_slot = "offhand"
        
        # Find the first available hand
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
                
            # Special check for shield/bow (left hand)
            item_type = item_data.get("item_type")
            if item_type in ["shield"] or item_data.get("skill") in ["bows", "crossbows"]:
                if self.player.worn_items.get(left_hand_slot) is None:
                    target_hand_slot = left_hand_slot
                # If preferred slot (left) is full, it will use the other (right) if free.
            else:
                 if self.player.worn_items.get(right_hand_slot) is None:
                    target_hand_slot = right_hand_slot
                # If preferred slot (right) is full, it will use the other (left) if free.
            
            # Re-check target_hand_slot after preferred logic
            if target_hand_slot is None:
                if self.player.worn_items.get(right_hand_slot) is None:
                    target_hand_slot = right_hand_slot
                elif self.player.worn_items.get(left_hand_slot) is None:
                    target_hand_slot = left_hand_slot
                else:
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
            # --- THIS IS THE FIX: Check ground first ---
            item_obj = _find_item_in_room(self.room.objects, target_item_name)
            
            if item_obj:
                # Found it on the ground!
                item_id = item_obj.get("item_id")
                item_name = item_obj.get("name", "an item")
                item_data = game_state.GAME_ITEMS.get(item_id, {})

                if not item_id:
                    self.player.send_message(f"You can't seem to pick up the {item_name}.")
                    return

                # Determine target slot (again, with item-specific logic)
                target_hand_slot_ground = None # Re-check for ground logic
                item_type = item_data.get("item_type")
                
                if item_type in ["shield"] or item_data.get("skill") in ["bows", "crossbows"]:
                    if self.player.worn_items.get(left_hand_slot) is None:
                        target_hand_slot_ground = left_hand_slot
                    elif self.player.worn_items.get(right_hand_slot) is None:
                        target_hand_slot_ground = right_hand_slot
                else:
                    if self.player.worn_items.get(right_hand_slot) is None:
                        target_hand_slot_ground = right_hand_slot
                    elif self.player.worn_items.get(left_hand_slot) is None:
                        target_hand_slot_ground = left_hand_slot
                
                # Add to the free hand (if one was found)
                if target_hand_slot_ground:
                    self.player.worn_items[target_hand_slot_ground] = item_id
                    self.player.send_message(f"You get {item_name} and hold it in your {target_hand_slot_ground.replace('hand', ' hand')}.")
                else:
                    # Both hands are full, put it in the pack
                    self.player.inventory.append(item_id)
                    self.player.send_message(f"Both hands are full. You get {item_name} and put it in your pack.")
                
                # --- BUG FIX: Remove from the live room.objects list ---
                self.room.objects.remove(item_obj)
                
                # Save the room state
                db.save_room_state(self.room)
                return # <-- IMPORTANT: Stop here
            # --- END GROUND CHECK ---

            # If not on ground, try to find item in inventory
            item_id_from_pack = _find_item_in_inventory(self.player, target_item_name)
            if not item_id_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here or in your pack.")
                return

            # Found it in the pack! Treat as "get from backpack"
            item_data = game_state.GAME_ITEMS.get(item_id_from_pack, {})
            item_name = item_data.get("name", "an item")

            # Check for free hands
            if not target_hand_slot:
                self.player.send_message("Your hands are full. You must free a hand to get that.")
                return
            
            # Special check for shield/bow (left hand)
            item_type = item_data.get("item_type")
            if item_type in ["shield"] or item_data.get("skill") in ["bows", "crossbows"]:
                if self.player.worn_items.get(left_hand_slot) is None:
                    target_hand_slot = left_hand_slot
            else:
                if self.player.worn_items.get(right_hand_slot) is None:
                    target_hand_slot = right_hand_slot
            
            # Re-check target_hand_slot after preferred logic
            if target_hand_slot is None:
                if self.player.worn_items.get(right_hand_slot) is None:
                    target_hand_slot = right_hand_slot
                elif self.player.worn_items.get(left_hand_slot) is None:
                    target_hand_slot = left_hand_slot
                else:
                    self.player.send_message("Your hands are full. You must free a hand to get that.")
                    return

            # Move from inventory to hand
            self.player.inventory.remove(item_id_from_pack)
            self.player.worn_items[target_hand_slot] = item_id_from_pack
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

        # Simple parser for "drop item" vs "drop item in container"
        args_str = " ".join(self.args).lower()
        target_item_name = args_str
        target_container_name = None

        if " in " in args_str:
            parts = args_str.split(" in ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
        elif " on " in args_str: # for "put item on table"
            parts = args_str.split(" on ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip() # Treat 'table' as a container for now
        
        # --- THIS IS THE FIX for STOW default ---
        elif self.command == "stow":
            target_item_name = args_str
            # Find their main container
            backpack = _find_container_on_player(self.player, "backpack")
            if backpack:
                target_container_name = "backpack"
        # --- END FIX ---
            
        if target_container_name and target_container_name.startswith("my "):
            target_container_name = target_container_name[3:].strip()
        # --- END FIX ---

        # 1. Find the item on the player (hands first, then inventory)
        item_id_to_drop = None
        item_location = None
        
        # Check hands
        for slot in ["mainhand", "offhand"]:
            item_id = self.player.worn_items.get(slot)
            if item_id:
                item_data = game_state.GAME_ITEMS.get(item_id, {})
                if (target_item_name == item_data.get("name", "").lower() or 
                    target_item_name in item_data.get("keywords", [])):
                    item_id_to_drop = item_id
                    item_location = slot
                    break
        
        # If not in hands, check inventory
        if not item_id_to_drop:
            item_id_to_drop = _find_item_in_inventory(self.player, target_item_name)
            if item_id_to_drop:
                item_location = "inventory"

        if not item_id_to_drop:
            self.player.send_message(f"You don't seem to have a {target_item_name}.")
            return
            
        item_data = game_state.GAME_ITEMS.get(item_id_to_drop)
        item_name = item_data.get("name", "an item")

        # 2. Handle the destination (container or ground)
        if target_container_name:
            # --- PUT IN CONTAINER ---
            container = _find_container_on_player(self.player, target_container_name)
            
            # For now, we only support putting things in the 'backpack' (main inventory)
            # This logic needs to be expanded when containers have their own inventories
            if container and container.get("wearable_slot") == "back":
                if item_location == "inventory":
                    self.player.send_message(f"The {item_name} is already in your pack.")
                    return
                
                # Move from hand to inventory
                self.player.worn_items[item_location] = None # Empty hand
                self.player.inventory.append(item_id_to_drop) # Add to pack
                self.player.send_message(f"You put {item_name} in your {container.get('name')}.")
            else:
                self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                return
        else:
            # --- DROP ON GROUND ---
            # Remove from player
            if item_location == "inventory":
                self.player.inventory.remove(item_id_to_drop)
            else:
                self.player.worn_items[item_location] = None # Empty hand
            
            # --- FIX for persistence ---
            item_data = game_state.GAME_ITEMS.get(item_id_to_drop)
            item_name = item_data.get("name", "an unknown item")
            item_keywords = [
                item_name.lower(), 
                item_id_to_drop.lower()
            ] + item_name.lower().split()

            new_item_obj = {
                "name": item_name,
                "description": item_data.get("description", "It's an item."),
                "keywords": list(set(item_keywords)),
                "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"],
                "is_item": True,
                "item_id": item_id_to_drop,
                "perception_dc": 0
            }
            
            # Add to the live room.objects list
            self.room.objects.append(new_item_obj)
            # --- END FIX ---

            db.save_room_state(self.room)
            self.player.send_message(f"You drop {item_name}.")

# --- Aliases ---
class Take(Get):
    pass

class Put(Drop):
    pass

# --- NEW VERB ---
class Pour(BaseVerb):
    """
    Handles 'pour'
    POUR <item> IN <target>
    """
    
    def execute(self):
        args_str = " ".join(self.args).lower()
        target_item_name = ""
        target_container_name = ""

        if " in " in args_str:
            parts = args_str.split(" in ", 1)
            target_item_name = parts[0].strip()
            target_container_name = parts[1].strip()
        else:
            self.player.send_message("Usage: POUR <item> IN <target>")
            return

        if not target_item_name or not target_container_name:
            self.player.send_message("Usage: POUR <item> IN <target>")
            return
            
        # 1. Find the item
        item_id = _find_item_in_inventory(self.player, target_item_name)
        if not item_id:
            self.player.send_message(f"You don't have a '{target_item_name}'.")
            return
            
        item_data = game_state.GAME_ITEMS.get(item_id)
        if item_data.get("use_verb") not in ["drink", "pour"]:
            self.player.send_message(f"You can't pour {item_data.get('name')}.")
            return
            
        # 2. Find the target
        # For now, we only check for other players
        
        # TODO: Add logic to find other players
        
        self.player.send_message(f"You can't seem to find '{target_container_name}' to pour into.")