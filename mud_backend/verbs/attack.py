# mud_backend/verbs/attack.py
import time
import copy 
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend import config 
from mud_backend.core import combat_system
from mud_backend.core import loot_system
from mud_backend.core import db 
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core import faction_handler

class Attack(BaseVerb):
    """
    Handles the 'attack' command.
    """
    
    def _resolve_and_handle_attack(self, target_monster_data: dict) -> dict:
        """
        Resolves one attack swing.
        Returns a dictionary with all message parts and combat results.
        """
        attack_results = combat_system.resolve_attack(
            self.world, self.player, target_monster_data, self.world.game_items
        )

        resolve_data = {
            "hit": attack_results['hit'],
            "is_fatal": False,
            "combat_continues": True,
            "messages": [] 
        }
        
        resolve_data["messages"].append(attack_results['attempt_msg'])
        resolve_data["messages"].append(attack_results['roll_string'])
        resolve_data["messages"].append(attack_results['result_msg'])
        
        if attack_results['hit']:
            if attack_results['critical_msg']:
                resolve_data["messages"].append(attack_results['critical_msg'])
            
            damage = attack_results['damage']
            is_fatal = attack_results['is_fatal']
            resolve_data["is_fatal"] = is_fatal
            new_hp = 0
            
            monster_uid = target_monster_data.get("uid")
            monster_id = target_monster_data.get("monster_id")
            
            new_hp = self.world.modify_monster_hp(
                monster_uid,
                target_monster_data.get("max_hp", 1),
                damage
            )

            if new_hp <= 0 or is_fatal:
                consequence_msg = f"**The {target_monster_data['name']} has been DEFEATED!**"
                resolve_data["messages"].append(consequence_msg)
                resolve_data["combat_continues"] = False 
                
                player_level = self.player.level
                monster_level = target_monster_data.get("level", 1)
                level_diff = player_level - monster_level
                
                nominal_xp = 0
                if level_diff >= 10:
                    nominal_xp = 0
                elif 1 <= level_diff <= 9:
                    nominal_xp = 100 - (10 * level_diff)
                elif level_diff == 0:
                    nominal_xp = 100
                elif -4 <= level_diff <= -1:
                    nominal_xp = 100 + (10 * abs(level_diff))
                elif level_diff <= -5:
                    nominal_xp = 150
                
                nominal_xp = max(0, nominal_xp) 
                
                if nominal_xp > 0:
                    resolve_data["messages"].append(f"You have gained {nominal_xp} experience from the kill.")
                    self.player.grant_experience(nominal_xp, source="combat")
                
                monster_faction = target_monster_data.get("faction")
                if monster_faction:
                    adjustments = faction_handler.get_faction_adjustments_on_kill(
                        self.world, monster_faction
                    )
                    for fac_id, amount in adjustments.items():
                        faction_handler.adjust_player_faction(self.player, fac_id, amount)
                
                corpse_data = loot_system.create_corpse_object_data(
                    defeated_entity_template=target_monster_data, 
                    defeated_entity_runtime_id=monster_uid, 
                    game_items_data=self.world.game_items,
                    game_loot_tables=self.world.game_loot_tables,
                    game_equipment_tables_data={} 
                )
                self.room.objects.append(corpse_data)
                
                # Remove monster from room
                if target_monster_data in self.room.objects:
                    self.room.objects.remove(target_monster_data)
                
                self.world.save_room(self.room)
                
                # --- NEW: Unregister from AI Index ---
                self.world.unregister_mob(monster_uid)
                # -------------------------------------
                
                resolve_data["messages"].append(f"The {corpse_data['name']} falls to the ground.")
                
                respawn_time = target_monster_data.get("respawn_time_seconds", 300)
                respawn_chance = target_monster_data.get(
                    "respawn_chance_per_tick", 
                    getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2)
                )

                self.world.set_defeated_monster(monster_uid, {
                    "room_id": self.room.room_id,
                    "template_key": monster_id,
                    "type": "monster",
                    "eligible_at": time.time() + respawn_time,
                    "chance": respawn_chance,
                    "faction": monster_faction
                })
                self.world.stop_combat_for_all(self.player.name.lower(), monster_uid)
        
        return resolve_data

    
    def execute(self):
        if not self.args:
            self.player.send_message("Attack what?")
            return

        target_name = " ".join(self.args).lower()
        player_id = self.player.name.lower()
        
        target_monster_data = None
        
        for obj in self.room.objects:
            if obj.get("is_monster") or obj.get("is_npc"):
                uid = obj.get("uid")
                is_defeated = False
                if uid:
                    with self.world.defeated_lock:
                        is_defeated = uid in self.world.defeated_monsters
                
                if not is_defeated:
                    if target_name in obj.get("keywords", []) or target_name == obj.get("name", "").lower():
                        target_monster_data = obj
                        break

        if not target_monster_data:
            self.player.send_message(f"You don't see a '{target_name}' here to attack.")
            return

        monster_uid = target_monster_data.get("uid")

        if not monster_uid:
            self.player.send_message("That creature cannot be attacked right now.")
            return
            
        with self.world.defeated_lock:
            if monster_uid in self.world.defeated_monsters:
                self.player.send_message(f"The {target_monster_data['name']} is already dead.")
                return
        
        current_time = time.time()

        if _check_action_roundtime(self.player, action_type="attack"):
            return
        
        combat_info = self.world.get_combat_state(player_id)
        monster_state = self.world.get_combat_state(monster_uid)
        monster_is_fighting_player = (monster_state and 
                                      monster_state.get("state_type") == "combat" and 
                                      monster_state.get("target_id") == player_id)

        if not monster_is_fighting_player:
             self.player.send_message(f"You attack the **{target_monster_data['name']}**!")
        
        resolve_data = self._resolve_and_handle_attack(target_monster_data)
        
        for msg in resolve_data["messages"]:
            self.player.send_message(msg)
            
        combat_continues = resolve_data["combat_continues"]
        
        if combat_continues:
            room_id = self.room.room_id
            base_rt = combat_system.calculate_roundtime(self.player.stats.get("AGI", 50))
            armor_penalty = self.player.armor_rt_penalty
            rt_seconds = base_rt + armor_penalty
            monster_rt = combat_system.calculate_roundtime(target_monster_data.get("stats", {}).get("AGI", 50))
            
            self.world.set_combat_state(player_id, {
                "state_type": "action",
                "target_id": monster_uid, 
                "next_action_time": current_time + rt_seconds, 
                "current_room_id": room_id,
                "rt_type": "hard" 
            })
            
            self.player.send_message(f"Roundtime: {rt_seconds:.1f}s")
            
            if not monster_is_fighting_player:
                self.world.set_combat_state(monster_uid, {
                    "state_type": "combat",
                    "target_id": player_id,
                    "next_action_time": current_time + (monster_rt / 2),
                    "current_room_id": room_id
                })
                if self.world.get_monster_hp(monster_uid) is None:
                     self.world.set_monster_hp(monster_uid, target_monster_data.get("max_hp", 50))