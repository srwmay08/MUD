# mud_backend/verbs/maneuvers.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.combat_system import calculate_attack_strength, calculate_defense_strength

# Skills that can be used for tripping
TRIP_WEAPON_SKILLS = ["polearms", "staves", "two_handed_blunt"]

class Trip(BaseVerb):
    """
    Handles the 'trip' command.
    Attempts to knock an opponent prone using a suitable weapon.
    """

    def execute(self):
        # 1. Check Roundtime
        if _check_action_roundtime(self.player, action_type="attack"):
            return

        # 2. Check Weapon
        weapon_data = self.player.get_equipped_item_data("mainhand")
        weapon_skill = weapon_data.get("skill") if weapon_data else None

        if weapon_skill not in TRIP_WEAPON_SKILLS:
            self.player.send_message("You must be wielding a polearm, staff, or two-handed blunt weapon to trip.")
            return

        weapon_name = weapon_data.get("name", "your weapon")

        # 3. Find Target
        if not self.args:
            self.player.send_message("Who do you want to trip?")
            return
            
        target_name = " ".join(self.args).lower()
        target_monster = None
        for obj in self.room.objects:
            if obj.get("is_monster") and not self.world.get_defeated_monster(obj.get("uid")):
                if (target_name == obj.get("name", "").lower() or 
                    target_name in obj.get("keywords", [])):
                    target_monster = obj
                    break
        
        if not target_monster:
            self.player.send_message(f"You don't see a '{target_name}' here to trip.")
            return

        target_name = target_monster.get("name", "the creature")

        # 4. Perform CMAN Check (AS vs DS)
        # We use a simplified AS/DS check for this maneuver
        
        # Attacker's "Trip AS"
        cman_ranks = self.player.skills.get("combat_maneuvers", 0)
        weapon_ranks = self.player.skills.get(weapon_skill, 0)
        str_bonus = self.player.con_bonus # con_bonus is actually get_stat_bonus for STR
        
        attacker_as = (cman_ranks * 2) + weapon_ranks + str_bonus
        
        # Defender's "Trip DS"
        # We'll use a simple DS based on their stats
        defender_stats = target_monster.get("stats", {})
        defender_race = target_monster.get("race", "Human")
        
        # Calculate a basic DS for the monster (without evasion/parry/block)
        defender_ds = (
            defender_stats.get("STR", 50) + 
            defender_stats.get("AGI", 50) + 
            defender_stats.get("DEX", 50)
        ) / 3
        
        # Apply posture modifier (harder to trip a prone target)
        if target_monster.get("posture", "standing") == "prone":
            defender_ds *= 1.5
        
        roll = random.randint(1, 100)
        result = (attacker_as - defender_ds) + roll
        
        # 5. Resolve
        if result > 100: # Success!
            target_monster["posture"] = "prone"
            self.player.send_message(f"You swing your {weapon_name} low and sweep {target_name}'s legs!")
            self.player.send_message(f"The {target_name} topples to the ground!")
            
            # Set RT for success
            _set_action_roundtime(self.player, 5.0, rt_type="hard")
            
            # TODO: Start monster combat?
            
        else: # Failure
            self.player.send_message(f"You attempt to trip {target_name} but fail to knock them down.")
            _set_action_roundtime(self.player, 3.0, rt_type="hard")