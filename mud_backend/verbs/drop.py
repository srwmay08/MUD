# mud_backend/verbs/drop.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.item_utils import (
    clean_name, 
    find_item_in_hands, 
    find_item_in_inventory, 
    get_item_data
)
import uuid
import re

@VerbRegistry.register(["drop", "discard", "throw"])
class Drop(BaseVerb):
    def execute(self):
        if check_action_roundtime(self.player, action_type="other"):
            return
        if not self.args:
            self.player.send_message("Drop what?")
            return

        args_str = " ".join(self.args).lower()
        
        # --- SPECIAL: Drop in Well ---
        match = re.search(r'^(.*?) (in|down|into) (.*well.*)$', args_str)
        if match:
            target_item_name = match.group(1).strip()
            # Check if a well exists in room
            has_well = False
            well_obj = None
            for obj in self.room.objects:
                if "well" in obj.get("keywords", []) or "well" in obj.get("name", "").lower():
                    has_well = True
                    well_obj = obj
                    break
            
            if not has_well:
                if "well" not in self.room.name.lower():
                    self.player.send_message("There is no well here.")
                    return

            self._handle_well_drop(target_item_name, well_obj)
            return

        # --- STANDARD DROP ---
        is_confirmed = False
        if self.args[-1].lower() == "confirm":
            is_confirmed = True
            self.args = self.args[:-1] 
            args_str = " ".join(self.args).lower()

        target_item_name = clean_name(args_str)
        game_items = self.world.game_items
        
        item_ref, hand_slot = find_item_in_hands(self.player, game_items, target_item_name)
        from_inventory = False

        if not item_ref:
            item_ref = find_item_in_inventory(self.player, game_items, target_item_name)
            if item_ref:
                from_inventory = True

        if not item_ref:
            self.player.send_message(f"You don't have a '{target_item_name}'.")
            return

        item_data = get_item_data(item_ref, game_items)
        item_name = item_data.get("name", "the item")

        if self.player.flags.get("safedrop", "on") == "on" and not is_confirmed and self.command == "drop":
            self.player.send_message(f"SAFEDROP is on. To drop {item_name}, type 'DROP {target_item_name} CONFIRM'.")
            return

        self._perform_drop(item_ref, from_inventory, hand_slot, item_data)

    def _perform_drop(self, item_ref, from_inventory, hand_slot, item_data):
        if from_inventory:
            self.player.inventory.remove(item_ref)
        else:
            self.player.worn_items[hand_slot] = None

        new_obj = None
        if isinstance(item_ref, dict):
            new_obj = item_ref
            new_obj["is_item"] = True
            if "keywords" not in new_obj: new_obj["keywords"] = item_data.get("keywords", [])
            if "uid" not in new_obj: new_obj["uid"] = uuid.uuid4().hex
        else:
            item_keywords = [item_data.get("name", "item").lower()] + item_data.get("keywords", [])
            new_obj = {
                "item_id": item_ref, 
                "name": item_data.get("name", "item"), 
                "is_item": True, 
                "keywords": list(set(item_keywords)),
                "description": item_data.get("description", "It's an item."),
                "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"],
                "uid": uuid.uuid4().hex
            }
        
        self.room.objects.append(new_obj)
        
        if "objects" not in self.room.data:
            self.room.data["objects"] = []
        self.room.data["objects"].append(new_obj)

        self.player.send_message(f"You drop {new_obj['name']} on the ground.")
        
        # --- ADDED BROADCAST ---
        if not self.player.is_hidden:
            # FIX: Look up SID to skip properly
            player_info = self.world.get_player_info(self.player.name.lower())
            skip_sid = player_info.get("sid") if player_info else None
            
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} drops {new_obj['name']}.", 
                "message", 
                skip_sid=skip_sid
            )
        # -----------------------

        self.world.save_room(self.room)
        set_action_roundtime(self.player, 1.0)

    def _handle_well_drop(self, target_item_name, well_obj):
        item_ref, hand_slot = find_item_in_hands(self.player, self.world.game_items, target_item_name)
        from_inventory = False
        if not item_ref:
            item_ref = find_item_in_inventory(self.player, self.world.game_items, target_item_name)
            from_inventory = True
        
        if not item_ref:
            self.player.send_message(f"You don't have a '{target_item_name}'.")
            return

        item_data = get_item_data(item_ref, self.world.game_items)
        item_name = item_data.get("name", "item")

        if from_inventory:
            self.player.inventory.remove(item_ref)
        else:
            self.player.worn_items[hand_slot] = None

        self.player.send_message(f"You drop the {item_name} into the well. It falls into the darkness...")
        
        # FIX: Look up SID to skip properly
        player_info = self.world.get_player_info(self.player.name.lower())
        skip_sid = player_info.get("sid") if player_info else None
        
        self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} drops {item_name} into the well.", "message", skip_sid=skip_sid)

        target_room_id = "well_bottom" 
        
        # FIX: Use world.get_room instead of world.room_handler.get_room (which caused the error)
        target_room_data = self.world.get_room(target_room_id)
        
        # If the bottom room is active (someone is down there), we need that instance.
        target_room_active = self.world.active_rooms.get(target_room_id)
        
        if target_room_active:
            # Real-time update
            target_room = target_room_active
            new_obj = None
            if isinstance(item_ref, dict):
                new_obj = item_ref
            else:
                new_obj = {
                    "item_id": item_ref,
                    "name": item_name,
                    "is_item": True,
                    "uid": uuid.uuid4().hex
                }
            target_room.objects.append(new_obj)
            self.world.save_room(target_room)
            self.world.broadcast_to_room(target_room_id, f"Something splashes into the water from above: {item_name}", "message")
            
        elif target_room_data:
            # Offline update (room not loaded)
            new_obj = None
            if isinstance(item_ref, dict):
                new_obj = item_ref
            else:
                new_obj = {
                    "item_id": item_ref,
                    "name": item_name,
                    "is_item": True,
                    "uid": uuid.uuid4().hex
                }
            
            if "objects" not in target_room_data:
                target_room_data["objects"] = []
            target_room_data["objects"].append(new_obj)
            
        else:
            print(f"[ERROR] Well drop target '{target_room_id}' not found.")
            
        set_action_roundtime(self.player, 1.0)