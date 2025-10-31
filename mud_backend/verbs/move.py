# mud_backend/verbs/move.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.db import fetch_room_data
from mud_backend.core.game_objects import Room

class Move(BaseVerb):
    """
    Handles all directional movement by checking the room's exit data.
    Assumes the argument has already been normalized (e.g., "north", "south").
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Move where? (e.g., NORTH, SOUTH, E, W, etc.)")
            return

        # The command executor has already normalized the direction
        move_direction = self.args[0] # e.g., "north"

        # 1. Find the exit in the current room's exit dictionary
        target_room_id = self.room.exits.get(move_direction)

        if not target_room_id:
            self.player.send_message("You cannot go that way.")
            return

        # 2. Fetch new room data
        new_room_data = fetch_room_data(target_room_id)
        if not new_room_data or new_room_data.get("room_id") == "void":
            self.player.send_message("You move, but find only an endless void. You quickly scramble back.")
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
        self.player.send_message(f"You move {move_direction}...")

        # Send the "look" data
        self.player.send_message(f"**{new_room.name}**")
        self.player.send_message(new_room.description)
        
        if new_room.objects:
            html_objects = []
            for obj in new_room.objects:
                obj_name = obj['name']
                verbs = obj.get('verbs', ['look'])
                verb_str = ','.join(verbs).lower()
                html_objects.append(
                    f'<span class="keyword" data-name="{obj_name}" data-verbs="{verb_str}">{obj_name}</span>'
                )
            self.player.send_message(f"\nObvious objects here: {', '.join(html_objects)}.")