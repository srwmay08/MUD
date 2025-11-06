# mud_backend/verbs/attack.py
import time
import copy 
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.game_state import (
    COMBAT_STATE, RUNTIME_MONSTER_HP, 
    DEFEATED_MONSTERS, GAME_MONSTER_TEMPLATES,
    GAME_ITEMS, GAME_LOOT_TABLES,
    COMBAT_LOCK
)
from mud_backend import config 
from mud_backend.core import combat_system
from mud_backend.core import loot_system
from mud_backend.core import db 

class Attack(BaseVerb):
    """
    Handles the 'attack' command.
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
            monster_id_check = obj.get("monster_id")
            if monster_id_check:
                # Use UID for uniqueness checks
                uid = obj.get("uid")
                is_defeated = False
                if uid:
                    with COMBAT_LOCK:
                        is_defeated = uid in DEFEATED_MONSTERS
                
                if not is_defeated:
                    if target_name in obj.get("keywords", [obj.get("name", "").lower()]):
                        target_monster_data = obj
                        break

        if not target_monster_data:
            self.player.send_message(f"You don't see a **{target_name}** here to attack.")
            return

        # Get both template ID and Unique ID
        monster_id = target_monster_data.get("monster_id")
        monster_uid = target_monster_data.get("uid")

        if not monster_id or not monster_uid:
            self.player.send_message("That creature cannot be attacked right now.")
            return
            
        with COMBAT_LOCK:
            if monster_uid in DEFEATED_MONSTERS:
                self.player.send_message(f"The {target_monster_data['name']} is already dead.")
                return
        
        current_time = time.time()

        # Check for *any* round-time first
        combat_info = None
        with COMBAT_LOCK:
            combat_info = COMBAT_STATE.get(player_id)
            
        if combat_info and current_time < combat_info.get("next_action_time", 0):
            wait_time = combat_info['next_action_time'] - current_time
            self.player.send_message(f"You are not ready to do that yet. (Wait {wait_time:.1f}s)")
            return
        
        # --- Helper function to perform the attack and handle results ---
        def _resolve_and_handle_attack():
            attack_results = combat_system.resolve_attack(
                self.player, target_monster_data, GAME_ITEMS
            )
            
            # 1. Flavor Text
            self.player.send_message(attack_results['attacker_msg'])
            
            # 2. Roll String
            self.player.send_message(attack_results['roll_string'])
            
            if attack_results['hit']:
                # 3. Damage Text
                self.player.send_message(attack_results['damage_msg'])
                
                # 4. Consequences (HP, Death)
                damage = attack_results['damage']
                new_hp = 0
                
                with COMBAT_LOCK:
                    # Use UID for runtime HP tracking
                    if monster_uid not in RUNTIME_MONSTER_HP:
                        RUNTIME_MONSTER_HP[monster_uid] = target_monster_data.get("max_hp", 1)
                    
                    RUNTIME_MONSTER_HP[monster_uid] -= damage
                    new_hp = RUNTIME_MONSTER_HP[monster_uid]

                if new_hp <= 0:
                    self.player.send_message(f"**The {target_monster_data['name']} has been DEFEATED!**")
                    
                    nominal_xp = 1000 
                    self.player.add_field_exp(nominal_xp)
                    
                    # Pass the UID to corpse creation so it can be unique too if needed
                    corpse_data = loot_system.create_corpse_object_data(
                        defeated_entity_template=target_monster_data, 
                        defeated_entity_runtime_id=monster_uid, 
                        game_items_data=GAME_ITEMS,
                        game_loot_tables=GAME_LOOT_TABLES,
                        game_equipment_tables_data={} 
                    )
                    self.room.objects.append(corpse_data)
                    
                    # Remove the specific monster instance
                    if target_monster_data in self.room.objects:
                        self.room.objects.remove(target_monster_data)
                    
                    db.save_room_state(self.room) 
                    
                    self.player.send_message(f"The {corpse_data['name']} falls to the ground.")
                    
                    respawn_time = target_monster_data.get("respawn_time_seconds", 300)
                    respawn_chance = target_monster_data.get(
                        "respawn_chance_per_tick", 
                        getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2)
                    )

                    with COMBAT_LOCK:
                        # Register defeat using UID, but remember template ID for respawn
                        DEFEATED_MONSTERS[monster_uid] = {
                            "room_id": self.room.room_id,
                            "template_key": monster_id,
                            "type": "monster",
                            "eligible_at": time.time() + respawn_time,
                            "chance": respawn_chance
                        }
                        combat_system.stop_combat(player_id, monster_uid)
                    
                    return False # Combat has ended
            
            return True # Combat continues
        # --- (End of helper function) ---


        # --- Simplified combat logic ---
        
        # Check if the monster is already fighting the player (using UID)
        monster_state = None
        with COMBAT_LOCK:
            monster_state = COMBAT_STATE.get(monster_uid)
        monster_is_fighting_player = (monster_state and 
                                      monster_state.get("state_type") == "combat" and 
                                      monster_state.get("target_id") == player_id)

        # Check if player is switching targets (using UID)
        if combat_info and combat_info.get("target_id") and combat_info.get("target_id") != monster_uid:
            # Player's last action was against a different target
            # (We might want to allow switching, but GSIV usually locks you or warns you)
            # For now, let's allow it but warn them implicitly by just attacking the new one.
            # actually, standard GSIV lets you 'attack other' and it just switches target.
            pass 

        if not monster_is_fighting_player:
             self.player.send_message(f"You attack the **{target_monster_data['name']}**!")
        
        # --- Resolve the attack ---
        combat_continues = _resolve_and_handle_attack()
        
        # --- Set RT and Monster AI (if combat didn't end) ---
        if combat_continues:
            room_id = self.room.room_id
            base_rt = combat_system.calculate_roundtime(self.player.stats.get("AGI", 50))
            armor_penalty = self.player.armor_rt_penalty
            rt_seconds = base_rt + armor_penalty
            monster_rt = combat_system.calculate_roundtime(target_monster_data.get("stats", {}).get("AGI", 50))
            
            with COMBAT_LOCK:
                # Set Player's RT using UID as target
                COMBAT_STATE[player_id] = {
                    "state_type": "action",
                    "target_id": monster_uid, 
                    "next_action_time": current_time + rt_seconds, 
                    "current_room_id": room_id
                }
                
                # Set Monster AI using UID as combatant key
                if not monster_is_fighting_player:
                    COMBAT_STATE[monster_uid] = {
                        "state_type": "combat",
                        "target_id": player_id,
                        "next_action_time": current_time + (monster_rt / 2),
                        "current_room_id": room_id
                    }
                    if monster_uid not in RUNTIME_MONSTER_HP:
                         RUNTIME_MONSTER_HP[monster_uid] = target_monster_data.get("max_hp", 1)