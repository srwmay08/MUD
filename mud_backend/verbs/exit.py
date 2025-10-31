# mud_backend/verbs/exit.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_room_data
from mud_backend.core.game_objects import Room
from mud_backend.core.room_handler import show_room_to_player

# We import the Enter class to borrow its logic
from mud_backend.verbs.enter import Enter

class Exit(BaseVerb):
    """
    Handles the 'exit' and 'out' commands.
    Tries to find a special "out" exit first.
    If that fails, or if args are given (e.g., "exit door"),
    it tries to find an enterable object.
    """
    
    def execute(self):
        
        if not self.args:
            # --- CHECK 1: Handle 'exit' or 'out' (no args) ---
            # Try to find the special "out" exit
            target_room_id = self.room.exits.get("out")

            if target_room_id:
                # --- Found the "out" exit ---
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
                self.player.current_room_id = target_room_id
                self.player.send_message("You head out...")
                show_room_to_player(self.player, new_room)
                return
            else:
                # --- No "out" exit, try to "enter door" ---
                # This handles being in the inn and typing "exit"
                enter_verb = Enter(self.player, self.room, ["door"])
                enter_verb.execute()
                return

        else:
            # --- CHECK 2: Handle 'exit <object>' (e.g., "exit door") ---
            # This is the same as "enter <object>"
            enter_verb = Enter(self.player, self.room, self.args)
            enter_verb.execute()
            return