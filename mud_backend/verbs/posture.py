# mud_backend/verbs/posture.py
import random
import math
import time
from mud_backend.verbs.base_verb import BaseVerb
# --- REFACTORED: Removed game_state import ---

# We import these helpers from other files
# This helper applies roundtime
# --- MODIFIED: Import both helpers ---
from mud_backend.verbs.foraging import _set_action_roundtime, _check_action_roundtime
# --- END MODIFIED ---
# This helper calculates stat bonuses
from mud_backend.core.combat_system import get_stat_bonus #<-- This should be from utils, but keeping as-is from your file
from mud_backend.core.utils import get_stat_bonus #<-- Correcting import, using utils

# --- THIS IS THE FIX ---
# Map all valid COMMANDS (keys) to their resulting STATE (values)
POSTURE_MAP = {
    "stand": "standing",
    "sit": "sitting",
    "kneel": "kneeling",
    "prone": "prone",
    "crouch": "kneeling", # <-- NEW ALIAS
    "meditate": "sitting",  # <-- NEW ALIAS
    "lay": "prone"        # <-- NEW ALIAS (for "lay down")
}
# --- END FIX ---


class Posture(BaseVerb):
    """
    Handles the 'sit', 'stand', 'kneel', 'prone', 'crouch', 
    'meditate', and 'lay' commands.
    Allows the player to change their physical posture.
    
    The command itself (e.g., 'sit') is passed in self.command.
    """

    def _handle_stand(self, from_posture: str):
        """Handles the logic and RT roll for moving to a standing position."""
        
        chance = 0.0
        if from_posture in ["sitting", "kneeling"]:
            chance = 0.20
        elif from_posture == "prone":
            chance = 0.40
        
        # Check for existing roundtime
        # --- MODIFIED: Use new helper ---
        # Note: We check RT *again* here because execute() might call this
        # without having checked RT itself (if logic changes). It's safer.
        # --- FIX: Specify action_type ---
        if _check_action_roundtime(self.player, action_type="move"):
            return
        # --- END FIX ---

        # Roll to see if RT is applied
        if random.random() < chance:
            # Failure! Apply roundtime.
            roll = random.randint(1, 100)
            
            # Calculate stat reduction based on DEX/AGI
            dex_bonus = get_stat_bonus(self.player.stats.get("DEX", 50), "DEX", self.player.race)
            agi_bonus = get_stat_bonus(self.player.stats.get("AGI", 50), "AGI", self.player.race)
            
            # Average bonus / 20.0 = seconds reduction
            # e.g., (25 + 25) / 20.0 = 2.5s reduction
            stat_reduction = (dex_bonus + agi_bonus) / 20.0 
            
            base_rt = 1.0
            if roll <= 10: # "Awful roll" (10% chance on a failed check)
                base_rt = 3.0 # A "couple seconds"
            elif roll <= 40:
                base_rt = 2.0
            
            # Final RT is 0.5s minimum
            final_rt = max(0.5, base_rt - stat_reduction) 
            
            # --- MODIFIED: Use helper, provide custom message ---
            _set_action_roundtime(self.player, final_rt, f"You stumble slightly while trying to stand.")
        else:
            # Success! No roundtime.
            self.player.send_message("You move to a standing position.")
            # --- NEW: Set minimal RT for successful stand ---
            _set_action_roundtime(self.player, 0.5)
        
        self.player.posture = "standing"

    def execute(self):
        # --- THIS IS THE FIX ---
        
        # The command is 'sit', 'stand', 'crouch', etc.
        # We get it from self.command (passed by command_executor)
        target_command = self.command.lower()
        
        if target_command not in POSTURE_MAP:
            # This should not happen if aliased correctly
            self.player.send_message("That is not a valid posture.")
            return

        # Get the target *state* (e.g., "sitting") from the *command* (e.g., "sit")
        target_state = POSTURE_MAP[target_command]
        current_posture = self.player.posture
        
        if target_state == current_posture:
            self.player.send_message(f"You are already {current_posture}.")
            return
        # --- END FIX ---

        # Check for existing roundtime
        # --- MODIFIED: Use new helper ---
        # --- FIX: Specify action_type ---
        if _check_action_roundtime(self.player, action_type="stance"):
            return
        # --- END FIX ---

        if target_state == "standing":
            # Handle standing logic (which includes RT rolls)
            self._handle_stand(current_posture)
        else:
            # Moving between sit/kneel/prone (or from stand to one)
            # This is always allowed and has a minimal RT
            
            # --- THIS IS THE FIX ---
            self.player.posture = target_state # Set the correct state (e.g., "sitting")
            self.player.send_message(f"You move into a **{target_state}** position.")
            # --- END FIX ---
            
            _set_action_roundtime(self.player, 0.5) # 0.5s RT for changing posture