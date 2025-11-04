# mud_backend/verbs/movement.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_room_data
from mud_backend.core.game_objects import Room
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core.command_executor import DIRECTION_MAP
# --- NEW IMPORT ---
from mud_backend.core import game_state

# --- Class from enter.py ---
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
        # --- FIX: Get from live game_state cache, not stale DB ---
        new_room_data = game_state.GAME_ROOMS.get(target_room_id)
        # --- END FIX ---
        
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

# --- Class from climb.py ---
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
            
        # 2. Fetch new room data
        # --- FIX: Get from live game_state cache, not stale DB ---
        new_room_data = game_state.GAME_ROOMS.get(target_room_id)
        # --- END FIX ---
        
        if not new_room_data or new_room_data.get("room_id") == "void":
            self.player.send_message("You climb, but find only an endless void. You quickly scramble back.")
            return
            
        new_room = Room(
            room_id=new_room_data["room_id"],
            name=new_room_data["name"],
            description=new_room_data["description"],
            db_data=new_room_data
        )

        # 3. Change the player's room
        self.player.current_room_id = target_room_id
        
        # 4. Success message
        self.player.send_message(f"You grasp the {target_name} and begin to climb...")
        self.player.send_message(f"After a few moments, you arrive.")

        # 5. Automatic "Look"
        show_room_to_player(self.player, new_room)

# --- Class from move.py ---
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
            # --- FIX: Get from live game_state cache, not stale DB ---
            new_room_data = game_state.GAME_ROOMS.get(target_room_id)
            # --- END FIX ---
            
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
            # No import needed, class is in the same file!
            enter_verb = Enter(self.player, self.room, self.args)
            enter_verb.execute()
            return

        # --- If neither, fail ---
        self.player.send_message("You cannot go that way.")

# --- Class from exit.py ---
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
                # --- FIX: Get from live game_state cache, not stale DB ---
                new_room_data = game_state.GAME_ROOMS.get(target_room_id)
                # --- END FIX ---
                
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