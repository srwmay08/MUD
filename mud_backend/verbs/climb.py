# verbs/climb.py
from mud_backend.verbs.base_verb import BaseVerb
# --- NEW IMPORTS ---
from mud_backend.core.db import fetch_room_data
from mud_backend.core.game_objects import Room # Need this to create a Room object
from mud_backend.core.room_handler import show_room_to_player # <-- IMPORT THIS

class Climb(BaseVerb):
    """Handles the 'climb' command to move between connected objects (like wells/ropes)."""
    
    def execute(self):
        if not self.args:
            self.player.send_message("Climb what? (e.g., CLIMB ROPE or CLIMB WELL)")
            return

        target_name = self.args[0].lower()
        
        # 1. Find the object
        climbable_object = next((obj for obj in self.room.objects 
                                 if obj['name'].lower() == target_name and "CLIMB" in obj.get("verbs", [])), None)

        if not climbable_object:
            self.player.send_message(f"You cannot climb the **{target_name}** here.")
            return

        target_room_id = climbable_object.get("target_room")

        if not target_room_id:
            self.player.send_message(f"The {target_name} leads nowhere right now.")
            return
            
        # --- NEW LOGIC: Fetch new room data ---
        new_room_data = fetch_room_data(target_room_id)
        if not new_room_data or new_room_data.get("room_id") == "void":
            self.player.send_message("You climb, but find only an endless void. You quickly scramble back.")
            return
            
        # Create a temporary Room object for the destination
        new_room = Room(
            room_id=new_room_data["room_id"],
            name=new_room_data["name"],
            description=new_room_data["description"],
            db_data=new_room_data
        )
        # --- END NEW LOGIC ---

        # 2. Change the player's room
        self.player.current_room_id = target_room_id
        
        # 3. Success message
        self.player.send_message(f"You grasp the {target_name} and begin to climb...")
        self.player.send_message(f"After a few moments, you arrive.")

        # 4. --- NEW: Automatic "Look" ---
        # We now use the central function to show everything
        show_room_to_player(self.player, new_room)
        
        # The main executor will save the player state after this verb runs.