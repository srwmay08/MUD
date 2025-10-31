# verbs/look.py

# The BaseVerb class import has been removed here to resolve the dynamic loading issue.
# The command executor now handles connecting the Look class to the BaseVerb class.

class Look:
    """Handles the 'look' command."""
    
    # We rely on the command_executor to instantiate this class 
    # and ensure it inherits from BaseVerb, giving it access to self.player, 
    # self.room, and self.args.
    
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