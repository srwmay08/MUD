# mud_backend/verbs/training.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.game_objects import Room
from mud_backend.core.db import fetch_room_data
from mud_backend.core.room_handler import show_room_to_player
from mud_backend import config
from mud_backend.core.skill_handler import (
    show_training_menu, 
    show_skill_list, 
    train_skill
)

class CheckIn(BaseVerb):
    """
    Handles the 'check in' command at the inn.
    Enters the 'training' game state.
    """
    def execute(self):
        # We only allow checking in at the inn
        if self.room.room_id != config.CHARGEN_START_ROOM:
            self.player.send_message("You can only check in at the inn.")
            return

        self.player.game_state = "training"
        self.player.send_message("You approach the front desk to review your skills...")
        
        # --- MODIFIED: Show list FIRST, then menu ---
        self.player.send_message("\n--- **All Skills** ---")
        show_skill_list(self.player, "all")
        show_training_menu(self.player)
        # ---
        

class List(BaseVerb):
    """
    Handles the 'list' command *while in the training state*.
    """
    def execute(self):
        if self.player.game_state != "training":
            self.player.send_message("You can only do that while you are training.")
            return
            
        if not self.args:
            category = "categories"
        else:
            category = " ".join(self.args)
        
        # --- MODIFIED: Show list FIRST, then menu ---
        show_skill_list(self.player, category)
        show_training_menu(self.player)
        # ---

class Train(BaseVerb):
    """
    Handles the 'train' command *while in the training state*.
    """
    def execute(self):
        if self.player.game_state != "training":
            self.player.send_message("You can only do that while you are training.")
            return

        if not self.args or len(self.args) < 2:
            self.player.send_message("Usage: TRAIN <skill name> <ranks>")
            return
            
        # Try to parse the rank number
        try:
            ranks_to_train = int(self.args[-1])
            skill_name = " ".join(self.args[:-1])
        except ValueError:
            ranks_to_train = 1
            skill_name = " ".join(self.args)
            
        if ranks_to_train <= 0:
            ranks_to_train = 1
            
        train_skill(self.player, skill_name, ranks_to_train)

class Done(BaseVerb):
    """
    Handles the 'done' command *while in the training state*.
    Exits training and returns to the appropriate room.
    """
    def execute(self):
        if self.player.game_state != "training":
            self.player.send_message("You are not currently training.")
            return
            
        # Check if this was the *first* training (at chargen)
        # We know this if the player is still in the "inn_room"
        # and their chargen_step indicates completion.
        if (self.player.current_room_id == config.CHARGEN_START_ROOM and
            self.player.chargen_step >= 99): # 99 is the "completed" step
            
            # This is the end of chargen!
            self.player.game_state = "playing"
            self.player.current_room_id = config.CHARGEN_COMPLETE_ROOM
            
            self.player.send_message("\nYou have finalized your training.")
            self.player.send_message("You feel the dream fade...")
            self.player.send_message("You open your eyes and find yourself in...")
            
            # Manually fetch the new room and use the room_handler to show it
            town_square_data = fetch_room_data(config.CHARGEN_COMPLETE_ROOM)
            new_room = Room(
                room_id=town_square_data.get("room_id"),
                name=town_square_data.get("name"),
                description=town_square_data.get("description"),
                db_data=town_square_data
            )
            # The player object's room ID is already updated, so this works
            show_room_to_player(self.player, new_room)
            
        else:
            # This was a normal training session
            self.player.game_state = "playing"
            self.player.send_message("You check out from the front desk and head back into the inn.")
            show_room_to_player(self.player, self.room)