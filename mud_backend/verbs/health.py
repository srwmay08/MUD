# mud_backend/verbs/health.py
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry

@VerbRegistry.register(["health", "hp"]) 
class Health(BaseVerb):
    """Handles the 'health' command."""
    def execute(self):
        player = self.player
        current_hp = player.hp
        max_hp = player.max_hp
        percent_hp = (current_hp / max_hp) * 100
        
        if current_hp <= 0: status = "**DEAD**"
        elif percent_hp > 90: status = "in excellent shape"
        elif percent_hp > 75: status = "in good shape"
        elif percent_hp > 50: status = "lightly wounded"
        elif percent_hp > 25: status = "moderately wounded"
        elif percent_hp > 10: status = "badly wounded"
        else: status = "near death"

        death_sting_msg = "None"
        if hasattr(player, "death_sting_points") and player.death_sting_points > 0:
            death_sting_msg = f"{player.death_sting_points} points (XP gain reduced)"

        con_loss_msg = "None"
        if hasattr(player, "con_lost") and player.con_lost > 0:
            pool = getattr(player, "con_recovery_pool", 0)
            con_loss_msg = f"{player.con_lost} points lost (Recovery pool: {pool:,})"
            
        self.player.send_message("--- **Health Status** ---")
        self.player.send_message(f"HP: {current_hp}/{max_hp} ({status})")
        self.player.send_message(f"CON Loss: {con_loss_msg}")
        self.player.send_message(f"Death's Sting: {death_sting_msg}")
        
        if hasattr(self.player, "wounds") and self.player.wounds:
            self.player.send_message("\n--- **Active Wounds** ---")
            wound_descs = self.world.game_criticals.get("wounds", {}) if hasattr(self.world, "game_criticals") else {}
            for location, rank in self.player.wounds.items():
                # Retrieve description or default
                loc_data = wound_descs.get(location, {})
                desc = loc_data.get(str(rank), f"a rank {rank} wound to the {location}")
                
                # Check for bleeding (assuming body_parts structure exists, otherwise placeholder)
                bleed_msg = ""
                if hasattr(self.player, "body_parts") and location in self.player.body_parts:
                    bleed = self.player.body_parts[location].get("bleed", 0)
                    if bleed > 0:
                        bleed_msg = f" (Bleeding {bleed}/rnd)"
                
                self.player.send_message(f"- {location.capitalize()}: {desc}{bleed_msg}")


@VerbRegistry.register(["diagnose", "diag"])
class Diagnose(BaseVerb):
    """
    DIAGNOSE [target]
    Checks wounds and bleeding status.
    """
    def execute(self):
        target = self.player
        if self.args:
            target_name = self.args[0]
            if target_name.lower() != "my":
                # Simplistic target finding for this snippet
                found = self.game.get_player_in_room(self.player.room_id, target_name)
                if not found:
                    self.player.send_message(f"You don't see {target_name} here.")
                    return
                target = found

        msg = f"Diagnosing {target.name}:\n"
        found_wounds = False

        # Assuming a structure for body parts exists on the entity
        if hasattr(target, "body_parts"):
            for part, data in target.body_parts.items():
                severity = data.get("severity", 0)
                bleed = data.get("bleed", 0)
                
                if severity > 0 or bleed > 0:
                    found_wounds = True
                    status = []
                    if severity == 1: status.append("minor")
                    elif severity == 2: status.append("moderate")
                    elif severity == 3: status.append("severe")
                    
                    if bleed > 0:
                        status.append(f"bleeding {bleed}/rnd")
                    
                    msg += f"  {part.replace('_', ' ').title()}: {', '.join(status)}\n"

        if not found_wounds:
            msg += "  No significant injuries found."

        self.player.send_message(msg)


