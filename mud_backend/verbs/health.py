# mud_backend/verbs/health.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry # <-- Added

@VerbRegistry.register(["health", "hp"]) 
class Health(BaseVerb):
    """Handles the 'health' command."""
    def execute(self):
        player = self.player
        current_hp = player.hp
        max_hp = player.max_hp
        percent_hp = (current_hp / max_hp) * 100
        
        if current_hp <= 0: status = "**DEAD**"
        elif percent_hp > 90: status = "in excellent shape"
        elif percent_hp > 75: status = "in good shape"
        elif percent_hp > 50: status = "lightly wounded"
        elif percent_hp > 25: status = "moderately wounded"
        elif percent_hp > 10: status = "badly wounded"
        else: status = "near death"

        death_sting_msg = "None"
        if player.death_sting_points > 0:
            death_sting_msg = f"{player.death_sting_points} points (XP gain reduced)"

        con_loss_msg = "None"
        if player.con_lost > 0:
            con_loss_msg = f"{player.con_lost} points lost (Recovery pool: {player.con_recovery_pool:,})"
            
        self.player.send_message("--- **Health Status** ---")
        self.player.send_message(f"HP: {current_hp}/{max_hp} ({status})")
        self.player.send_message(f"CON Loss: {con_loss_msg}")
        self.player.send_message(f"Death's Sting: {death_sting_msg}")
        
        if self.player.wounds:
            self.player.send_message("\n--- **Active Wounds** ---")
            wound_descs = self.world.game_criticals.get("wounds", {})
            for location, rank in self.player.wounds.items():
                desc = wound_descs.get(location, {}).get(str(rank), f"a rank {rank} wound to the {location}")
                self.player.send_message(f"- {location.capitalize()}: {desc}")