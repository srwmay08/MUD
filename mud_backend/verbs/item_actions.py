# mud_backend/verbs/item_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import db
from typing import Dict, Any
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
import time

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

def _find_item_in_inventory(player, game_items_data: Dict[str, Any], target_name: str) -> str | None:
    """Finds the first item_id in a player's inventory that matches."""
    for item_id in player.inventory:
        item_data = game_items_data.get(item_id)
        if item_data:
            if (target_name == item_data.get("name", "").lower() or 
                target_name in item_data.get("keywords", [])):
                return item_id
    return None

def _find_container_on_player(player, game_items_data: Dict[str, Any], target_name: str) -> Dict[str, Any] | None:
    """Finds a container item on the player (worn or in inventory)."""
    for slot, item_id in player.worn_items.items():
        if item_id:
            item_data = game_items_data.get(item_id)
            if item_data and item_data.get("is_container"):
                search_keywords = item_data.get("keywords", []) + [item_id]
                if (target_name == item_data.get("name", "").lower() or
                    target_name in search_keywords):
                    item_data_with_id = item_data.copy()
                    item_data_with_id["_runtime_item_id"] = item_id
                    return item_data_with_id

    for item_id in player.inventory:
        item_data = game_items_data.get(item_id)
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
        if _check_action_roundtime(self.player, action_type="other"):
            return

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

        right_hand_slot = "mainhand"
        left_hand_slot = "offhand"
        target_hand_slot = None
        if self.player.worn_items.get(right_hand_slot) is None:
            target_hand_slot = right_hand_slot
        elif self.player.worn_items.get(left_hand_slot) is None:
            target_hand_slot = left_hand_slot

        game_items = self.world.game_items

        # ---
        # BRANCH 1: GET <item> FROM <container>
        # ---
        if target_container_name:
            container = _find_container_on_player(self.player, game_items, target_container_name)
            
            if not container or container.get("wearable_slot") != "back":
                self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                return

            item_id = _find_item_in_inventory(self.player, game_items, target_item_name)
            
            if not item_id:
                self.player.send_message(f"You don't have a {target_item_name} in your {container.get('name')}.")
                return
            
            item_data = game_items.get(item_id, {})
            item_name = item_data.get("name", "an item")

            if not target_hand_slot:
                self.player.send_message("Your hands are full. You must free a hand to get that.")
                return
                
            self.player.inventory.remove(item_id)
            self.player.worn_items[target_hand_slot] = item_id
            self.player.send_message(f"You get {item_name} from your {container.get('name')} and hold it.")

            # ---
            # --- MODIFIED: Tutorial Hook (Final Step)
            # ---
            if (item_id == "inn_note" and 
                "intro_stow" in self.player.completed_quests and
                "intro_lookatnote_or_leave" not in self.player.completed_quests):
                
                self.player.send_message(
                    "\n<span class='keyword' data-command='help look'>[Help: LOOK AT]</span> - You've mastered the basics of item management! "
                    "You can read the note again by <span class='keyword' data-command='look at note'>LOOK AT NOTE</span>. "
                    "When you're ready, <span class='keyword' data-command='out'>OUT</span> to leave the room and find the innkeeper."
                )
                self.player.completed_quests.append("intro_lookatnote_or_leave")
            # ---
            # --- END MODIFIED
            # ---
            
            _set_action_roundtime(self.player, 1.0) # 1s RT for getting from pack
            
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
                     self.player.inventory.append(item_id)
                     self.player.send_message(f"Both hands are full. You get {item_name} and put it in your pack.")
                else:
                     self.player.worn_items[target_hand_slot] = item_id
                     self.player.send_message(f"You get {item_name} and hold it.")
                
                self.room.objects.remove(item_obj)
                self.world.save_room(self.room)
                
                # ---
                # --- MODIFIED: Tutorial Hook (Step 2: Look At Note)
                # ---
                if (item_id == "inn_note" and 
                    "intro_get" in self.player.completed_quests and
                    "intro_lookatnote" not in self.player.completed_quests):
                    
                    self.player.send_message(
                        "\n<span class='keyword' data-command='help look'>[Help: LOOK AT]</span> - You are now holding the note. "
                        "To read it, you can <span class='keyword' data-command='look at note'>LOOK AT NOTE</span>."
                    )
                    self.player.completed_quests.append("intro_lookatnote")
                # --- END MODIFIED ---

                return

            # If not on ground, try to find item in inventory (to hold it)
            item_id_from_pack = _find_item_in_inventory(self.player, game_items, target_item_name)
            if not item_id_from_pack:
                self.player.send_message(f"You don't see a **{target_item_name}** here or in your pack.")
                return

            if not target_hand_slot:
                self.player.send_message("Your hands are full. You must free a hand to get that from your pack.")
                return

            self.player.inventory.remove(item_id_from_pack)
            self.player.worn_items[target_hand_slot] = item_id_from_pack
            item_name = game_items.get(item_id_from_pack, {}).get("name", "an item")
            self.player.send_message(f"You get {item_name} from your pack and hold it.")
            
            # ---
            # --- MODIFIED: Tutorial Hook (Final Step)
            # ---
            if (item_id_from_pack == "inn_note" and 
                "intro_stow" in self.player.completed_quests and
                "intro_lookatnote_or_leave" not in self.player.completed_quests):
                
                self.player.send_message(
                    "\n<span class='keyword' data-command='help look'>[Help: LOOK AT]</span> - You've mastered the basics of item management! "
                    "You can read the note again by <span class='keyword' data-command='look at note'>LOOK AT NOTE</span>. "
                    "When you're ready, <span class='keyword' data-command='out'>OUT</span> to leave the room and find the innkeeper."
                )
                self.player.completed_quests.append("intro_lookatnote_or_leave")
            # ---
            # --- END MODIFIED
            # ---

            _set_action_roundtime(self.player, 1.0) # 1s RT for getting from pack


