# mud_backend/verbs/attack.py
import time
import copy # <-- NEW IMPORT
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.game_state import COMBAT_STATE, RUNTIME_MONSTER_HP, DEFEATED_MONSTERS, GAME_MONSTER_TEMPLATES
from mud_backend.core import combat_system 

class Attack(BaseVerb):
    """
    Handles the 'attack' command.
    This verb *initiates* combat. The combat itself is handled
    by the combat_system tick.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Attack what?")
            return

        target_name = " ".join(self.args).lower()
        player_id = self.player.name.lower()
        
        # 1. Check if player is already in combat
        if player_id in COMBAT_STATE:
            self.player.send_message("You are already in combat!")
            return
            
        # --- UPDATED: Find target by keyword ---
        target_monster_data = None
        for obj in self.room.objects:
            if obj.get("is_monster") and target_name in obj.get("keywords", []):
                target_monster_data = obj
                break # Found our monster
        # ---

        if not target_monster_data:
            self.player.send_message(f"You don't see a **{target_name}** here to attack.")
            return

        monster_id = target_monster_data.get("monster_id")
        if not monster_id:
            self.player.send_message("That creature cannot be attacked.")
            return
            
        # (This inflation logic is now redundant because command_executor handles it)
        # (We will leave it for now as a safeguard)
        if "stats" not in target_monster_data:
            template = GAME_MONSTER_TEMPLATES.get(monster_id)
            if not template:
                self.player.send_message("Error: Monster template not found.")
                return
            target_monster_data.update(copy.deepcopy(template))

        # 3. Check if monster is already dead
        if monster_id in DEFEATED_MONSTERS:
            self.player.send_message(f"The {target_monster_data['name']} is already dead.")
            return
            
        # 4. Check if monster is already in combat
        if monster_id in COMBAT_STATE:
            self.player.send_message(f"The {target_monster_data['name']} is already fighting someone else!")
            return

        # 5. INITIATE COMBAT
        # Use the monster's proper name in the message
        self.player.send_message(f"You attack the **{target_monster_data['name']}**!")
        
        current_time = time.time()
        room_id = self.room.room_id
        
        COMBAT_STATE[player_id] = {
            "target_id": monster_id,
            "next_action_time": current_time,
            "current_room_id": room_id
        }
        
        monster_rt = combat_system.calculate_roundtime(target_monster_data.get("stats", {}).get("AGI", 50))
        COMBAT_STATE[monster_id] = {
            "target_id": player_id,
            "next_action_time": current_time + (monster_rt / 2),
            "current_room_id": room_id
        }
        
        if monster_id not in RUNTIME_MONSTER_HP:
            RUNTIME_MONSTER_HP[monster_id] = target_monster_data.get("max_hp", 1)