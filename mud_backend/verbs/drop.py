# mud_backend/verbs/drop.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.item_actions import (
    _clean_name, 
    _find_item_in_hands, 
    _find_item_in_inventory, 
    _get_item_data
)
import uuid

@VerbRegistry.register(["drop", "discard"])
class Drop(BaseVerb):
    def execute(self):
        if _check_action_roundtime(self.player, action_type="other"):
            return
        if not self.args:
            self.player.send_message("Drop what?")
            return

        is_confirmed = False
        if self.args[-1].lower() == "confirm":
            is_confirmed = True
            self.args = self.args[:-1]

        args_str = " ".join(self.args).lower()
        target_item_name = _clean_name(args_str)
        game_items = self.world.game_items
        
        # Logic to find item to drop (Hands -> Inventory)
        item_ref, hand_slot = _find_item_in_hands(self.player, game_items, target_item_name)
        from_inventory = False

        if not item_ref:
            item_ref = _find_item_in_inventory(self.player, game_items, target_item_name)
            if item_ref:
                from_inventory = True

        if not item_ref:
            self.player.send_message(f"You don't have a '{target_item_name}'.")
            return

        item_data = _get_item_data(item_ref, game_items)
        item_name = item_data.get("name", "the item")

        # SAFEDROP Check
        if self.player.flags.get("safedrop", "on") == "on" and not is_confirmed and self.command == "drop":
            self.player.send_message(f"SAFEDROP is on. To drop {item_name}, type 'DROP {target_item_name} CONFIRM'.")
            return

        # Perform the drop
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
            item_keywords = [item_name.lower()] + item_name.lower().split()
            new_obj = {
                "item_id": item_ref, 
                "name": item_name, 
                "is_item": True, 
                "keywords": list(set(item_keywords)),
                "description": item_data.get("description", "It's an item."),
                "verbs": ["GET", "LOOK", "EXAMINE", "TAKE"],
                "uid": uuid.uuid4().hex
            }
        
        # Add to active room
        self.room.objects.append(new_obj)
        
        # --- SYNC WITH PERSISTENT DATA ---
        if "objects" not in self.room.data:
            self.room.data["objects"] = []
        self.room.data["objects"].append(new_obj)
        # ---------------------------------

        self.player.send_message(f"You drop {item_name} on the ground.")
        self.world.save_room(self.room)
        _set_action_roundtime(self.player, 1.0)