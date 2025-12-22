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
from mud_backend.core.utils import check_action_roundtime
from mud_backend.core import faction_handler

@VerbRegistry.register(["attack"])
class Attack(BaseVerb):
    """
    Handles the 'attack' command.
    Supports Single Weapon and Two-Weapon Combat (TWC).
    """

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
                # Use shared core social aggro logic
                combat_system.trigger_social_aggro(self.world, self.room, target_monster_data, self.player)

            if new_hp <= 0 or is_fatal:
                consequence_msg = f"**The {target_monster_data['name']} has been DEFEATED!**"
                resolve_data["messages"].append(consequence_msg)
                resolve_data["combat_continues"] = False

                # Use shared core death handler
                death_messages = combat_system.handle_monster_death(
                    self.world, self.player, target_monster_data, self.room
                )
                resolve_data["messages"].extend(death_messages)

        return resolve_data

    def execute(self):
        if not self.args:
            self.player.send_message("Attack what?")
            return

        if check_action_roundtime(self.player, action_type="attack"):
            return

        target_name = " ".join(self.args).lower()
        target_monster_data = None

        # Find Target
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

        # Check TWC
        main_weapon = self.player.get_equipped_item_data("mainhand")
        off_weapon = self.player.get_equipped_item_data("offhand")

        is_twc = (main_weapon and main_weapon.get("item_type") == "weapon" and
                  off_weapon and off_weapon.get("item_type") == "weapon")

        current_time = time.time()

        if is_twc:
            # 1. Execute Main Attack
            res_main = self._resolve_and_handle_attack(target_monster_data, is_offhand=False)
            for msg in res_main["messages"]:
                self.player.send_message(msg)

            # 2. Execute Offhand Attack (if target alive)
            if res_main["combat_continues"]:
                res_off = self._resolve_and_handle_attack(target_monster_data, is_offhand=True)
                for msg in res_off["messages"]:
                    self.player.send_message(msg)

            # 3. Apply TWC Roundtime
            rt_seconds = combat_system.calculate_roundtime_twc(
                self.player.stats, main_weapon, off_weapon
            )

        else:
            # Standard Attack
            res = self._resolve_and_handle_attack(target_monster_data, is_offhand=False)
            for msg in res["messages"]:
                self.player.send_message(msg)

            # Standard Roundtime
            base_speed = main_weapon.get("base_speed", 3) if main_weapon else 3
            agi = self.player.stats.get("AGI", 50)
            rt_seconds = combat_system.calculate_roundtime(agi, base_speed)

        # Apply RT to Player
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

        # Ensure Monster Aggro
        monster_state = self.world.get_combat_state(monster_uid)
        monster_is_fighting_player = (monster_state and
                                      monster_state.get("state_type") == "combat" and
                                      monster_state.get("target_id") == self.player.name.lower())

        if not monster_is_fighting_player and (target_monster_data not in self.room.objects or self.world.get_defeated_monster(monster_uid)):
            pass # Monster died, no aggro needed
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