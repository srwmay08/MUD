# mud_backend/verbs/exit.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_room_data
from mud_backend.core.game_objects import Room
from mud_backend.core.room_handler import show_room_to_player

class Exit(BaseVerb):
    """Handles the 'exit' and 'out' commands."""
    
    def execute(self):
        # 1. Find the "out" exit in the current room
        target_room_id = self.room.exits.get("out")

        if not target_room_id:
            self.player.send_message("You cannot go out that way.")
            return

        # 2. Fetch new room data
        new_room_data = fetch_room_data(target_room_id)
        if not new_room_data or new_room_data.get("room_id") == "void":
            self.player.send_message("You try to leave, but find only an endless void.")
            return
            
        new_room = Room(
            room_id=new_room_data["room_id"],
            name=new_room_data["name"],
            description=new_room_data["description"],
            db_data=new_room_data
        )

        # 3. Change the player's room
        self.player.current_room_id = target_room_id
        
        # 4. Success message and automatic "Look"
        self.player.send_message("You head out...")
        show_room_to_player(self.player, new_room)