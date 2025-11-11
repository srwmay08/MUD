# mud_backend/verbs/maneuvers.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
# --- MODIFIED: Import get_stat_bonus ---
from mud_backend.core.combat_system import calculate_attack_strength, calculate_defense_strength
from mud_backend.core.utils import get_stat_bonus
# --- END MODIFIED ---

# Skills that can be used for tripping
TRIP_WEAPON_SKILLS = ["polearms", "staves", "two_handed_blunt"]

class Trip(BaseVerb):
    """
    Handles the 'trip' command.
    Attempts to knock an opponent prone using a suitable weapon.
    """

    def execute(self):
        # --- NEW: Gating check ---
        if "trip" not in self.player.known_maneuvers and "trip_training" not in self.player.known_maneuvers:
            self.player.send_message("You do not know how to perform that maneuver.")
            return
        # --- END NEW ---

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

        # --- NEW: Check if training ---
        is_training = "trip_training" in self.player.known_maneuvers
        is_warrior = target_monster.get("monster_id") == "grizzled_warrior"
        
        if is_training and not is_warrior:
            self.player.send_message("You must complete your training with the Grizzled Warrior before you can trip other targets.")
            return
        # --- END NEW ---

        # 4. Perform CMAN Check (AS vs DS)
        # We use a simplified AS/DS check for this maneuver
        
        cman_ranks = self.player.skills.get("combat_maneuvers", 0)
        weapon_ranks = self.player.skills.get(weapon_skill, 0)
        
        # ---
        # --- THIS IS THE FIX ---
        # Calculate STR bonus correctly
        str_bonus = get_stat_bonus(self.player.stats.get("STR", 50), "STR", self.player.race)
        # --- END FIX ---
        
        attacker_as = (cman_ranks * 2) + weapon_ranks + str_bonus
        
        # Defender's "Trip DS"
        # We'll use a simple DS based on their stats
        defender_stats = target_monster.get("stats", {})
        defender_race = target_monster.get("race", "Human")
        
        # --- NEW: Get monster's skill for DS ---
        # A monster's DS against trip is helped by their own CMAN and weapon skill
        defender_cman = defender_stats.get("combat_maneuvers", 0)
        defender_wep_skill = 0
        if "polearms" in defender_stats: defender_wep_skill = defender_stats["polearms"]
        if "staves" in defender_stats: defender_wep_skill = max(defender_wep_skill, defender_stats["staves"])
        if "two_handed_blunt" in defender_stats: defender_wep_skill = max(defender_wep_skill, defender_stats["two_handed_blunt"])

        defender_ds = (
            defender_stats.get("STR", 50) + 
            defender_stats.get("AGI", 50) + 
            defender_stats.get("DEX", 50) +
            defender_cman + 
            defender_wep_skill
        ) / 3
        # --- END NEW ---
        
        # Apply posture modifier (harder to trip a prone target)
        if target_monster.get("posture", "standing") == "prone":
            defender_ds *= 1.5
        
        roll = random.randint(1, 100)
        result = (attacker_as - defender_ds) + roll
        
        # 5. Resolve
        if result > 100: # Success!
            
            # --- NEW: Handle training success ---
            if is_training and is_warrior:
                self.player.quest_trip_counter += 1
                count = self.player.quest_trip_counter
                
                self.player.send_message(f"You swing your {weapon_name} low and sweep {target_name}'s legs!")
                self.player.send_message(f"The {target_name} topples to the ground!")
                
                if count >= 10:
                    # Quest complete!
                    self.player.send_message("The warrior dusts himself off and nods. 'Alright, alright, I've had enough! You've got the hang of it. Be careful with that.'")
                    self.player.send_message("You have learned: **Trip**")
                    self.player.known_maneuvers.remove("trip_training")
                    self.player.known_maneuvers.append("trip")
                    self.player.completed_quests.append("trip_quest_1") # Use the quest_id from quests.json
                    _set_action_roundtime(self.player, 3.0, rt_type="hard") # Shorter RT on completion
                else:
                    # Quest in progress
                    self.player.send_message(f"The {target_name} scrambles back to his feet. 'Not bad! Again! ({count}/10)'")
                    _set_action_roundtime(self.player, 5.0, rt_type="hard") # The 5s RT
            
            else:
                # --- Original success logic ---
                target_monster["posture"] = "prone"
                self.player.send_message(f"You swing your {weapon_name} low and sweep {target_name}'s legs!")
                self.player.send_message(f"The {target_name} topples to the ground!")
                
                # Set RT for success
                _set_action_roundtime(self.player, 5.0, rt_type="hard")
            
        else: # Failure
            # --- NEW: Handle training failure ---
            if is_training and is_warrior:
                self.player.send_message(f"You attempt to trip {target_name} but fail.")
                self.player.send_message(f"The {target_name} scoffs. 'Too slow! Again!'")
            else:
                # --- Original failure logic ---
                self.player.send_message(f"You attempt to trip {target_name} but fail to knock them down.")
            
            _set_action_roundtime(self.player, 3.0, rt_type="hard")