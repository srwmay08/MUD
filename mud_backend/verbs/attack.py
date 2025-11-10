# mud_backend/verbs/attack.py
import time
import copy 
from mud_backend.verbs.base_verb import BaseVerb
# --- REFACTORED: Removed all game_state imports ---
from mud_backend import config 
from mud_backend.core import combat_system
from mud_backend.core import loot_system
from mud_backend.core import db 
# --- NEW: Import new RT functions ---
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
# --- END NEW ---

class Attack(BaseVerb):
    """
    Handles the 'attack' command.
    """
    
    # ---
    # --- NEW: Refactored helper function to return structured data
    # ---
    def _resolve_and_handle_attack(self, target_monster_data: dict) -> dict:
        """
        Resolves one attack swing.
        Returns a dictionary with all message parts and combat results.
        """
        # --- FIX: Pass self.world.game_items AND self.world ---
        attack_results = combat_system.resolve_attack(
            self.world, self.player, target_monster_data, self.world.game_items
        )

        # This dictionary will be returned
        resolve_data = {
            "hit": attack_results['hit'],
            "is_fatal": False,
            "combat_continues": True,
            "messages": [] # A list of messages to print in order
        }
        
        # 1. Flavor Text (e.g., "You swing...")
        resolve_data["messages"].append(attack_results['attacker_msg'])
        
        # 2. Roll String
        resolve_data["messages"].append(attack_results['roll_string'])
        
        if attack_results['hit']:
            # 3. Damage Text
            resolve_data["messages"].append(attack_results['damage_msg'])
            
            # 4. Consequences (HP, Death)
            damage = attack_results['damage']
            is_fatal = attack_results['is_fatal'] # <-- GET FATAL FLAG
            resolve_data["is_fatal"] = is_fatal
            new_hp = 0
            
            monster_uid = target_monster_data.get("uid")
            monster_id = target_monster_data.get("monster_id")
            
            # --- FIX: Use self.world.modify_monster_hp ---
            new_hp = self.world.modify_monster_hp(
                monster_uid,
                target_monster_data.get("max_hp", 1),
                damage
            )

            if new_hp <= 0 or is_fatal: # <-- CHECK FATAL FLAG
                resolve_data["messages"].append(f"**The {target_monster_data['name']} has been DEFEATED!**")
                resolve_data["combat_continues"] = False # Combat ends
                
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
                
                self.world.save_room(self.room)
                
                resolve_data["messages"].append(f"The {corpse_data['name']} falls to the ground.")
                
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
                self.world.stop_combat_for_all(self.player.name.lower(), monster_uid)
        
        return resolve_data
    # --- (End of helper function) ---

    
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

        # ---
        # --- MODIFIED: Check RT using new function
        # ---
        if _check_action_roundtime(self.player, action_type="attack"):
            return
        # --- END MODIFIED ---
        
        # --- FIX: Use self.world.get_combat_state ---
        combat_info = self.world.get_combat_state(player_id)
        monster_state = self.world.get_combat_state(monster_uid)
        monster_is_fighting_player = (monster_state and 
                                      monster_state.get("state_type") == "combat" and 
                                      monster_state.get("target_id") == player_id)

        # Check if player is switching targets (using UID)
        if combat_info and combat_info.get("target_id") and combat_info.get("target_id") != monster_uid:
            pass # TODO: Add logic for switching targets

        if not monster_is_fighting_player:
             self.player.send_message(f"You attack the **{target_monster_data['name']}**!")
        
        # ---
        # --- MODIFIED: Resolve attack and print messages in order
        # ---
        resolve_data = self._resolve_and_handle_attack()
        
        # Print all messages from the resolve data
        for msg in resolve_data["messages"]:
            self.player.send_message(msg)
            
        combat_continues = resolve_data["combat_continues"]
        # --- END MODIFIED ---
        
        # --- Set RT and Monster AI (if combat didn't end) ---
        if combat_continues:
            room_id = self.room.room_id
            base_rt = combat_system.calculate_roundtime(self.player.stats.get("AGI", 50))
            armor_penalty = self.player.armor_rt_penalty
            rt_seconds = base_rt + armor_penalty
            monster_rt = combat_system.calculate_roundtime(target_monster_data.get("stats", {}).get("AGI", 50))
            
            # --- FIX: Use self.world.set_combat_state/set_monster_hp ---
            # Set Player's RT using UID as target
            # --- MODIFIED: Set rt_type to "hard" ---
            self.world.set_combat_state(player_id, {
                "state_type": "action",
                "target_id": monster_uid, 
                "next_action_time": current_time + rt_seconds, 
                "current_room_id": room_id,
                "rt_type": "hard" # <-- NEW
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