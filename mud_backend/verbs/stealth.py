# mud_backend/verbs/stealth.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core.skill_handler import attempt_skill_learning

@VerbRegistry.register(["hide"])
class Hide(BaseVerb):
    """
    Attempts to place the character into stealth.
    Success determined by: Stalking & Hiding Skill + Discipline Bonus + Racial Modifier.
    Gains a significant bonus if no players or monsters are observing.
    """
    def execute(self):
        # 1. Check RT
        if _check_action_roundtime(self.player, action_type="physical"):
            return

        if self.player.is_hidden:
            self.player.send_message("You are already hidden.")
            return

        # 2. Base Calculation
        skill_rank = self.player.skills.get("stalking_and_hiding", 0)
        
        # Skill Bonus
        skill_bonus = calculate_skill_bonus(skill_rank)

        # Stat Bonus: Discipline
        dis_stat = self.player.stats.get("DIS", 50)
        dis_bonus = get_stat_bonus(dis_stat, "DIS", self.player.stat_modifiers)
        
        # Racial Modifier
        race_mod = self.player.race_data.get("hide_bonus", 0) 
        
        # --- Observational Check ---
        observers = 0
        
        # Check Players
        room_players = self.world.room_players.get(self.room.room_id, [])
        for p_name in room_players:
            if p_name != self.player.name.lower():
                observers += 1
        
        # Check Monsters (exclude generic NPCs)
        for obj in self.room.objects:
            if obj.get("is_monster"):
                observers += 1
                
        observer_penalty = 0
        environment_bonus = 0
        
        if observers == 0:
            environment_bonus = 50 
        else:
            observer_penalty = observers * 5

        # Total Modifier
        total_mod = skill_bonus + dis_bonus + race_mod + environment_bonus - observer_penalty
        
        # Roll d100
        roll = random.randint(1, 100)
        result = roll + total_mod
        
        # Base Difficulty
        difficulty = 100
        
        # 3. Roundtime Calculation
        rt = 10
        if skill_rank >= 120:
            rt -= 2
        elif skill_rank >= 60:
            rt -= 1
            
        has_celerity = False
        for buff in self.player.buffs.values():
            if buff.get("id") == "506" or buff.get("name") == "Celerity":
                has_celerity = True
                break
        
        if has_celerity:
            rt -= 1 

        rt = max(3, rt) 

        # 4. Result
        
        # Fetch correct SID to skip broadcast for self
        player_info = self.world.get_player_info(self.player.name.lower())
        sid = player_info.get("sid") if player_info else None

        if result > difficulty:
            self.player.is_hidden = True
            
            # Send success message
            self.player.send_message("You see no one turn their head in your direction as you hide.")
            self.player.send_message("You slip into the shadows and are now hidden.")
            
            # Apply RT
            _set_action_roundtime(self.player, float(rt))
            
            # Broadcast to room (Third person)
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} slips into a hiding place.", 
                "message", 
                skip_sid=sid
            )
            
            # Learning chance
            attempt_skill_learning(self.player, "stalking_and_hiding")
            
        else:
            # Send failure message
            self.player.send_message(f"You see {random.choice(['someone', 'something'])} turn their head in your direction as you hide.")
            self.player.send_message("You attempt to blend with the surroundings, but don't feel very confident about your success.")
            
            # Apply RT
            _set_action_roundtime(self.player, float(rt))

            # Broadcast failure
            self.world.broadcast_to_room(
                self.room.room_id, 
                f"{self.player.name} looks around suspiciously and tries to hide, but fails.", 
                "message", 
                skip_sid=sid
            )

@VerbRegistry.register(["unhide"])
class Unhide(BaseVerb):
    def execute(self):
        if not self.player.is_hidden:
            self.player.send_message("You are not hidden.")
            return

        self.player.is_hidden = False
        
        # Fetch correct SID to skip broadcast for self
        player_info = self.world.get_player_info(self.player.name.lower())
        sid = player_info.get("sid") if player_info else None
        
        self.player.send_message("You step out of the shadows.")
        self.world.broadcast_to_room(
            self.room.room_id, 
            f"{self.player.name} reveals themselves from the shadows.", 
            "message", 
            skip_sid=sid
        )