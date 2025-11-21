# mud_backend/verbs/smithing.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.verbs.item_actions import _get_item_data
from mud_backend.core.registry import VerbRegistry # <-- Added

@VerbRegistry.register(["stoke"]) 
class Stoke(BaseVerb):
    """Adds fuel to the fire."""
    def execute(self):
        self.player.send_message("You stoke the fire.")
        _set_action_roundtime(self.player, 4.0)

@VerbRegistry.register(["draw"]) 
class Draw(BaseVerb):
    """Draws out the metal (lengthens)."""
    def execute(self):
        if _check_action_roundtime(self.player, "other"): return
        self.player.send_message("You strike the metal, drawing it out.")
        _set_action_roundtime(self.player, 3.0)