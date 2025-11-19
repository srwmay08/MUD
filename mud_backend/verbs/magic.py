# mud_backend/verbs/magic.py
# MODIFIED FILE
import time
import math
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core import combat_system
from mud_backend import config 

class Prep(BaseVerb):
    """
    Handles the 'prep' (prepare) command for spells.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="cast"):
            return
            
        if not self.args:
            self.player.send_message("What spell do you wish to prepare?")
            return

        args_str = " ".join(self.args).lower()
        parts = args_str.split()
        spell_name_input = parts[0]
        rank = 1
        if len(parts) > 1:
            try: rank = int(parts[1])
            except ValueError: pass # default to rank 1

        # Find the spell in the World spell list
        spell_id = None
        spell_display_name = ""
        spell_data = None
        
        # --- NEW: Use world spell cache ---
        game_spells = self.world.game_spells
        
        for known_spell_id in self.player.known_spells:
            s_data = game_spells.get(known_spell_id)
            if not s_data:
                continue
                
            # Find by exact match or starting keyword in name
            if (spell_name_input == s_data["name"].lower() or 
                s_data["name"].lower().startswith(spell_name_input)):
                spell_id = known_spell_id
                spell_display_name = s_data["name"]
                spell_data = s_data
                break
        
        if not spell_id or not spell_data:
            self.player.send_message("You do not know that spell.")
            return

        # Check Mana / Spirit cost
        mana_cost = spell_data.get("mana_cost", 0)
        spirit_cost = spell_data.get("spirit_cost", 0)
        
        if mana_cost > 0:
            if self.player.mana < mana_cost:
                self.player.send_message("You do not have enough mana to prepare that spell.")
                return
            self.player.mana -= mana_cost
            
        elif spirit_cost > 0:
            if self.player.spirit < spirit_cost:
                self.player.send_message("You do not have enough spirit to prepare that spell.")
                return
            self.player.spirit -= spirit_cost

        self.player.prepared_spell = {
            "spell_id": spell_id, # Changed key from "spell" to "spell_id" for consistency
            "rank": rank,
            "mana_cost": mana_cost,
            "spirit_cost": spirit_cost,
            "display_name": spell_display_name
        }
        
        self.player.send_message(f"Your hands glow with power as you invoke the phrase for {spell_display_name}...")
        self.player.send_message("Your spell is ready.")
        
        _set_action_roundtime(self.player, 1.0, rt_type="hard")


class Cast(BaseVerb):
    """
    Handles the 'cast' command.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="cast"):
            return
            
        prepared_data = self.player.prepared_spell
        if not prepared_data:
            self.player.send_message("You have no spell prepared.")
            return

        # Clear the spell *before* execution
        self.player.prepared_spell = None
        
        # Soft RT for casting
        _set_action_roundtime(self.player, 3.0, "Cast Roundtime 3 Seconds.", rt_type="soft")

        spell_id = prepared_data.get("spell_id")
        # --- NEW: Look up data from world cache ---
        spell_data = self.world.game_spells.get(spell_id)
        
        if not spell_data:
            self.player.send_message("The magic fizzles. (Spell data not found)")
            return

        effect_type = spell_data.get("effect")
        skill_name = spell_data.get("skill", "spiritual_lore") # Default skill
        skill_ranks = self.player.skills.get(skill_name, 0)
        skill_bonus = calculate_skill_bonus(skill_ranks)

        # --- HANDLER: HEAL ---
        if effect_type == "heal":
            base_heal = spell_data.get("base_power", 10)
            # Scaling: +1 healing per 10 skill bonus
            bonus_heal = math.trunc(skill_bonus / 10)
            heal_amount = base_heal + bonus_heal 
            
            self.player.hp = min(self.player.max_hp, self.player.hp + heal_amount)
            
            msg = spell_data.get("cast_message_self", "You cast a healing spell.")
            self.player.send_message(f"{msg} (Healed {heal_amount} HP)")
            return

        # --- HANDLER: BUFF ---
        elif effect_type == "buff":
            buff_type = spell_data.get("buff_type")
            base_power = spell_data.get("base_power", 10)
            duration_per_rank = spell_data.get("duration_per_rank", 10)
            
            if buff_type == "ds_bonus":
                # DS Bonus Calculation
                # Base + ((Skill - 2) / 3)
                bonus = base_power + math.floor(max(0, skill_ranks - 2) / 3)
                # Capped at level
                bonus = min(bonus, max(1, self.player.level))
                
                duration = max(30, skill_ranks * duration_per_rank)
                
                self.player.buffs[spell_id] = {
                    "ds_bonus": bonus, 
                    "expires_at": time.time() + duration
                }
                msg = spell_data.get("cast_message_self", "You cast a buff.")
                self.player.send_message(msg)
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

            # --- Combat Math ---
            # AS = (Skill Bonus * 4) + Spell Bonus
            spell_as = skill_bonus * 4 
            spell_as += spell_data.get("bonus_as", 0)
            
            # DS: Target WIS
            spell_ds = get_stat_bonus(
                target_monster.get("stats", {}).get("WIS", 50), 
                "WIS", 
                target_monster.get("race", "Human")
            )
            
            # AvD: (Caster INT + Caster WIS) / 2
            int_b = get_stat_bonus(self.player.stats.get("INT", 50), "INT", self.player.race)
            wis_b = get_stat_bonus(self.player.stats.get("WIS", 50), "WIS", self.player.race)
            avd = math.trunc((int_b + wis_b) / 2)
            
            d100_roll = random.randint(1, 100)
            combat_roll_result = (spell_as - spell_ds) + avd + d100_roll
            
            roll_string = (
                f"  AS: +{spell_as} vs DS: +{spell_ds} with AvD: +{avd} + d100 roll: +{d100_roll} = +{combat_roll_result}"
            )
            self.player.send_message(roll_string)
            
            if combat_roll_result > config.COMBAT_HIT_THRESHOLD:
                # --- Hit! ---
                endroll_success_margin = combat_roll_result - config.COMBAT_HIT_THRESHOLD
                
                damage_factor = spell_data.get("base_damage_factor", 0.25)
                raw_damage = max(1, endroll_success_margin * damage_factor)
                
                critical_divisor = 5
                base_crit_rank = math.trunc(raw_damage / critical_divisor)
                base_crit_rank += spell_data.get("bonus_crit_rank", 0)
                    
                final_crit_rank = combat_system._get_randomized_crit_rank(base_crit_rank)
                hit_location = combat_system._get_random_hit_location()
                
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
                
                # --- Apply damage ---
                monster_uid = target_monster.get("uid")
                new_hp = self.world.modify_monster_hp(
                    monster_uid,
                    target_monster.get("max_hp", 1),
                    total_damage
                )
                
                if new_hp <= 0 or is_fatal:
                    self.player.send_message(f"The {target_monster.get('name')} falls to the ground and dies.")
                    # Handle death via generic combat system
                    # (This simplified version just removes it from room)
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
                # --- Miss! ---
                self.player.send_message(f"The spell dissipates harmlessly near the {target_monster.get('name')}.")

            return
            
        # --- Unknown Effect ---
        else:
            self.player.send_message(f"You cast {spell_data['name']}, but nothing seems to happen. (Effect '{effect_type}' not implemented)")
            return