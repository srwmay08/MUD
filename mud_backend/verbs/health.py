# mud_backend/verbs/health.py
from mud_backend.verbs.base_verb import BaseVerb

class Health(BaseVerb):
    """
    Handles the 'health' command.
    Displays the player's HP and general health status.
    """
    
    def execute(self):
        player = self.player
        current_hp = player.hp
        max_hp = player.max_hp
        
        # Calculate health percentage for status flavor
        percent_hp = (current_hp / max_hp) * 100
        
        # Determine health message
        if current_hp <= 0:
            status = "**DEAD**"
        elif percent_hp > 90:
            status = "in excellent shape"
        elif percent_hp > 75:
            status = "in good shape"
        elif percent_hp > 50:
            status = "lightly wounded"
        elif percent_hp > 25:
            status = "moderately wounded"
        elif percent_hp > 10:
            status = "badly wounded"
        else:
            status = "near death"

        # Death's Sting status
        death_sting_msg = "None"
        if player.death_sting_points > 0:
            death_sting_msg = f"{player.death_sting_points} points (XP gain reduced)"

        # CON loss status (Temporary CON loss, tracked in con_lost)
        # This confirms that the CON loss is temporary and shows the pool for recovery.
        con_loss_msg = "None"
        if player.con_lost > 0:
            con_loss_msg = f"{player.con_lost} points lost (Recovery pool: {player.con_recovery_pool:,})"
            
        self.player.send_message("--- **Health Status** ---")
        self.player.send_message(f"HP: {current_hp}/{max_hp} ({status})")
        self.player.send_message(f"CON Loss: {con_loss_msg}")
        self.player.send_message(f"Death's Sting: {death_sting_msg}")
        
        # --- NEW: Display Wounds ---
        if self.player.wounds:
            self.player.send_message("\n--- **Active Wounds** ---")
            # Load the wound descriptions from the criticals table
            wound_descs = self.world.game_criticals.get("wounds", {})
            
            for location, rank in self.player.wounds.items():
                # Get the description for this location and rank
                desc = wound_descs.get(location, {}).get(str(rank), f"a rank {rank} wound to the {location}")
                self.player.send_message(f"- {location.capitalize()}: {desc}")
        # --- END NEW ---