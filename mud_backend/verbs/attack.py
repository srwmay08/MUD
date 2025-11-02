# mud_backend/verbs/attack.py
import time
import copy 
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.game_state import (
    COMBAT_STATE, RUNTIME_MONSTER_HP, 
    DEFEATED_MONSTERS, GAME_MONSTER_TEMPLATES,
    GAME_ITEMS, GAME_LOOT_TABLES
)
from mud_backend.core import combat_system
from mud_backend.core import loot_system # <-- NEW IMPORT

class Attack(BaseVerb):
    """
    Handles the 'attack' command.
    - If not in combat, this *initiates* combat.
    - If in combat, this *performs* an attack, subject to roundtime.
    """
    
    def execute(self):
        if not self.args:
            self.player.send_message("Attack what?")
            return

        target_name = " ".join(self.args).lower()
        player_id = self.player.name.lower()
        
        # 1. Find the target
        target_monster_data = None
        for obj in self.room.objects:
            if obj.get("is_monster") and target_name in obj.get("keywords", []):
                target_monster_data = obj
                break

        if not target_monster_data:
            self.player.send_message(f"You don't see a **{target_name}** here to attack.")
            return

        monster_id = target_monster_data.get("monster_id")
        if not monster_id:
            self.player.send_message("That creature cannot be attacked.")
            return
            
        # 2. Check if monster is dead
        if monster_id in DEFEATED_MONSTERS:
            self.player.send_message(f"The {target_monster_data['name']} is already dead.")
            return
        
        # ---
        # NEW: MANUAL ATTACK LOGIC
        # ---
        current_time = time.time()
        
        if player_id in COMBAT_STATE:
            # Player is already in combat
            combat_info = COMBAT_STATE[player_id]
            
            # Check if they are attacking the right target
            if combat_info["target_id"] != monster_id:
                self.player.send_message(f"You are already fighting the {combat_info['target_id']}!")
                return
                
            # Check if their roundtime is up
            if current_time < combat_info["next_action_time"]:
                wait_time = combat_info['next_action_time'] - current_time
                self.player.send_message(f"You are not ready to attack yet. (Wait {wait_time:.1f}s)")
                return
                
            # --- PLAYER IS READY TO ATTACK ---
            self.player.send_message(f"You attack the **{target_monster_data['name']}**!")
            
            attack_results = combat_system.resolve_attack(
                self.player, target_monster_data, GAME_ITEMS
            )
            
            # Send results to the player
            self.player.send_message(attack_results['attacker_msg'])
            self.player.send_message(attack_results['roll_string'])
            
            if attack_results['hit']:
                # Apply damage
                damage = attack_results['damage']
                if monster_id not in RUNTIME_MONSTER_HP:
                    RUNTIME_MONSTER_HP[monster_id] = target_monster_data.get("max_hp", 1)
                
                RUNTIME_MONSTER_HP[monster_id] -= damage
                new_hp = RUNTIME_MONSTER_HP[monster_id]

                if new_hp <= 0:
                    # Monster is dead
                    self.player.send_message(f"**The {target_monster_data['name']} has been DEFEATED!**")
                    
                    # --- NEW: GRANT XP (Level-based) ---
                    monster_level = target_monster_data.get("level", 1)
                    level_diff = self.player.level - monster_level
                    
                    nominal_xp = 1000 # Default for same-level
                    if level_diff >= 10:
                        nominal_xp = 0
                    elif level_diff > 0: # Monster is lower level
                        nominal_xp = 100 - (level_diff * 10)
                    elif level_diff <= -5: # Monster is 5+ levels higher
                        nominal_xp = 150
                    elif level_diff < 0: # Monster is 1-4 levels higher
                        nominal_xp = 100 + (abs(level_diff) * 10)

                    if nominal_xp > 0:
                        # Use the new method that handles diminishing returns
                        self.player.add_field_exp(nominal_xp)
                    else:
                        self.player.send_message("You learn nothing from this kill.")
                    # --- END NEW ---
                    
                    corpse_data = loot_system.create_corpse_object_data(
                        defeated_entity_template=target_monster_data, 
                        defeated_entity_runtime_id=monster_id,
                        game_items_data=GAME_ITEMS,
                        game_loot_tables=GAME_LOOT_TABLES,
                        game_equipment_tables_data={} 
                    )
                    
                    self.room.objects.append(corpse_data)
                    self.room.objects = [obj for obj in self.room.objects if obj.get("monster_id") != monster_id]
                    self.player.send_message(f"The {corpse_data['name']} falls to the ground.")
                    
                    DEFEATED_MONSTERS[monster_id] = {
                        "room_id": self.room.room_id,
                        "template_key": monster_id,
                        "type": "monster",
                        "eligible_at": time.time() + 300 # 5 min respawn
                    }
                    combat_system.stop_combat(player_id, monster_id)
                    return # Combat is over
                else:
                    self.player.send_message(f"(The {target_monster_data['name']} has {new_hp} HP remaining)")
            
            # Set player's next roundtime
            rt_seconds = combat_system.calculate_roundtime(self.player.stats.get("AGI", 50))
            combat_info["next_action_time"] = current_time + rt_seconds
            
        else:
            # --- PLAYER IS INITIATING COMBAT ---
            self.player.send_message(f"You attack the **{target_monster_data['name']}**!")
            
            room_id = self.room.room_id
            
            # Add player to combat state
            COMBAT_STATE[player_id] = {
                "target_id": monster_id,
                "next_action_time": current_time, # Attack immediately
                "current_room_id": room_id
            }
            
            # Add monster to combat state
            monster_rt = combat_system.calculate_roundtime(target_monster_data.get("stats", {}).get("AGI", 50))
            COMBAT_STATE[monster_id] = {
                "target_id": player_id,
                "next_action_time": current_time + (monster_rt / 2), # Acts in half a round
                "current_room_id": room_id
            }
            
            if monster_id not in RUNTIME_MONSTER_HP:
                RUNTIME_MONSTER_HP[monster_id] = target_monster_data.get("max_hp", 1)
            
            # --- PERFORM THE FIRST ATTACK ---
            # This is a "free" attack for initiating
            self.execute() # Just call this function again