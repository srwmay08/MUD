# verbs/look.py
from .base_verb import BaseVerb # RESTORED: Relative import now works with correct package structure

class Look(BaseVerb): # RESTORED: Standard inheritance
    """Handles the 'look' command."""

    def execute(self):
        # The 'look' verb logic
        if not self.args:
            # Player is looking at the current room
            self.player.send_message(f"**{self.room.name}**")
            self.player.send_message(self.room.description)
            self.player.send_message("You see a few other people standing around.")
        else:
            # Player is trying to look at something specific (e.g., 'look fountain')
            target = self.args[0]
            self.player.send_message(f"You examine the **{target}** closely.")
            # In a real MUD, you would check room contents here.