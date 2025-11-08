# mud_backend/verbs/training.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.skill_handler import (
    show_skill_list, 
    train_skill, 
    _perform_conversion_and_train
)
from mud_backend import config
import re

class CheckIn(BaseVerb):
    """
    Handles the 'checkin' command.
    Allows a player to enter the training state.
    """
    def execute(self):
        # We'll assume the inn is in 'ts_south' for now
        if self.room.room_id not in ["ts_south", "inn_room"]:
            self.player.send_message("You must be at the inn to check in for training.")
            return

        self.player.send_message("You check in at the inn, ready to train.")
        self.player.game_state = "training"
        
        # Show the full skill list by default
        show_skill_list(self.player, "all")

class List(BaseVerb):
    """
    Handles the 'list' command *during training*.
    """
    def execute(self):
        category = " ".join(self.args).lower()
        if not category:
            category = "all"
        
        show_skill_list(self.player, category)

class Train(BaseVerb):
    """
    Handles the 'train' command *during training*.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: TRAIN <skill name> <ranks> (e.g., TRAIN ARMOR USE 1)")
            return

        args_str = " ".join(self.args).lower()

        # 1. Handle CONFIRM/CANCEL
        pending_training = self.player.db_data.get('_pending_training')
        
        if args_str == "confirm":
            if not pending_training:
                self.player.send_message("You have no pending training to confirm.")
                return
            
            _perform_conversion_and_train(self.player, pending_training)
            return
            
        elif args_str == "cancel":
            if not pending_training:
                self.player.send_message("You have no pending training to cancel.")
                return
            
            self.player.db_data.pop('_pending_training', None)
            self.player.send_message("Pending training canceled.")
            return
        
        # 2. Handle a new training request
        if pending_training:
            self.player.send_message("You have pending training. Please 'TRAIN CONFIRM' or 'TRAIN CANCEL' first.")
            return

        # 3. Parse the command (e.g., "train armor use 1")
        ranks_to_train = 1
        skill_name = args_str
        
        # Find if the last argument is a number
        match = re.search(r'(\d+)$', args_str)
        if match:
            try:
                ranks_to_train = int(match.group(1))
                # Get the skill name, which is everything *before* the number
                skill_name = args_str[:match.start()].strip()
            except ValueError:
                ranks_to_train = 1 # Not a valid number, assume 1
                skill_name = args_str
        
        if not skill_name:
            self.player.send_message("Usage: TRAIN <skill name> <ranks> (e.g., TRAIN ARMOR USE 1)")
            return

        # 4. Call the skill_handler function
        train_skill(self.player, skill_name, ranks_to_train)

class Done(BaseVerb):
    """
    Handles the 'done' command *during training*.
    Moves the player out of chargen/training and into the game.
    """
    def execute(self):
        self.player.send_message("You finish your training and head out into the world.")
        self.player.game_state = "playing"
        
        # Set HP to max after chargen
        self.player.hp = self.player.max_hp
        
        # Move player to the town square to start the game
        # (This also handles broadcasting their arrival)
        self.player.move_to_room(config.CHARGEN_COMPLETE_ROOM, "You exit the inn.")