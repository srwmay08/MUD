# mud_backend/verbs/attack.py
import time
import copy 
from mud_backend.verbs.base_verb import BaseVerb
# --- REFACTORED: Removed all game_state imports ---
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
                    # --- FIX: Use self.world ---
                    with self.world.defeated_lock:
                        is_defeated = uid in self.world.defeated_monsters
                
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
            
        # --- FIX: Use self.world ---
        with self.world.defeated_lock:
            if monster_uid in self.world.defeated_monsters:
                self.player.send_message(f"The {target_monster_data['name']} is already dead.")
                return
        
        current_time = time.time()

        # Check for *any* round-time first
        # --- FIX: Use self.world ---
        combat_info = self.world.get_combat_state(player_id)
            
        if combat_info and current_time < combat_info.get("next_action_time", 0):
            wait_time = combat_info['next_action_time'] - current_time
            self.player.send_message(f"You are not ready to do that yet. (Wait {wait_time:.1f}s)")
            return
        
        # --- Helper function to perform the attack and handle results ---
        def _resolve_and_handle_attack():
            # --- FIX: Pass self.world.game_items AND self.world ---
            attack_results = combat_system.resolve_attack(
                self.world, self.player, target_monster_data, self.world.game_items
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
                is_fatal = attack_results['is_fatal'] # <-- GET FATAL FLAG
                new_hp = 0
                
                # --- FIX: Use self.world.modify_monster_hp ---
                new_hp = self.world.modify_monster_hp(
                    monster_uid,
                    target_monster_data.get("max_hp", 1),
                    damage
                )

                if new_hp <= 0 or is_fatal: # <-- CHECK FATAL FLAG
                    self.player.send_message(f"**The {target_monster_data['name']} has been DEFEATED!**")
                    
                    nominal_xp = 1000 # TODO: Get from template
                    self.player.add_field_exp(nominal_xp)
                    
                    # --- FIX: Pass self.world data stores ---
                    corpse_data = loot_system.create_corpse_object_data(
                        defeated_entity_template=target_monster_data, 
                        defeated_entity_runtime_id=monster_uid, 
                        game_items_data=self.world.game_items,
                        game_loot_tables=self.world.game_loot_tables,
                        game_equipment_tables_data={} 
                    )
                    self.room.objects.append(corpse_data)
                    
                    # Remove the specific monster instance
                    if target_monster_data in self.room.objects:
                        self.room.objects.remove(target_monster_data)
                    
                    # --- FIX: Pass self.world to save_room_state ---
                    # db.save_room_state(self.room) # This is handled by self.world.save_room
                    self.world.save_room(self.room)
                    
                    self.player.send_message(f"The {corpse_data['name']} falls to the ground.")
                    
                    respawn_time = target_monster_data.get("respawn_time_seconds", 300)
                    respawn_chance = target_monster_data.get(
                        "respawn_chance_per_tick", 
                        getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2)
                    )

                    # --- FIX: Use self.world.set_defeated_monster ---
                    self.world.set_defeated_monster(monster_uid, {
                        "room_id": self.room.room_id,
                        "template_key": monster_id,
                        "type": "monster",
                        "eligible_at": time.time() + respawn_time,
                        "chance": respawn_chance
                    })
                    # --- FIX: Use self.world.stop_combat_for_all ---
                    self.world.stop_combat_for_all(player_id, monster_uid)
                    
                    return False # Combat has ended
            
            return True # Combat continues
        # --- (End of helper function) ---


        # --- Simplified combat logic ---
        
        # --- FIX: Use self.world.get_combat_state ---
        monster_state = self.world.get_combat_state(monster_uid)
        monster_is_fighting_player = (monster_state and 
                                      monster_state.get("state_type") == "combat" and 
                                      monster_state.get("target_id") == player_id)

        # Check if player is switching targets (using UID)
        if combat_info and combat_info.get("target_id") and combat_info.get("target_id") != monster_uid:
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
            
            # --- FIX: Use self.world.set_combat_state/set_monster_hp ---
            # Set Player's RT using UID as target
            self.world.set_combat_state(player_id, {
                "state_type": "action",
                "target_id": monster_uid, 
                "next_action_time": current_time + rt_seconds, 
                "current_room_id": room_id
            })
            
            # --- THIS IS THE FIX ---
            self.player.send_message(f"Roundtime: {rt_seconds:.1f}s")
            # --- END FIX ---
            
            # Set Monster AI using UID as combatant key
            if not monster_is_fighting_player:
                self.world.set_combat_state(monster_uid, {
                    "state_type": "combat",
                    "target_id": player_id,
                    "next_action_time": current_time + (monster_rt / 2),
                    "current_room_id": room_id
                })
                if self.world.get_monster_hp(monster_uid) is None:
                     self.world.set_monster_hp(monster_uid, target_monster_data.get("max_hp", 1))