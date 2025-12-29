# mud_backend/verbs/maneuvers.py
import random
import time
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend.core import combat_system
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime, calculate_skill_bonus, get_stat_bonus

@VerbRegistry.register(["perform", "maneuver", "trip"]) 
class Perform(BaseVerb):
    """
    PERFORM <maneuver> <target>
    or
    TRIP <target>
    
    Executes a learned combat maneuver.
    Supported: Feint, Sweep, Disarm, Sunder, Trip
    """
    def execute(self):
        # 1. Check Roundtime
        if check_action_roundtime(self.player, action_type="attack"):
            return

        matched_maneuver = None
        target_name = None

        # 2. Parse Arguments (Direct Command vs Perform)
        if self.command_keyword == "trip":
            matched_maneuver = "trip"
            target_name = " ".join(self.args).lower()
        else:
            # Handle "PERFORM <maneuver> <target>"
            if not self.args:
                self.player.send_message("Perform what maneuver?")
                return

            args_str = " ".join(self.args).lower()
            
            # Sort known maneuvers by length (descending) to match "shield bash" before "shield"
            known_sorted = sorted(self.player.known_maneuvers, key=len, reverse=True)
            
            # Allow "trip" to be performed even if not explicitly in known_maneuvers yet (for the quest)
            # or ensure it's handled if the player types "perform trip"
            check_list = known_sorted + ["trip"]
            
            for m_key in check_list:
                m_name_display = m_key.replace("_", " ")
                if args_str.startswith(m_name_display):
                    matched_maneuver = m_key
                    # The rest of the string is the target
                    remainder = args_str[len(m_name_display):].strip()
                    if remainder:
                        target_name = remainder
                    break
        
        if not matched_maneuver:
            self.player.send_message("You don't know that maneuver (or you mistyped it).")
            return

        # 3. Resolve Target
        target = None
        
        if not target_name:
            # Auto-target last combatant
            last_target_id = self.player.combat_state.get("last_target")
            if last_target_id:
                possible_target = self.world.get_instance(last_target_id)
                if possible_target and possible_target.current_room_id == self.room.room_id:
                    target = possible_target
            
            if not target:
                self.player.send_message(f"Perform {matched_maneuver.replace('_',' ')} on whom?")
                return
        else:
            # --- ID MATCHING ---
            if target_name.startswith("#"):
                target_uid = target_name[1:]
                
                # Check Players in Room
                room_players = self.world.room_players.get(self.room.room_id, [])
                for p_name in room_players:
                    p_obj = self.world.get_player_obj(p_name)
                    if p_obj and str(p_obj.uid) == target_uid:
                        target = p_obj
                        break
                
                # Check Mobs in Room
                if not target:
                    for obj in self.room.objects:
                        if str(obj.get("uid")) == target_uid:
                            if obj.get("is_monster") or obj.get("is_npc"):
                                target = obj
                            break
            # -------------------
            
            # --- NAME MATCHING ---
            if not target:
                # Check Players
                room_players = self.world.room_players.get(self.room.room_id, [])
                for p_name in room_players:
                    if p_name == target_name:
                        target = self.world.get_player_obj(p_name)
                        break
                
                # Check Monsters
                if not target:
                    for obj in self.room.objects:
                        if (obj.get("name", "").lower() == target_name or 
                            target_name in obj.get("keywords", [])):
                            if obj.get("is_monster") or obj.get("is_npc"):
                                target = obj
                                break
            # ---------------------

            if not target:
                self.player.send_message(f"You don't see '{target_name}' here.")
                return

        if target == self.player:
            self.player.send_message("You cannot perform maneuvers on yourself.")
            return

        # 4. Dispatch Maneuver Logic
        if matched_maneuver == "feint":
            self._do_feint(target)
        elif matched_maneuver == "sweep":
            self._do_sweep(target)
        elif matched_maneuver == "disarm":
            self._do_disarm(target)
        elif matched_maneuver == "sunder":
            self._do_sunder(target)
        elif matched_maneuver == "trip":
            self._do_trip(target)
        else:
            self.player.send_message(f"The maneuver '{matched_maneuver}' is not yet implemented mechanically.")


    def _do_feint(self, target):
        # Cost: 10 Stamina
        if self.player.stamina < 10:
            self.player.send_message("You are too exhausted to feint.")
            return
        self.player.stamina -= 10

        # Formula: (Weapon Skill + AGI Bonus + d100) vs (Target Level * 5 + Target WIS Bonus + d100)
        
        # Attack
        # A simple fallback: Use Combat Maneuvers skill
        cm_rank = self.player.skills.get("combat_maneuvers", 0)
        cm_bonus = calculate_skill_bonus(cm_rank)
        agi_bonus = get_stat_bonus(self.player.stats.get("AGI", 50), "AGI", self.player.stat_modifiers)
        roll = random.randint(1, 100)
        attack_total = cm_bonus + agi_bonus + roll

        # Defense
        target_lvl = target.get("level", 1)
        target_wis = target.get("stats", {}).get("WIS", 50)
        wis_bonus = get_stat_bonus(target_wis, "WIS", combat_system._get_stat_modifiers(target))
        def_roll = random.randint(1, 100)
        defense_total = (target_lvl * 5) + wis_bonus + def_roll

        self.player.send_message(f"You attempt to feint {target.get('name')}! (Roll: {attack_total} vs {defense_total})")
        
        margin = attack_total - defense_total
        
        if margin > 0:
            self.player.send_message(f"Success! {target.get('name')} falls for your trick and is left open.")
            
            # Effect: Reduce target stance effectiveness
            debuff_id = "feint_open"
            combat_system.apply_status_effect(target, debuff_id, duration=10, data={"defense_penalty": 25})
            
        else:
            self.player.send_message(f"{target.get('name')} ignores your feint.")

        set_action_roundtime(self.player, 3.0)


    def _do_sweep(self, target):
        if self.player.stamina < 15:
            self.player.send_message("Too exhausted.")
            return
        self.player.stamina -= 15

        cm_rank = self.player.skills.get("combat_maneuvers", 0)
        cm_bonus = calculate_skill_bonus(cm_rank)
        str_bonus = get_stat_bonus(self.player.stats.get("STR", 50), "STR", self.player.stat_modifiers)
        roll = random.randint(1, 100)
        attack = cm_bonus + str_bonus + roll

        t_agi = target.get("stats", {}).get("AGI", 50)
        t_agi_bonus = get_stat_bonus(t_agi, "AGI", combat_system._get_stat_modifiers(target))
        t_level = target.get("level", 1)
        defense = (t_level * 5) + t_agi_bonus + random.randint(1, 100)

        self.player.send_message(f"You drop low and attempt to sweep {target.get('name')}'s legs.")

        if attack > defense:
            self.player.send_message(f"**CRASH!** {target.get('name')} hits the ground hard!")
            damage = random.randint(1, 5) # Minor fall damage
            
            # Apply Prone
            combat_system.apply_status_effect(target, "prone", duration=15)
            
            # Deal damage
            new_hp = self.world.modify_monster_hp(target.get("uid"), target.get("max_hp", 10), damage)
            if new_hp <= 0:
                self.player.send_message(f"{target.get('name')} dies from the fall!")
                combat_system.handle_monster_death(self.world, self.player, target, self.room)
        else:
            self.player.send_message(f"{target.get('name')} nimbly hops over your leg.")

        set_action_roundtime(self.player, 5.0)

    def _do_trip(self, target):
        """
        Trip logic, similar to sweep but distinct for the quest line.
        """
        if self.player.stamina < 10:
            self.player.send_message("You are too exhausted to attempt a trip.")
            return
        self.player.stamina -= 10

        # Calculations
        cm_rank = self.player.skills.get("combat_maneuvers", 0)
        cm_bonus = calculate_skill_bonus(cm_rank)
        str_bonus = get_stat_bonus(self.player.stats.get("STR", 50), "STR", self.player.stat_modifiers)
        roll = random.randint(1, 100)
        attack = cm_bonus + str_bonus + roll

        # Defense
        t_agi = target.get("stats", {}).get("AGI", 50)
        t_agi_bonus = get_stat_bonus(t_agi, "AGI", combat_system._get_stat_modifiers(target))
        t_level = target.get("level", 1)
        defense = (t_level * 5) + t_agi_bonus + random.randint(1, 100)

        self.player.send_message(f"You hook your weapon around {target.get('name')}'s leg and pull!")

        if attack > defense:
            self.player.send_message(f"**THUD!** {target.get('name')} loses their balance and falls prone!")
            
            # Apply Prone
            combat_system.apply_status_effect(target, "prone", duration=10)
            
            # --- QUEST LOGIC ---
            # If target is the Grizzled Warrior trainer, update the quest
            if target.get("monster_id") == "grizzled_warrior":
                self.player.quest_counters["quest_trip_success"] = 1
                self.player.send_message("The warrior grunts in approval. 'Not bad! Talk to me again.'")
                self.player.mark_dirty()
            # -------------------

        else:
            self.player.send_message(f"{target.get('name')} steps firmly out of your trip attempt.")

        set_action_roundtime(self.player, 4.0)

    def _do_disarm(self, target):
        if self.player.stamina < 20: return
        self.player.stamina -= 20
        
        # Placeholder for Monster Disarm
        self.player.send_message(f"You attempt to disarm {target.get('name')}... but they have a death grip (or no weapon)!")
        set_action_roundtime(self.player, 4.0)


    def _do_sunder(self, target):
        if self.player.stamina < 20: return
        self.player.stamina -= 20
        
        self.player.send_message(f"You strike a heavy blow at {target.get('name')}'s defenses!")
        
        combat_system.perform_attack(self.player, target, self.room, self.world, maneuver_bonus="sunder")
        
        set_action_roundtime(self.player, 7.0)