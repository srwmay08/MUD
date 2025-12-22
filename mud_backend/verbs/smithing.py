# mud_backend/verbs/smithing.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["stoke"]) 
class Stoke(BaseVerb):
    """Adds fuel to the fire."""
    def execute(self):
        self.player.send_message("You stoke the fire.")
        set_action_roundtime(self.player, 4.0)

@VerbRegistry.register(["draw"]) 
class Draw(BaseVerb):
    """Draws out the metal (lengthens)."""
    def execute(self):
        if check_action_roundtime(self.player, "other"): return
        self.player.send_message("You strike the metal, drawing it out.")
        set_action_roundtime(self.player, 3.0)