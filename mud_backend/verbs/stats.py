# mud_backend/verbs/stats.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.stat_roller import format_stats 
from mud_backend.core.registry import VerbRegistry # <-- Added

@VerbRegistry.register(["stats", "stat"])

class Stats(BaseVerb):
    """
    Handles the 'stat' command.
    Displays the player's current base attributes.
    """
    
    def execute(self):
        # The format_stats utility handles the formatting
        self.player.send_message(format_stats(self.player.stats))