@VerbRegistry.register(["tend"])
class Tend(BaseVerb):
    """
    TEND [MY | {character}] {area}
    Applies bandages to a bleeding wound based on First Aid skill.
    """
    def execute(self):
        if not self.args:
            self.player.send_message("Usage: TEND [MY | <player>] <location>")
            return

        # 1. Parse Arguments
        target = self.player
        location_arg = ""

        potential_target_name = self.args[0].lower()
        
        if potential_target_name == "my":
            target = self.player
            location_arg = " ".join(self.args[1:]).lower()
        else:
            # Check for other player
            found_target = self.game.get_player_in_room(self.player.room_id, potential_target_name)
            if found_target:
                target = found_target
                location_arg = " ".join(self.args[1:]).lower()
            else:
                # Assume implicit "my" if target not found (or args[0] is the location)
                target = self.player
                location_arg = " ".join(self.args).lower()

        if not location_arg:
            self.player.send_message("Which location do you want to tend?")
            return

        normalized_loc = self._normalize_location(location_arg)
        
        # 2. Validate Target State (Demeanor/Stance)
        if target != self.player:
            # Placeholder for stance check if property exists
            if hasattr(target, "stance") and target.stance == "offensive":
                self.player.send_message(f"{target.name} is too aggressive to be tended right now.")
                return

        # 3. Validate Wound
        if not hasattr(target, "body_parts") or normalized_loc not in target.body_parts:
            self.player.send_message(f"{target.name} does not have a '{location_arg}'.")
            return

        part_data = target.body_parts[normalized_loc]
        bleed_amt = part_data.get("bleed", 0)
        severity = part_data.get("severity", 0)

        if "eye" in normalized_loc:
            self.player.send_message("Eye injuries do not bleed.")
            return

        if bleed_amt <= 0:
            self.player.send_message("That area is not bleeding.")
            return

        # 4. Logic & Formulas
        difficulty = self._get_difficulty(normalized_loc)
        
        # Formula: First Aid Ranks >= ((2 * Difficulty) + (6 * Severity) - 12) * (Bleed Per Round)
        required_ranks = ((2 * difficulty) + (6 * severity) - 12) * bleed_amt
        if required_ranks < 0: required_ranks = 0

        # Get Actor's Skill (assuming get_skill_rank exists, otherwise 0)
        actor_ranks = 0
        if hasattr(self.player, "get_skill_rank"):
            actor_ranks = self.player.get_skill_rank("first_aid")
        
        # Check for Tend Lore buff (placeholder check)
        has_tend_lore = False
        if hasattr(self.player, "has_effect") and self.player.has_effect("tend_lore"):
            has_tend_lore = True
            actor_ranks += 20  # Phantom ranks

        # Success Logic
        success_type = "fail"
        if actor_ranks >= required_ranks:
            success_type = "full"
        elif actor_ranks >= (required_ranks / 2):
            success_type = "partial"
        else:
            self.player.send_message("The severity of that injury is beyond your skill to tend.")
            return

        # Roundtime Calculation
        # Base RT = (2 * Difficulty) + (6 * Severity) + (2 * Bleed Per Round) + 3
        base_rt = (2 * difficulty) + (6 * severity) + (2 * bleed_amt) + 3
        
        # Reduction by surplus ranks (1s per rank)
        rank_surplus = max(0, actor_ranks - required_ranks)
        calculated_rt = max(3, base_rt - rank_surplus)

        # Modifiers
        if has_tend_lore:
            calculated_rt = math.ceil(calculated_rt * 0.75)
        
        if hasattr(self.player, "has_effect") and self.player.has_effect("celerity"):
            calculated_rt = math.ceil(calculated_rt * 0.5)

        calculated_rt = min(60, calculated_rt)

        # Apply Output
        self.player.send_message(f"You begin to do your best to bandage {'your' if target == self.player else target.name + '''s'''} {location_arg}.")
        
        if success_type == "full":
            part_data['bleed'] = 0
            part_data['bandaged'] = True
            # Bandage duration = Ranks / 10 actions (placeholder logic for duration)
            duration = max(1, int(actor_ranks / 10))
            part_data['bandage_duration'] = duration
            
            self.player.send_message("After some effort you manage to stop the bleeding.")
            if target != self.player:
                target.send_message(f"{self.player.name} bandages your {location_arg}, stopping the bleeding.")

        elif success_type == "partial":
            old_bleed = part_data['bleed']
            new_bleed = math.ceil(old_bleed / 2)
            part_data['bleed'] = new_bleed
            
            self.player.send_message("After some effort you manage to reduce the bleeding somewhat.")
            if target != self.player:
                target.send_message(f"{self.player.name} bandages your {location_arg}, reducing the bleeding.")

        # Apply RT
        self.player.send_message(f"Roundtime: {calculated_rt} sec.")
        if hasattr(self.player, "apply_roundtime"):
            self.player.apply_roundtime(calculated_rt)
        if target != self.player and hasattr(target, "apply_roundtime"):
            target.apply_roundtime(calculated_rt)

    def _normalize_location(self, loc_str):
        mapping = {
            "right arm": "r_arm", "r arm": "r_arm",
            "left arm": "l_arm", "l arm": "l_arm",
            "right leg": "r_leg", "r leg": "r_leg",
            "left leg": "l_leg", "l leg": "l_leg",
            "right hand": "r_hand", "r hand": "r_hand",
            "left hand": "l_hand", "l hand": "l_hand",
            "right eye": "r_eye", "r eye": "r_eye",
            "left eye": "l_eye", "l eye": "l_eye",
            "chest": "chest", "abdomen": "abdomen",
            "back": "back", "head": "head", "neck": "neck"
        }
        # Try exact match or underscore replacement
        clean = loc_str.replace(" ", "_")
        return mapping.get(loc_str, clean)

    def _get_difficulty(self, loc_key):
        # 1: Back, Arms, Hands, Legs
        # 2: Head, Chest, Abdomen
        # 3: Neck
        group_2 = ["head", "chest", "abdomen"]
        group_3 = ["neck"]
        
        if loc_key in group_3: return 3
        if loc_key in group_2: return 2
        return 1