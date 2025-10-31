# mud_backend/verbs/move.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_room_data
from mud_backend.core.game_objects import Room
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core.command_executor import DIRECTION_MAP

# We import the Enter class to borrow its logic
from mud_backend.verbs.enter import Enter

class Move(BaseVerb):
    """
    Handles all directional movement (n, s, go north) AND
    object-based movement (go door).
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Move where? (e.g., NORTH, SOUTH, E, W, etc.)")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Normalize the direction (e.g., "n" -> "north")
        normalized_direction = DIRECTION_MAP.get(target_name, target_name)
        
        # --- CHECK 1: Is it a cardinal exit? ---
        target_room_id = self.room.exits.get(normalized_direction)
        
        if target_room_id:
            # --- Found a cardinal exit ---
            new_room_data = fetch_room_data(target_room_id)
            if not new_room_data or new_room_data.get("room_id") == "void":
                self.player.send_message("You move, but find only an endless void.")
                return
            
            new_room = Room(
                room_id=new_room_data["room_id"],
                name=new_room_data["name"],
                description=new_room_data["description"],
                db_data=new_room_data
            )
            self.player.current_room_id = target_room_id
            self.player.send_message(f"You move {normalized_direction}...")
            show_room_to_player(self.player, new_room)
            return

        # --- CHECK 2: Is it an object you can 'enter'? ---
        # (This handles 'go door', 'move door')
        enterable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "ENTER" in obj.get("verbs", [])), None)
                                 
        if enterable_object:
            # --- Found an enterable object ---
            # We can just create an instance of the Enter verb and run it
            enter_verb = Enter(self.player, self.room, self.args)
            enter_verb.execute()
            return

        # --- If neither, fail ---
        self.player.send_message("You cannot go that way.")