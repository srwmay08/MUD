# mud_backend/verbs/say.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry # <-- Added

@VerbRegistry.register(["say"]) # <-- Added
class Say(BaseVerb):
    """Handles the 'say' command."""
    
    def execute(self):
        if not self.args:
            self.player.send_message("What do you want to say?")
            return

        message = " ".join(self.args)
        self.player.send_message(f"You say, \"{message}\"")
        self.world.broadcast_to_room(self.room.room_id, f"{self.player.name} says, \"{message}\"", "message", skip_sid=self.player.uid)