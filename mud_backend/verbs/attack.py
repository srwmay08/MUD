# mud_backend/verbs/attack.py
import time
import copy
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry
from mud_backend import config
from mud_backend.core import combat_system
from mud_backend.core import loot_system
from mud_backend.core import db
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core import faction_handler

@VerbRegistry.register(["attack"])
class Attack(BaseVerb):
    def _trigger_social_aggro(self, target_monster_data: dict):
        target_faction = target_monster_data.get("faction")
        if not target_faction: return

        target_uid = target_monster_data.get("uid")
        player_id = self.player.name.lower()
        current_time = time.time()

        for obj in self.room.objects:
            if obj.get("uid") == target_uid: continue
            if not (obj.get("is_monster") or obj.get("is_npc")): continue
            if obj.get("faction") != target_faction: continue

            mob_uid = obj.get("uid")
            combat_state = self.world.get_combat_state(mob_uid)
            if combat_state and combat_state.get("state_type") == "combat": continue

            monster_name = obj.get("name", "A creature")
            self.player.send_message(f"The {monster_name} comes to the aid of its kin!")
            self.world.broadcast_to_room(self.room.room_id, f"The {monster_name} joins the fight!", "combat_broadcast", skip_sid=self.player.uid)

            monster_agi = obj.get("stats", {}).get("AGI", 50)
            monster_rt = combat_system.calculate_roundtime(monster_agi)

            self.world.set_combat_state(mob_uid, {
                "state_type": "combat",
                "target_id": player_id,
                "next_action_time": current_time + (monster_rt / 2),
                "current_room_id": self.room.room_id
            })
            if self.world.get_monster_hp(mob_uid) is None:
                self.world.set_monster_hp(mob_uid, obj.get("max_hp", 50))

    def _resolve_and_handle_attack(self, target_monster_data: dict, is_offhand: bool = False) -> dict:
        attack_results = combat_system.resolve_attack(
            self.world, self.player, target_monster_data, self.world.game_items, is_offhand=is_offhand
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

            monster_uid = target_monster_data.get("uid")
            new_hp = self.world.modify_monster_hp(
                monster_uid,
                target_monster_data.get("max_hp", 1),
                damage
            )

            if new_hp > 0 and not is_fatal:
                self._trigger_social_aggro(target_monster_data)

            if new_hp <= 0 or is_fatal:
                consequence_msg = f"**The {target_monster_data['name']} has been DEFEATED!**"
                resolve_data["messages"].append(consequence_msg)
                resolve_data["combat_continues"] = False

                monster_id = target_monster_data.get("monster_id")
                if monster_id:
                    self.world.treasure_manager.register_kill(monster_id)

                present_group_members = []
                if self.player.group_id:
                    group_data = self.world.get_group(self.player.group_id)
                    if group_data:
                        for member_name in group_data.get("members", []):
                            p_info = self.world.get_player_info(member_name)
                            if p_info:
                                p_obj = p_info.get("player_obj")
                                if p_obj and p_obj.current_room_id == self.room.room_id:
                                    present_group_members.append(p_obj)
                
                if not present_group_members:
                    present_group_members = [self.player]

                monster_family = target_monster_data.get("family")
                
                for member in present_group_members:
                    if monster_id:
                        key = f"{monster_id}_kills"
                        member.quest_counters[key] = member.quest_counters.get(key, 0) + 1

                    if monster_family:
                        key = f"{monster_family}_kills"
                        member.quest_counters[key] = member.quest_counters.get(key, 0) + 1

                max_level = max(p.level for p in present_group_members)
                monster_level = target_monster_data.get("level", 1)
                level_diff = max_level - monster_level
                
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
                    member_count = len(present_group_members)
                    bonus_multiplier = 1.0 + (0.1 * (member_count - 1)) if member_count > 1 else 1.0
                    total_xp = nominal_xp * bonus_multiplier
                    share_xp = int(total_xp / member_count)

                    for member in present_group_members:
                        member.grant_experience(share_xp, source="combat")
                        if member == self.player:
                            if member_count > 1:
                                resolve_data["messages"].append(f"Group kill! You share experience and gain {share_xp} XP.")
                            else:
                                resolve_data["messages"].append(f"You have gained {share_xp} experience from the kill.")
                        else:
                            member.send_message(f"Your group killed a {target_monster_data['name']}! You share experience and gain {share_xp} XP.")

                monster_faction = target_monster_data.get("faction")
                if monster_faction:
                    adjustments = faction_handler.get_faction_adjustments_on_kill(self.world, monster_faction)
                    for fac_id, amount in adjustments.items():
                        faction_handler.adjust_player_faction(self.player, fac_id, amount)

                corpse_data = loot_system.create_corpse_object_data(
                    target_monster_data, monster_uid, self.world.game_items, self.world.game_loot_tables, {}
                )
                self.room.objects.append(corpse_data)
                if target_monster_data in self.room.objects:
                    self.room.objects.remove(target_monster_data)

                self.world.save_room(self.room)
                self.world.unregister_mob(monster_uid)

                resolve_data["messages"].append(f"The {corpse_data['name']} falls to the ground.")

                respawn_time = target_monster_data.get("respawn_time_seconds", 300)
                respawn_chance = target_monster_data.get("respawn_chance_per_tick", getattr(config, "NPC_DEFAULT_RESPAWN_CHANCE", 0.2))

                self.world.set_defeated_monster(monster_uid, {
                    "room_id": self.room.room_id,
                    "template_key": target_monster_data.get("monster_id"),
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

        if check_action_roundtime(self.player, action_type="attack"):
            return

        target_name = " ".join(self.args).lower()
        target_monster_data = None

        for obj in self.room.objects:
            if obj.get("is_monster") or obj.get("is_npc"):
                uid = obj.get("uid")
                is_defeated = False
                if uid:
                    is_defeated = self.world.get_defeated_monster(uid) is not None

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

        main_weapon = self.player.get_equipped_item_data("mainhand")
        off_weapon = self.player.get_equipped_item_data("offhand")

        is_twc = (main_weapon and main_weapon.get("item_type") == "weapon" and
                  off_weapon and off_weapon.get("item_type") == "weapon")

        current_time = time.time()

        if is_twc:
            res_main = self._resolve_and_handle_attack(target_monster_data, is_offhand=False)
            for msg in res_main["messages"]:
                self.player.send_message(msg)

            if res_main["combat_continues"]:
                res_off = self._resolve_and_handle_attack(target_monster_data, is_offhand=True)
                for msg in res_off["messages"]:
                    self.player.send_message(msg)

            rt_seconds = combat_system.calculate_roundtime_twc(
                self.player.stats, main_weapon, off_weapon
            )

        else:
            res = self._resolve_and_handle_attack(target_monster_data, is_offhand=False)
            for msg in res["messages"]:
                self.player.send_message(msg)

            base_speed = main_weapon.get("base_speed", 3) if main_weapon else 3
            agi = self.player.stats.get("AGI", 50)
            rt_seconds = combat_system.calculate_roundtime(agi, base_speed)

        armor_penalty = self.player.armor_rt_penalty
        final_rt = rt_seconds + armor_penalty

        self.world.set_combat_state(self.player.name.lower(), {
            "state_type": "action",
            "target_id": monster_uid,
            "next_action_time": current_time + final_rt,
            "duration": final_rt,
            "current_room_id": self.room.room_id,
            "rt_type": "hard"
        })
        self.player.send_message(f"Roundtime: {final_rt:.1f}s")

        monster_state = self.world.get_combat_state(monster_uid)
        monster_is_fighting_player = (monster_state and
                                      monster_state.get("state_type") == "combat" and
                                      monster_state.get("target_id") == self.player.name.lower())

        if not monster_is_fighting_player and (target_monster_data not in self.room.objects or self.world.get_defeated_monster(monster_uid)):
            pass 
        elif not monster_is_fighting_player:
            monster_agi = target_monster_data.get("stats", {}).get("AGI", 50)
            monster_rt = combat_system.calculate_roundtime(monster_agi)
            self.world.set_combat_state(monster_uid, {
                "state_type": "combat",
                "target_id": self.player.name.lower(),
                "next_action_time": current_time + (monster_rt / 2),
                "current_room_id": self.room.room_id
            })
            if self.world.get_monster_hp(monster_uid) is None:
                self.world.set_monster_hp(monster_uid, target_monster_data.get("max_hp", 50))