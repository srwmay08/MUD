# verbs/say.py
from .base_verb import BaseVerb # RESTORED: Relative import now works with correct package structure

class Say(BaseVerb): # RESTORED: Standard inheritance
    """Handles the 'say' command."""

    def execute(self):
        # The 'say' verb logic
        if not self.args:
            self.player.send_message("What do you want to say?")
            return

        message = " ".join(self.args)

        # Output for the player
        self.player.send_message(f"You say, \"{message}\"")

        # Output that would be sent to others in the room
        # (This requires a message queue system, but we'll simulate the text)
        print(f"[To Room] {self.player.name} says, \"{message}\"")