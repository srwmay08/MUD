# mud_backend/verbs/stance_actions.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import game_state

# Helper list of statuses that prevent standing
GROUND_STATUSES = ["sitting", "kneeling", "prone"]

class Stand(BaseVerb):
    """Handles the 'stand' command."""
    def execute(self):
        # Check if the player is already standing
        if not any(status in self.player.status_effects for status in GROUND_STATUSES):
            self.player.send_message("You are already standing.")
            return
            
        # Check if player is immobilized
        if any(s in self.player.status_effects for s in ["immobilized", "webbed"]):
            self.player.send_message("You are bound and cannot stand up!")
            return
            
        # Remove all ground statuses
        self.player.status_effects = [s for s in self.player.status_effects if s not in GROUND_STATUSES]
        self.player.send_message("You stand up.")

class Sit(BaseVerb):
    """Handles the 'sit' command."""
    def execute(self):
        if "sitting" in self.player.status_effects:
            self.player.send_message("You are already sitting.")
            return
            
        if any(s in self.player.status_effects for s in ["prone", "kneeling"]):
            self.player.send_message("You must STAND up first.")
            return
            
        if any(s in self.player.status_effects for s in ["immobilized", "webbed"]):
            self.player.send_message("You are bound and cannot sit down!")
            return
            
        self.player.status_effects.append("sitting")
        self.player.send_message("You sit down.")

class Kneel(BaseVerb):
    """Handles the 'kneel' command."""
    def execute(self):
        if "kneeling" in self.player.status_effects:
            self.player.send_message("You are already kneeling.")
            return
            
        if any(s in self.player.status_effects for s in ["prone", "sitting"]):
            self.player.send_message("You must STAND up first.")
            return
            
        if any(s in self.player.status_effects for s in ["immobilized", "webbed"]):
            self.player.send_message("You are bound and cannot kneel!")
            return
            
        self.player.status_effects.append("kneeling")
        self.player.send_message("You kneel down.")
        
class Prone(BaseVerb):
    """Handles the 'prone' command."""
    def execute(self):
        if "prone" in self.player.status_effects:
            self.player.send_message("You are already prone.")
            return
            
        if any(s in self.player.status_effects for s in ["sitting", "kneeling"]):
            self.player.send_message("You must STAND up first.")
            return
            
        if any(s in self.player.status_effects for s in ["immobilized", "webbed"]):
            self.player.send_message("You are bound and cannot lie down!")
            return
            
        self.player.status_effects.append("prone")
        self.player.send_message("You lie down on the ground.")