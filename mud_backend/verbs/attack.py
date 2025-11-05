# mud_backend/verbs/attack.py
import time
import copy 
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.game_state import (
    COMBAT_STATE, RUNTIME_MONSTER_HP, 
    DEFEATED_MONSTERS, GAME_MONSTER_TEMPLATES,
    GAME_ITEMS, GAME_LOOT_TABLES
)
from mud_backend import config 
from mud_backend.core import combat_system
from mud_backend.core import loot_system
from mud_backend.core import db 

class Attack(BaseVerb):
    """
    Handles the 'attack' command.
    - If not in combat, this *initiates* combat AND performs the first attack.
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
            monster_id_check = obj.get("monster_id")
            if monster_id_check and monster_id_check not in DEFEATED_MONSTERS:
                if target_name in obj.get("keywords", [obj.get("name", "").lower()]):
                    target_monster_data = obj
                    break

        if not target_monster_data:
            self.player.send_message(f"You don't see a **{target_name}** here to attack.")
            return

        monster_id = target_monster_data.get("monster_id")
        if not monster_id:
            self.player.send_message("That creature cannot be attacked.")
            return
            
        if monster_id in DEFEATED_MONSTERS:
            self.player.send_message(f"The {target_monster_data['name']} is already dead.")
            return
        
        current_time = time.time()
        
        def _resolve_and_handle_attack():
            # --- THIS IS THE FIX: Pass self.room.db_data ---
            attack_results = combat_system.resolve_attack(
                self.player, target_monster_data, self.room.db_data, GAME_ITEMS
            )
            # --- END FIX ---
            
            # 1. Flavor Text
            self.player.send_message(attack_results['attacker_msg'])
            
            # 2. Roll String
            self.player.send_message(attack_results['roll_string'])
            
            if attack_results['hit']:
                # 3. Damage Text
                self.player.send_message(attack_results['damage_msg'])
                
                # 4. Consequences (HP, Death)
                damage = attack_results['damage']
                if monster_id not in RUNTIME_MONSTER_HP:
                    RUNTIME_MONSTER_HP[monster_id] = target_monster_data.get("max_hp", 1)
                
                RUNTIME_MONSTER_HP[monster_id] -= damage
                new_hp = RUNTIME_MONSTER_HP[monster_id]

                if new_hp <= 0:
                    self.player.send_message(f"**The {target_monster_data['name']} has been DEFEATED!**")
                    
                    nominal_xp = 1000 
                    self.player.add_field_exp(nominal_xp)
                    
                    corpse_data = loot_system.create_corpse_object_data(
                        defeated_entity_template=target_monster_data, 
                        defeated_entity_runtime_id=monster_id,
                        game_items_data=GAME_ITEMS,
                        game_loot_tables=GAME_LOOT_TABLES,
                        game_equipment_tables_data={} 
                    )
                    self.room.objects.append(corpse_data)
                    self.room.objects = [obj for obj in self.room.objects if obj.get("monster_id") != monster_id]
                    
                    db.save_room_state(self.room) 
                    
                    self.player.send_message(f"The {corpse_data['name']} falls to the ground.")
                    
                    respawn_time = target_monster_data.get("respawn_time_seconds", 300)
                    respawn_chance = target_monster_data.get(
                        "respawn_chance_per_tick", 
                        getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2)
                    )

                    DEFEATED_MONSTERS[monster_id] = {
                        "room_id": self.room.room_id,
                        "template_key": monster_id,
                        "type": "monster",
                        "eligible_at": time.time() + respawn_time,
                        "chance": respawn_chance
                    }
                    
                    combat_system.stop_combat(player_id, monster_id)
                    return False 
                else:
                    self.player.send_message(f"(The {target_monster_data['name']} has {new_hp} HP remaining)")
            
            return True 
        # --- (End of helper function) ---


        combat_info = COMBAT_STATE.get(player_id)
        is_in_active_combat = combat_info and combat_info.get("target_id")

        if is_in_active_combat:
            # --- PLAYER IS ALREADY IN COMBAT ---
            
            if combat_info["target_id"] != monster_id:
                self.player.send_message(f"You are already fighting the {combat_info['target_id']}!")
                return
                
            if current_time < combat_info["next_action_time"]:
                wait_time = combat_info['next_action_time'] - current_time
                self.player.send_message(f"You are not ready to attack yet. (Wait {wait_time:.1f}s)")
                return
                
            combat_continues = _resolve_and_handle_attack()
            
            if combat_continues:
                base_rt = combat_system.calculate_roundtime(self.player.stats.get("AGI", 50))
                armor_penalty = self.player.armor_rt_penalty
                rt_seconds = base_rt + armor_penalty
                combat_info["next_action_time"] = current_time + rt_seconds
            
        else:
            # --- PLAYER IS INITIATING COMBAT ---
            
            self.player.send_message(f"You attack the **{target_monster_data['name']}**!")
            
            room_id = self.room.room_id
            
            base_rt = combat_system.calculate_roundtime(self.player.stats.get("AGI", 50))
            armor_penalty = self.player.armor_rt_penalty
            rt_seconds = base_rt + armor_penalty
            
            COMBAT_STATE[player_id] = {
                "target_id": monster_id,
                "next_action_time": current_time + rt_seconds, 
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
            
            _resolve_and_handle_attack()