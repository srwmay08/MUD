# mud_backend/verbs/magic.py
import time
import math
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core import combat_system
from mud_backend import config
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["prep", "prepare"])
class Prep(BaseVerb):
    """
    Handles the 'prep' (prepare) command for spells.
    Usage: PREP <spell_id> or PREP <spell_name>
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="cast"):
            return
            
        if not self.args:
            self.player.send_message("What spell do you wish to prepare?")
            return

        args_str = " ".join(self.args).lower()
        parts = args_str.split()
        spell_input = parts[0]
        rank = 1
        if len(parts) > 1:
            try: rank = int(parts[1])
            except ValueError: pass 

        spell_id = None
        spell_display_name = ""
        spell_data = None
        
        game_spells = self.world.game_spells
        
        # --- ADMIN OVERRIDE: Admins can prep any spell in the game ---
        if getattr(self.player, "is_admin", False):
            source_list = game_spells.keys()
        else:
            source_list = self.player.known_spells
        # ------------------------------------------------------------

        for candidate_id in source_list:
            s_data = game_spells.get(candidate_id)
            if not s_data:
                continue
            
            # Match by ID (e.g. "1001") OR Name (e.g. "Minor Ward")
            if (spell_input == str(candidate_id) or 
                spell_input == s_data["name"].lower() or 
                s_data["name"].lower().startswith(spell_input)):
                spell_id = candidate_id
                spell_display_name = s_data["name"]
                spell_data = s_data
                break
        
        if not spell_id or not spell_data:
            self.player.send_message("You do not know that spell.")
            return

        # Check Mana / Spirit cost
        mana_cost = spell_data.get("mana_cost", 0)
        spirit_cost = spell_data.get("spirit_cost", 0)
        
        if mana_cost > 0 and self.player.mana < mana_cost:
            self.player.send_message("You do not have enough mana.")
            return
        if spirit_cost > 0 and self.player.spirit < spirit_cost:
            self.player.send_message("You do not have enough spirit.")
            return

        self.player.mana -= mana_cost
        self.player.spirit -= spirit_cost

        self.player.prepared_spell = {
            "spell_id": spell_id, 
            "rank": rank,
            "mana_cost": mana_cost,
            "spirit_cost": spirit_cost,
            "display_name": spell_display_name
        }
        
        self.player.send_message(f"Your hands glow with power as you invoke the phrase for {spell_display_name}...")
        self.player.send_message("Your spell is ready.")
        
        _set_action_roundtime(self.player, 1.0, rt_type="hard")


@VerbRegistry.register(["cast", "incant"])
class Cast(BaseVerb):
    """
    Handles the 'cast' command.
    Usage: CAST, CAST <target>, or CAST <spell_id> <target> (to confirm)
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="cast"):
            return
            
        prepared_data = self.player.prepared_spell
        if not prepared_data:
            self.player.send_message("You have no spell prepared.")
            return

        spell_id = prepared_data.get("spell_id")
        spell_data = self.world.game_spells.get(spell_id)
        
        if not spell_data:
            self.player.send_message("The magic fizzles. (Spell data not found)")
            self.player.prepared_spell = None
            return

        # --- Check if user typed 'CAST 1001' matches prepared ---
        if self.args:
            first_arg = self.args[0].lower()
            if first_arg == str(spell_id):
                # User typed 'cast 1001' while 1001 is prepped. 
                # Consume this arg so it's not treated as a target name.
                self.args.pop(0)

        # Clear prep
        self.player.prepared_spell = None
        
        _set_action_roundtime(self.player, 3.0, "Cast Roundtime 3 Seconds.", rt_type="soft")

        # --- ADMIN OVERRIDE: Bypass Level Requirement ---
        req_level = spell_data.get("req_level", 0)
        is_admin = getattr(self.player, "is_admin", False)
        
        if self.player.level < req_level and not is_admin:
            self.player.send_message(f"You are not experienced enough to cast {spell_data['name']} (Level {req_level} required).")
            return
        # ------------------------------------------------

        effect_type = spell_data.get("effect")
        skill_name = spell_data.get("skill", "spiritual_lore") 
        skill_ranks = self.player.skills.get(skill_name, 0)
        skill_bonus = calculate_skill_bonus(skill_ranks)

        # --- HANDLER: HEAL ---
        if effect_type == "heal":
            base_heal = spell_data.get("base_power", 10)
            bonus_heal = math.trunc(skill_bonus / 10)
            heal_amount = base_heal + bonus_heal 
            self.player.hp = min(self.player.max_hp, self.player.hp + heal_amount)
            msg = spell_data.get("cast_message_self", "You cast a healing spell.")
            self.player.send_message(f"{msg} (Healed {heal_amount} HP)")
            return

        # --- HANDLER: BUFF & GROUP BUFF ---
        elif effect_type in ["buff", "group_buff"]:
            buff_type = spell_data.get("buff_type")
            base_power = spell_data.get("base_power", 10)
            duration_per_rank = spell_data.get("duration_per_rank", 10)
            duration = max(30, skill_ranks * duration_per_rank)
            
            targets = [self.player]
            if effect_type == "group_buff":
                if self.player.group_id:
                    group = self.world.get_group(self.player.group_id)
                    if group:
                        for member_name in group["members"]:
                            if member_name == self.player.name.lower(): continue
                            member = self.world.get_player_obj(member_name)
                            if member and member.current_room_id == self.player.current_room_id:
                                targets.append(member)

            buff_value = base_power
            if buff_type == "ds_bonus":
                bonus = base_power + math.floor(max(0, skill_ranks - 2) / 3)
                buff_value = min(bonus, max(1, self.player.level))
            elif buff_type == "perception_bonus":
                buff_value = base_power + math.floor(skill_ranks / 2)
            elif buff_type == "armor_padding":
                buff_value = base_power + math.floor(skill_ranks / 10)
            elif buff_type == "sanctuary":
                buff_value = 1
            
            for target in targets:
                target.buffs[spell_id] = {
                    "type": buff_type,
                    "val": buff_value, 
                    "expires_at": time.time() + duration
                }
                if target == self.player:
                    target.send_message(spell_data.get("cast_message_self", "You cast a buff."))
                else:
                    target.send_message(f"{self.player.name} casts {spell_data['name']} on you.")

            if effect_type == "group_buff":
                self.player.send_message(f"You cast {spell_data['name']} on your group.")
            return

        # --- HANDLER: DISPEL ---
        elif effect_type == "dispel":
            target_type = spell_data.get("target_type", "self")
            target = self.player
            
            if target_type == "target":
                if not self.args:
                    self.player.send_message("Dispel who?")
                    return
                t_name = " ".join(self.args).lower()
                t_obj = self.world.get_player_obj(t_name)
                if not t_obj or t_obj.current_room_id != self.player.current_room_id:
                    self.player.send_message("Target not found.")
                    return
                target = t_obj

            if not target.buffs:
                self.player.send_message(f"{target.name} has no effects to dispel.")
                return

            max_effects = spell_data.get("max_effects", 1)
            removed = 0
            keys_to_remove = []
            
            for buff_id in list(target.buffs.keys()):
                if removed >= max_effects: break
                keys_to_remove.append(buff_id)
                removed += 1
            
            for k in keys_to_remove:
                del target.buffs[k]
            
            msg = spell_data.get("cast_message_self" if target == self.player else "cast_message_target", "You cast dispel.")
            self.player.send_message(msg.format(target=target.name))
            if target != self.player:
                target.send_message(f"{self.player.name} dispels magical effects from you!")
            return

        # --- HANDLER: ATTACK ---
        elif effect_type == "attack":
            if not self.args:
                self.player.send_message("Who do you want to cast that on?")
                return

            target_name = " ".join(self.args).lower()
            target_monster = None
            for obj in self.room.objects:
                if obj.get("is_monster") and not self.world.get_defeated_monster(obj.get("uid")):
                    if (target_name == obj.get("name", "").lower() or 
                        target_name in obj.get("keywords", [])):
                        target_monster = obj
                        break
            
            if not target_monster:
                self.player.send_message(f"You don't see a '{target_name}' here to cast at.")
                return

            self.player.send_message(f"You gesture at a {target_monster.get('name')}.")
            msg_target = spell_data.get("cast_message_target", "You attack {target} with magic!")
            self.player.send_message(msg_target.format(target=target_monster.get('name')))

            # --- NEW: Bolt AS Calculation ---
            combat_rules = getattr(self.world, 'game_rules', {})
            spell_as = combat_system.calculate_bolt_as(
                self.player, self.player.stats, self.player.skills, 
                self.player.stat_modifiers, combat_rules
            )
            
            # Bonus AS from specific spell
            spell_as += spell_data.get("bonus_as", 0)

            # --- Defender DS ---
            # Spell Attacks usually check against Ranged DS or specialized Magic DS
            # Using standard calculate_defense_strength with is_ranged=True
            defender_modifiers = combat_system._get_stat_modifiers(target_monster)
            
            # Monsters don't wear armor in item slots usually, assume innate/natural
            # Passing None for items triggers innate checks inside calc
            spell_ds = combat_system.calculate_defense_strength(
                target_monster, 
                None, None, None, None, # No equipment for monster
                True, # is_ranged
                target_monster.get("stance", "creature"),
                defender_modifiers,
                combat_rules
            )
            
            # AvD for Bolts (Usually 0 or specific to spell vs armor)
            # Simplified: Spell AvD vs Target Armor
            # Assuming unarmored/natural for now or need to fetch from spell data
            avd = spell_data.get("avd", 25) # Base spell AvD
            
            d100_roll = random.randint(1, 100)
            combat_roll_result = (spell_as + avd) - spell_ds + d100_roll
            
            roll_string = (f"  AS: +{spell_as} + AvD: +{avd} + d100: +{d100_roll} - DS: -{spell_ds} = +{combat_roll_result}")
            self.player.send_message(roll_string)
            
            if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
                endroll_success_margin = combat_roll_result - config.COMBAT_HIT_THRESHOLD
                damage_factor = spell_data.get("base_damage_factor", 0.25)
                
                bonus_families = spell_data.get("bonus_damage_vs_family", [])
                target_family = target_monster.get("family", "Unknown")
                if target_family in bonus_families:
                    damage_factor *= 2.0
                    self.player.send_message(f"The spell flares brightly against the {target_family}!")
                
                raw_damage = max(1, endroll_success_margin * damage_factor)
                
                critical_divisor = 5
                base_crit_rank = math.trunc(raw_damage / critical_divisor)
                base_crit_rank += spell_data.get("bonus_crit_rank", 0)
                    
                final_crit_rank = combat_system._get_randomized_crit_rank(base_crit_rank)
                hit_location = combat_system._get_random_hit_location(self.world.game_rules)
                
                damage_type = spell_data.get("damage_type", "electricity")
                crit_result = combat_system._get_critical_result(
                    self.world, damage_type, hit_location, final_crit_rank
                )
                
                extra_damage = crit_result["extra_damage"]
                total_damage = math.trunc(raw_damage) + extra_damage
                is_fatal = crit_result.get("fatal", False)
                crit_msg = crit_result.get("message", "A solid hit!").format(defender=target_monster.get("name"))

                self.player.send_message(f"  ... and hit for {total_damage} points of damage!")
                self.player.send_message(f"  {crit_msg}")
                
                monster_uid = target_monster.get("uid")
                new_hp = self.world.modify_monster_hp(
                    monster_uid,
                    target_monster.get("max_hp", 1),
                    total_damage
                )
                
                if new_hp <= 0 or is_fatal:
                    self.player.send_message(f"The {target_monster.get('name')} falls to the ground and dies.")
                    if target_monster in self.room.objects:
                        self.room.objects.remove(target_monster)
                    self.world.set_defeated_monster(monster_uid, { 
                        "room_id": self.room.room_id, 
                        "template_key": target_monster.get("monster_id"),
                        "eligible_at": time.time() + target_monster.get("respawn_time_seconds", 300),
                        "type": "monster"
                    })
                    self.world.stop_combat_for_all(self.player.name.lower(), monster_uid)
                
            else:
                self.player.send_message(f"The spell dissipates harmlessly near the {target_monster.get('name')}.")
            return
            
        else:
            self.player.send_message(f"You cast {spell_data['name']}, but nothing seems to happen. (Effect '{effect_type}' not implemented)")
            return