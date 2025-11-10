# mud_backend/verbs/magic.py
import time
import math
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.verbs.foraging import _check_action_roundtime, _set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus
from mud_backend.core import combat_system

# --- Spell Definitions ---
# spell_id: { mana_cost, min_rank, max_rank }
SPELL_BOOK = {
    "heal": {
        "name": "Minor Heal",
        "mana_cost": 10
    },
    "shock": {
        "name": "Minor Shock",
        "mana_cost": 10
    },
    "spirit_shield": {
        "name": "Spirit Shield",
        "mana_cost": 15
    }
}


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
        spell_name = parts[0]
        rank = 1
        if len(parts) > 1:
            try: rank = int(parts[1])
            except ValueError: pass # default to rank 1

        # Find the spell in our "book"
        spell_id = None
        spell_display_name = ""
        for key, data in SPELL_BOOK.items():
            if spell_name in data["name"].lower():
                spell_id = key
                spell_display_name = data["name"]
                break
        
        if not spell_id:
            self.player.send_message("You do not know that spell.")
            return

        spell_data = SPELL_BOOK[spell_id]
        mana_cost = spell_data.get("mana_cost", 10)
        
        if self.player.mana < mana_cost:
            self.player.send_message("You do not have enough mana to prepare that spell.")
            return
            
        # All checks pass. Prepare the spell.
        self.player.mana -= mana_cost
        self.player.prepared_spell = {
            "spell": spell_id,
            "rank": rank,
            "cost": mana_cost,
            "display_name": spell_display_name
        }
        
        self.player.send_message(f"Your hands glow with power as you invoke the phrase for {spell_display_name}...")
        self.player.send_message("Your spell is ready.")
        
        # Prep is a short hard RT
        _set_action_roundtime(self.player, 1.0, rt_type="hard")


class Cast(BaseVerb):
    """
    Handles the 'cast' command.
    """
    def execute(self):
        if _check_action_roundtime(self.player, action_type="cast"):
            return
            
        spell_data = self.player.prepared_spell
        
        if not spell_data:
            self.player.send_message("You have no spell prepared.")
            return

        # Clear the spell *before* execution
        self.player.prepared_spell = None
        
        # --- CASTING IS ALWAYS SOFT RT ---
        _set_action_roundtime(self.player, 3.0, "Cast Roundtime 3 Seconds.", rt_type="soft")

        spell_id = spell_data.get("spell")
        
        # ---
        # --- Branch 1: Heal (Self-cast)
        # ---
        if spell_id == "heal":
            heal_amount = 10 # Rank 1
            self.player.hp = min(self.player.max_hp, self.player.hp + heal_amount)
            self.player.send_message("A warm, restorative light washes over you. You feel a bit better.")
            # TODO: Add target logic
            return

        # ---
        # --- Branch 2: Spirit Shield (Self-cast buff)
        # ---
        if spell_id == "spirit_shield":
            lore_ranks = self.player.skills.get("spiritual_lore", 0)
            
            # DS increase = [10 + ((Spiritual Lore Blessings - 2) ÷ 3)]
            # We use spiritual_lore ranks for "Spiritual Lore Blessings"
            bonus = 10 + math.floor(max(0, lore_ranks - 2) / 3)
            
            # Capped at caster's level (level 0 counts as 1 for cap)
            bonus = min(bonus, max(1, self.player.level))
            
            # Duration: 10 seconds per rank of spiritual_lore
            duration = max(30, lore_ranks * 10) # 30s minimum
            
            self.player.buffs["spirit_shield"] = {
                "ds_bonus": bonus, 
                "expires_at": time.time() + duration
            }
            self.player.send_message("A dim aura surrounds you.")
            return

        # ---
        # --- Branch 3: Shock (Targeted attack spell)
        # ---
        if spell_id == "shock":
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
            self.player.send_message(f"You hurl a small surge of electricity at a {target_monster.get('name')}!")

            # --- Spell Combat ---
            # AS: (Spiritual Lore skill bonus * 4)
            lore_ranks = self.player.skills.get("spiritual_lore", 0)
            spell_as = calculate_skill_bonus(lore_ranks) * 4 # Per your example
            
            # DS: (Target's WIS bonus)
            spell_ds = get_stat_bonus(
                target_monster.get("stats", {}).get("WIS", 50), 
                "WIS", 
                target_monster.get("race", "Human")
            )
            
            # AvD: (Caster's INT bonus + Caster's WIS bonus) / 2
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
                damage_factor = 0.25 # Magic damage factor
                
                raw_damage = max(1, endroll_success_margin * damage_factor)
                
                critical_divisor = 5 # Magic has a low divisor
                base_crit_rank = math.trunc(raw_damage / critical_divisor)
                final_crit_rank = combat_system._get_randomized_crit_rank(base_crit_rank)
                hit_location = combat_system._get_random_hit_location()
                
                # Use new "electricity" crit table
                crit_result = combat_system._get_critical_result(
                    self.world, "electricity", hit_location, final_crit_rank
                )
                
                extra_damage = crit_result["extra_damage"]
                total_damage = math.trunc(raw_damage) + extra_damage
                is_fatal = crit_result.get("fatal", False)
                crit_msg = crit_result.get("message", "A solid jolt!").format(defender=target_monster.get("name"))

                self.player.send_message(f"  ... and hit for {total_damage} points of damage!")
                self.player.send_message(f"  {crit_msg}")
                
                # --- Apply damage and check for death ---
                monster_uid = target_monster.get("uid")
                new_hp = self.world.modify_monster_hp(
                    monster_uid,
                    target_monster.get("max_hp", 1),
                    total_damage
                )
                
                if new_hp <= 0 or is_fatal:
                    self.player.send_message(f"The {target_monster.get('name')} falls to the ground and dies.")
                    # (Simplified death, no XP/loot for this example)
                    # --- This is a basic implementation, doesn't add corpse/loot ---
                    if target_monster in self.room.objects:
                        self.room.objects.remove(target_monster)
                    self.world.set_defeated_monster(monster_uid, { "room_id": self.room.room_id, "template_key": target_monster.get("monster_id")})
                    self.world.stop_combat_for_all(self.player.name.lower(), monster_uid)
                
            else:
                # --- Miss! ---
                self.player.send_message(f"The surge of electricity dissipates harmlessly near the {target_monster.get('name')}.")

            return