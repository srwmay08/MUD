# mud_backend/verbs/posture.py
import random
import math
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.foraging import _set_action_roundtime, _check_action_roundtime
from mud_backend.core.utils import get_stat_bonus

# Map all valid COMMANDS (keys) to their resulting STATE (values)
POSTURE_MAP = {
    "stand": "standing",
    "sit": "sitting",
    "kneel": "kneeling",
    "prone": "prone",
    "crouch": "crouching",  # Distinct state
    "meditate": "meditating", # Distinct state
    "lay": "prone"        # Alias for prone
}

@VerbRegistry.register("stand")
@VerbRegistry.register("sit")
@VerbRegistry.register("kneel")
@VerbRegistry.register("prone")
@VerbRegistry.register("crouch")
@VerbRegistry.register("meditate")
@VerbRegistry.register("lay")
class Posture(BaseVerb):
    """
    Handles the 'sit', 'stand', 'kneel', 'prone', 'crouch', 
    'meditate', and 'lay' commands.
    Allows the player to change their physical posture.
    """

    def _handle_stand(self, from_posture: str):
        """Handles the logic and RT roll for moving to a standing position."""
        
        chance = 0.0
        # Determine failure chance based on current posture
        if from_posture in ["sitting", "kneeling", "meditating"]:
            chance = 0.20
        elif from_posture == "crouching":
            chance = 0.10 # Easier to stand from crouch
        elif from_posture == "prone":
            chance = 0.40
        
        # Check for existing roundtime
        if _check_action_roundtime(self.player, action_type="move"):
            return

        # Roll to see if RT is applied
        if random.random() < chance:
            # Failure! Apply roundtime.
            roll = random.randint(1, 100)
            
            # Calculate stat reduction based on DEX/AGI
            modifiers = self.player.stat_modifiers
            dex_bonus = get_stat_bonus(self.player.stats.get("DEX", 50), "DEX", modifiers)
            agi_bonus = get_stat_bonus(self.player.stats.get("AGI", 50), "AGI", modifiers)
            
            # Average bonus / 20.0 = seconds reduction
            stat_reduction = (dex_bonus + agi_bonus) / 20.0 
            
            base_rt = 1.0
            if roll <= 10: # "Awful roll"
                base_rt = 3.0 
            elif roll <= 40:
                base_rt = 2.0
            
            # Final RT is 0.5s minimum
            final_rt = max(0.5, base_rt - stat_reduction) 
            
            _set_action_roundtime(self.player, final_rt, f"You stumble slightly while trying to stand.")
        else:
            # Success! No roundtime.
            self.player.send_message("You move to a standing position.")
            _set_action_roundtime(self.player, 0.5)
        
        self.player.posture = "standing"

    def execute(self):
        target_command = self.command.lower()
        
        if target_command not in POSTURE_MAP:
            self.player.send_message("That is not a valid posture.")
            return

        # Get the target *state* (e.g., "meditating") from the *command* (e.g., "meditate")
        target_state = POSTURE_MAP[target_command]
        current_posture = self.player.posture
        
        if target_state == current_posture:
            self.player.send_message(f"You are already {current_posture}.")
            return

        # Check for existing roundtime
        if _check_action_roundtime(self.player, action_type="stance"):
            return

        if target_state == "standing":
            # Handle standing logic (which includes RT rolls)
            self._handle_stand(current_posture)
        else:
            # Moving between sit/kneel/prone/crouch/meditate
            self.player.posture = target_state
            
            # Custom messaging for specific states
            if target_state == "meditating":
                self.player.send_message("You sit down, cross your legs, and center your mind.")
            elif target_state == "crouching":
                self.player.send_message("You lower your profile, moving into a crouch.")
            else:
                self.player.send_message(f"You move into a **{target_state}** position.")
            
            _set_action_roundtime(self.player, 0.5) # 0.5s RT for changing posture