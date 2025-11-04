# mud_backend/verbs/stance.py
from mud_backend.verbs.base_verb import BaseVerb

VALID_STANCES = {
    "offensive": "Offensive",
    "advance": "Advance",
    "forward": "Forward",
    "neutral": "Neutral",
    "guarded": "Guarded",
    "defensive": "Defensive",
}

class Stance(BaseVerb):
    """
    Handles the 'stance' command.
    Allows the player to change their combat stance.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message(f"You are currently in **{VALID_STANCES[self.player.stance]}** stance.")
            self.player.send_message("Usage: STANCE <offensive | forward | neutral | guarded | defensive>")
            return

        target_stance = " ".join(self.args).lower()
        
        # Allow partial matching (e.g., "stance off")
        found_stance = None
        for key in VALID_STANCES:
            if key.startswith(target_stance):
                found_stance = key
                break
                
        if not found_stance:
            self.player.send_message(f"'{target_stance}' is not a valid stance.")
            self.player.send_message("Options: offensive, forward, neutral, guarded, defensive")
            return
            
        if self.player.stance == found_stance:
            self.player.send_message(f"You are already in **{VALID_STANCES[found_stance]}** stance.")
            return

        # Set the new stance
        self.player.stance = found_stance
        self.player.send_message(f"You move into a **{VALID_STANCES[found_stance]}** stance.")