# mud_backend/verbs/maneuvers.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import get_stat_bonus, calculate_skill_bonus
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
            # --- MODIFIED: Include NPCs ---
            if (obj.get("is_monster") or obj.get("is_npc")) and not self.world.get_defeated_monster(obj.get("uid")):
            # --- END MODIFIED ---
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
        
        # ---
        # --- NEW: Engage the warrior to prevent wandering
        # ---
        target_uid = target_monster.get("uid")
        player_uid = self.player.name.lower()

        if is_training and is_warrior:
            warrior_state = self.world.get_combat_state(target_uid)
            is_engaged = (warrior_state and 
                          warrior_state.get("state_type") == "combat" and 
                          warrior_state.get("target_id") == player_uid)
            
            if not is_engaged:
                # Set combat state on warrior to prevent wandering
                self.world.set_combat_state(target_uid, {
                    "state_type": "combat",
                    "target_id": player_uid,
                    "next_action_time": time.time() + 9999, # He won't attack
                    "current_room_id": self.room.room_id
                })
                # Set combat state on player to allow for "flee" messages
                self.world.set_combat_state(player_uid, {
                    "state_type": "combat",
                    "target_id": target_uid,
                    "next_action_time": time.time(), # Player is free
                    "current_room_id": self.room.room_id,
                    "rt_type": "hard"
                })
        # ---
        # --- END ENGAGE LOGIC
        # ---

        # ---
        # --- MODIFIED: Replaced CMAN Check with new logic
        # ---
        
        # 4. Perform CMAN Check
        
        # --- Attacker's Offense Bonus ---
        # "biggest factor is... bonus in Combat Maneuvers."
        cman_bonus = calculate_skill_bonus(self.player.skills.get("combat_maneuvers", 0))
        str_bonus = get_stat_bonus(self.player.stats.get("STR", 50), "STR", self.player.race)
        agi_bonus = get_stat_bonus(self.player.stats.get("AGI", 50), "AGI", self.player.race)
        level_bonus = self.player.level * 2 # "Level difference plays a factor"
        
        attacker_bonus = cman_bonus + str_bonus + agi_bonus + level_bonus
        
        # --- Defender's Defense Bonus ---
        defender_stats = target_monster.get("stats", {})
        defender_skills = target_monster.get("skills", {})
        defender_race = target_monster.get("race", "Human")
        defender_level = target_monster.get("level", 1)

        # "Each rank...gives...up to +15 to defend" (We use skill bonus, which is stronger)
        def_cman_bonus = calculate_skill_bonus(defender_skills.get("combat_maneuvers", 0))
        def_str_bonus = get_stat_bonus(defender_stats.get("STR", 50), "STR", defender_race)
        def_agi_bonus = get_stat_bonus(defender_stats.get("AGI", 50), "AGI", defender_race)
        def_dex_bonus = get_stat_bonus(defender_stats.get("DEX", 50), "DEX", defender_race)
        def_level_bonus = defender_level * 2
        
        defender_bonus = def_cman_bonus + def_str_bonus + def_agi_bonus + def_dex_bonus + def_level_bonus

        # --- Factor in Stance ---
        stance_mod = 0
        attacker_stance = self.player.stance
        if attacker_stance in ["offensive", "advance"]: stance_mod = 20
        if attacker_stance in ["guarded", "defensive"]: stance_mod = -20
        
        defender_stance = target_monster.get("stance", "creature")
        if defender_stance in ["offensive", "advance"]: stance_mod -= 20
        if defender_stance in ["guarded", "defensive"]: stance_mod += 20
        
        # --- Factor in Posture ---
        posture_mod = 0
        if target_monster.get("posture", "standing") == "prone":
            posture_mod = -30 # Harder to trip a target that is already prone

        # --- Factor in Stun ---
        stun_mod = 0
        if "stun" in target_monster.get("status_effects", []):
            stun_mod = 10 # "A stunned target has -10 to defend"
        
        # --- END CMAN CALCULATION ---

        # 5. Resolve
        roll = random.randint(1, 100)
        result = 0 # Default to fail

        # --- THIS IS THE KEY FIX for the 50% success rate ---
        if is_training and is_warrior:
            self.player.send_message("[You attempt the training maneuver...]")
            
            # Simple 50/50 check for training, ignoring stats
            if random.random() < 0.50: # 50% success rate
                result = 101 # Force success
            else:
                result = 0 # Force fail
        
        else:
            # Real combat calculation
            # (Attacker - Defender) + Roll + Advantage + Mods
            advantage = 50 # Base advantage (like in combat_system.py)
            result = (attacker_bonus - defender_bonus) + roll + advantage + stance_mod + posture_mod + stun_mod
            self.player.send_message(f"[Roll: {result} (A:{attacker_bonus} vs D:{defender_bonus}) + d100:{roll} + Adv:{advantage} + Mod:{stance_mod+posture_mod+stun_mod}]")

        # 6. Check Result
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
                    if "trip_training" in self.player.known_maneuvers:
                        self.player.known_maneuvers.remove("trip_training")
                    self.player.known_maneuvers.append("trip")
                    self.player.completed_quests.append("trip_quest_1") # Use the quest_id from quests.json
                    
                    # --- NEW: Disengage combat ---
                    self.world.stop_combat_for_all(player_uid, target_uid)
                    # --- END NEW ---
                    
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