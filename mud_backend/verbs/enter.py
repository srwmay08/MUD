# mud_backend/verbs/enter.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_room_data
from mud_backend.core.game_objects import Room
# --- NEW IMPORT ---
from mud_backend.core.room_handler import show_room_to_player

class Enter(BaseVerb):
    """Handles the 'enter' command to move through doors, portals, etc."""
    
    def execute(self):
        if not self.args:
            self.player.send_message("Enter what?")
            return

        target_name = " ".join(self.args).lower()
        
        # 1. Find the object the player wants to enter
        enterable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "ENTER" in obj.get("verbs", [])), None)

        if not enterable_object:
            self.player.send_message(f"You cannot enter the **{target_name}**.")
            return

        target_room_id = enterable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return

        # 2. Fetch new room data
        new_room_data = fetch_room_data(target_room_id)
        if not new_room_data or new_room_data.get("room_id") == "void":
            self.player.send_message("You try to enter, but find only an endless void. You quickly scramble back.")
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
        self.player.send_message(f"You enter the {target_name}...")
        show_room_to_player(self.player, new_room)