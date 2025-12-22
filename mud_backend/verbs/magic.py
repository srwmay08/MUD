# mud_backend/verbs/magic.py
import time
import math
import random
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.utils import check_action_roundtime, set_action_roundtime
from mud_backend.core.utils import calculate_skill_bonus
from mud_backend.core import combat_system
from mud_backend import config
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["prep", "prepare"])
class Prep(BaseVerb):
    """
    Handles the 'prep' command.
    Usage: PREP <spell_id>
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="cast"):
            return
            
        if not self.args:
            self.player.send_message("Prepare which spell?")
            return

        spell_input = self.args[0].lower()
        spell_id = None
        spell_data = None
        
        # Validate Spell Knowledge
        for known_id in self.player.known_spells:
            s_data = self.world.game_spells.get(known_id)
            if s_data and (known_id == spell_input or s_data["name"].lower().startswith(spell_input)):
                spell_id = known_id
                spell_data = s_data
                break
        
        if not spell_id:
            self.player.send_message("You do not know a spell by that name.")
            return

        # Cost Check
        mana_cost = spell_data.get("mana_cost", 0)
        if self.player.mana < mana_cost:
            self.player.send_message("You do not have enough mana.")
            return

        self.player.mana -= mana_cost
        self.player.prepared_spell = {"spell_id": spell_id, "name": spell_data["name"]}
        
        self.player.send_message(f"You chant the phrases for **{spell_data['name']}**.")
        self.player.send_message("Your spell is ready to CAST.")
        set_action_roundtime(self.player, 1.0, rt_type="hard")

@VerbRegistry.register(["cast", "incant"])
class Cast(BaseVerb):
    """
    Handles the 'cast' command.
    Executes the prepared spell using Warding (CS/TD), Bolt (AS/DS), or Utility logic.
    """
    def execute(self):
        if check_action_roundtime(self.player, action_type="cast"):
            return

        prep = self.player.prepared_spell
        if not prep:
            self.player.send_message("You don't have a spell prepared.")
            return

        spell_id = prep["spell_id"]
        spell_data = self.world.game_spells.get(spell_id)
        self.player.prepared_spell = None # Expire prep
        set_action_roundtime(self.player, 3.0, rt_type="soft")

        if not spell_data: return

        effect_type = spell_data.get("effect")
        
        # --- 1. HEAL / BUFF ---
        if effect_type in ["heal", "buff", "group_buff"]:
            self.player.send_message(f"You cast {spell_data['name']}.")
            if effect_type == "heal":
                self.player.hp = min(self.player.max_hp, self.player.hp + spell_data.get("base_power", 10))
                self.player.send_message("You feel rejuvenated.")
            elif effect_type in ["buff", "group_buff"]:
                 self.player.buffs[spell_id] = {"type": spell_data.get("buff_type"), "val": spell_data.get("base_power")}
                 self.player.send_message("You feel magic surround you.")
            return

        # --- 2. ATTACK SPELLS ---
        # Find target
        if not self.args:
            self.player.send_message("Cast at what?")
            return
        
        target_name = " ".join(self.args).lower()
        target = None
        for obj in self.room.objects:
             if obj.get("is_monster") and not self.world.get_defeated_monster(obj.get("uid")):
                 if target_name in obj.get("keywords", []):
                     target = obj
                     break
        
        if not target:
            self.player.send_message("You don't see that here.")
            return

        # --- 3. WARDING CALCULATION (CS vs TD) ---
        # Default to warding if not specified
        attack_mode = spell_data.get("attack_type", "warding") 
        
        if attack_mode == "warding":
            cs = combat_system.calculate_casting_strength(self.player, spell_data)
            td = combat_system.calculate_target_defense(target, spell_data)
            cva = combat_system.get_cva(target)
            d100 = random.randint(1, 100)
            
            result = cs - td + cva + d100
            
            self.player.send_message(f"You gesture at {target['name']}.")
            self.player.send_message(f"CS: {cs} - TD: {td} + CvA: {cva} + d100: {d100} = {result}")
            
            if result > 100:
                self.player.send_message("Warding success!")
                damage = math.trunc((result - 100) * spell_data.get("base_damage_factor", 0.5))
                self._apply_damage(target, damage)
            else:
                self.player.send_message("Warding failed!")

        # --- 4. MANEUVER CALCULATION (SMR) ---
        elif attack_mode == "maneuver":
            open_d100 = random.randint(1, 100)
            # Exploding roll logic
            if open_d100 > 95: open_d100 += random.randint(1, 100)
            
            skill_bonus = calculate_skill_bonus(self.player.skills.get(spell_data.get("skill", "spiritual_lore"), 0))
            difficulty = target.get("level", 1) * 5
            
            result = open_d100 + skill_bonus - difficulty
            self.player.send_message(f"[SMR Result: {result}]")
            
            if result > 100:
                self.player.send_message("The spell takes hold!")
                damage = spell_data.get("base_power", 10)
                self._apply_damage(target, damage)
            else:
                self.player.send_message("The spell fails.")
                
        # --- 5. BOLT CALCULATION (AS vs DS) ---
        elif attack_mode == "bolt":
            spell_as = combat_system.calculate_bolt_as(
                self.player, self.player.stats, self.player.skills, 
                self.player.stat_modifiers, self.world.game_rules
            )
            spell_as += spell_data.get("bonus_as", 0)
            
            defender_modifiers = combat_system._get_stat_modifiers(target)
            spell_ds = combat_system.calculate_defense_strength(
                target, None, None, None, None, True, 
                target.get("stance", "creature"), defender_modifiers, self.world.game_rules
            )
            
            avd = spell_data.get("avd", 25)
            d100 = random.randint(1, 100)
            result = (spell_as + avd) - spell_ds + d100
            
            self.player.send_message(f"You hurl a bolt at {target['name']}!")
            self.player.send_message(f"AS: {spell_as} - DS: {spell_ds} + AvD: {avd} + d100: {d100} = {result}")
            
            if result > 100:
                 damage = math.trunc((result - 100) * spell_data.get("base_damage_factor", 0.2))
                 self.player.send_message(f"   ... hit for {damage} damage!")
                 self._apply_damage(target, damage)
            else:
                 self.player.send_message("   A clean miss.")


    def _apply_damage(self, target, damage):
        uid = target.get("uid")
        new_hp = self.world.modify_monster_hp(uid, target.get("max_hp", 10), damage)
        
        if new_hp > 0:
            # Trigger social aggro on hit
            combat_system.trigger_social_aggro(self.world, self.room, target, self.player)

        if new_hp <= 0:
            self.player.send_message(f"**The {target['name']} is destroyed!**")
            
            # Use shared death handler (grants loot/xp/etc)
            death_msgs = combat_system.handle_monster_death(self.world, self.player, target, self.room)
            for msg in death_msgs:
                self.player.send_message(msg)