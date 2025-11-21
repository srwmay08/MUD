# mud_backend/verbs/stance.py
from mud_backend.verbs.base_verb import BaseVerb

@VerbRegistry.register(["stance"])

class Stance(BaseVerb):
    """
    Handles the 'stance' command.
    Allows the player to change their combat stance, balancing Attack vs Defense.
    """

    # Standardized stance names and their display aliases
    STANCES = {
        "offensive": "Offensive",
        "off": "Offensive",
        "advance": "Advance",
        "adv": "Advance",
        "forward": "Forward",
        "fwd": "Forward",
        "neutral": "Neutral",
        "neu": "Neutral",
        "guarded": "Guarded",
        "gua": "Guarded",
        "defensive": "Defensive",
        "def": "Defensive"
    }

    # Mapping full stance names to their verbose messages
    STANCE_MESSAGES = {
        "Offensive": "drops all defense as he moves into a battle-ready stance.",
        "Advance": "moves into an aggressive stance, clearly preparing for an attack.",
        "Forward": "switches to a slightly aggressive stance.",
        "Neutral": "falls back into a relaxed, neutral stance.",
        "Guarded": "moves into a defensive stance, clearly guarding himself.",
        "Defensive": "moves into a defensive stance, ready to fend off an attack."
    }
    
    def execute(self):
        if not self.args:
            current_stance = self.player.stance.capitalize()
            self.player.send_message(f"You are currently in **{current_stance}** stance.")
            return

        target_stance_input = self.args[0].lower()
        
        # Validate input
        if target_stance_input not in self.STANCES:
            self.player.send_message("Usage: STANCE <offensive|advance|forward|neutral|guarded|defensive>")
            return

        new_stance = self.STANCES[target_stance_input]
        
        if self.player.stance.lower() == new_stance.lower():
             self.player.send_message(f"You are already in {new_stance} stance.")
             return

        # Update state
        self.player.stance = new_stance.lower()
        
        # Feedback to player
        self.player.send_message(f"You are now in **{new_stance}** stance.")

        # Verbose output (simulated broadcast for now, as true broadcast requires more complex networking)
        # In a full implementation, this would go to everyone ELSE in the room.
        msg = self.STANCE_MESSAGES.get(new_stance, "changes stance.")
        # print(f"[DEBUG BROADCAST] {self.player.name} {msg}")