class Drop(BaseVerb):
    """
    Handles 'drop' and 'put'.
    DROP <item>
    PUT <item> IN <container>
    STOW <item> (defaults to 'put in backpack')
    """
    
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return

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

        item_id_to_drop = None
        item_location = None
        
        for slot in ["mainhand", "offhand"]:
            item_id = self.player.worn_items.get(slot)
            if item_id:
                item_data = game_items.get(item_id, {})
                if (target_item_name == item_data.get("name", "").lower() or 
                    target_item_name in item_data.get("keywords", [])):
                    item_id_to_drop = item_id
                    item_location = slot
                    break
        
        if not item_id_to_drop:
            item_id_to_drop = _find_item_in_inventory(self.player, game_items, target_item_name)
            if item_id_to_drop:
                item_location = "inventory"

        if not item_id_to_drop:
            self.player.send_message(f"You don't seem to have a {target_item_name}.")
            return
            
        item_data = game_items.get(item_id_to_drop)
        item_name = item_data.get("name", "an item")

        if target_container_name:
            # --- PUT IN CONTAINER ---
            container = _find_container_on_player(self.player, game_items, target_container_name)
            
            if not container:
                 self.player.send_message(f"You don't have a container called '{target_container_name}'.")
                 return

            if container.get("_runtime_item_id") == item_id_to_drop:
                 self.player.send_message("You can't put something inside itself!")
                 return

            if container.get("wearable_slot") == "back":
                if item_location == "inventory":
                    self.player.send_message(f"The {item_name} is already in your pack.")
                    return
                
                self.player.worn_items[item_location] = None
                self.player.inventory.append(item_id_to_drop)
                self.player.send_message(f"You put {item_name} in your {container.get('name')}.")
            else:
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
            self.world.save_room(self.room)
            self.player.send_message(f"You drop {item_name}.")
        
        _set_action_roundtime(self.player, 1.0) # 1s RT for dropping/putting


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
        if _check_action_roundtime(self.player, action_type="other"):
            return
        
        args_str = " ".join(self.args).lower()
        if " in " not in args_str:
            self.player.send_message("Usage: POUR <item> IN <target>")
            return
            
        parts = args_str.split(" in ", 1)
        target_item_name = parts[0].strip()
        target_container_name = parts[1].strip()
        
        game_items = self.world.game_items
        
        item_id = _find_item_in_inventory(self.player, game_items, target_item_name)
        if not item_id:
             for slot in ["mainhand", "offhand"]:
                  hid = self.player.worn_items.get(slot)
                  if hid:
                       hdata = game_items.get(hid, {})
                       if target_item_name in hdata.get("keywords", []):
                            item_id = hid
                            break

        if not item_id:
            self.player.send_message(f"You don't have a '{target_item_name}'.")
            return

        self.player.send_message(f"You can't seem to find '{target_container_name}' to pour into.")
        
        _set_action_roundtime(self.player, 2.0)