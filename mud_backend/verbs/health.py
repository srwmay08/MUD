# mud_backend/verbs/health.py
import math
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core.registry import VerbRegistry

def normalize_location_name(loc_str):
    """
    Converts internal location keys (lefteye, left_leg) to readable names (left eye, left leg).
    Used for display purposes (e.g. "You bandage your left leg").
    """
    loc_str = loc_str.lower().replace("_", " ")
    
    mapping = {
        "lefteye": "left eye", "l eye": "left eye", "l_eye": "left eye",
        "righteye": "right eye", "r eye": "right eye", "r_eye": "right eye",
        "leftleg": "left leg", "l leg": "left leg", "l_leg": "left leg",
        "rightleg": "right leg", "r leg": "right leg", "r_leg": "right leg",
        "leftarm": "left arm", "l arm": "left arm", "l_arm": "left arm",
        "rightarm": "right arm", "r arm": "right arm", "r_arm": "right arm",
        "lefthand": "left hand", "l hand": "left hand", "l_hand": "left hand",
        "righthand": "right hand", "r hand": "right hand", "r_hand": "right hand",
    }
    
    return mapping.get(loc_str, loc_str)

def get_json_key(loc_str):
    """
    Converts mixed keys (lefteye, left leg) to the specific Snake Case format 
    used in criticals.json (left_eye, right_leg).
    """
    clean = loc_str.lower().replace(" ", "") # collapse all spaces first
    
    mapping = {
        "lefteye": "left_eye", "leye": "left_eye",
        "righteye": "right_eye", "reye": "right_eye",
        "leftleg": "left_leg", "lleg": "left_leg",
        "rightleg": "right_leg", "rleg": "right_leg",
        "leftarm": "left_arm", "larm": "left_arm",
        "rightarm": "right_arm", "rarm": "right_arm",
        "lefthand": "left_hand", "lhand": "left_hand",
        "righthand": "right_hand", "rhand": "right_hand",
        "chest": "chest", "head": "head", "neck": "neck",
        "abdomen": "abdomen", "back": "back",
        "nervoussystem": "nervous_system"
    }
    
    # Return mapped key or fallback to original (underscored)
    return mapping.get(clean, loc_str.replace(" ", "_"))

@VerbRegistry.register(["health", "hp"]) 
class Health(BaseVerb):
    """
    Shows your current health, spirit, and stamina status.
    """
    def execute(self):
        player = self.player
        current_hp = player.hp
        max_hp = player.max_hp
        percent_hp = (current_hp / max_hp) * 100
        
        # Check for active wounds to adjust status message
        has_wounds = False
        if hasattr(player, "wounds"):
            for r in player.wounds.values():
                if r > 0: 
                    has_wounds = True
                    break

        if current_hp <= 0: 
            status = "you are dead"
        elif percent_hp > 90: 
            if has_wounds:
                status = "you seem to be in excellent shape, aside from your injuries"
            else:
                status = "you seem to be in excellent shape"
        elif percent_hp > 75: 
            status = "you are in good shape"
        elif percent_hp > 50: 
            status = "you are looking a bit rough"
        elif percent_hp > 25: 
            status = "you are badly wounded"
        elif percent_hp > 10: 
            status = "you are barely holding it together"
        else: 
            status = "you are near death"

        death_sting_msg = "None"
        if hasattr(player, "death_sting_points") and player.death_sting_points > 0:
            death_sting_msg = f"{player.death_sting_points} points (XP gain reduced)"

        con_loss_msg = "None"
        if hasattr(player, "con_lost") and player.con_lost > 0:
            pool = getattr(player, "con_recovery_pool", 0)
            con_loss_msg = f"{player.con_lost} points lost (Recovery pool: {pool:,})"
            
        self.player.send_message("--- [Health Status] ---")
        self.player.send_message(f"HP: {current_hp}/{max_hp} - {status}.")
        self.player.send_message(f"CON Loss: {con_loss_msg}")
        self.player.send_message(f"Death's Sting: {death_sting_msg}")
        
        # Display Wounds
        if hasattr(self.player, "wounds") and self.player.wounds:
            # Fetch criticals table safely
            crit_data = getattr(self.world, "game_criticals", {})
            wound_table = crit_data.get("wounds", {})
            
            # Check if any wounds actually exist
            wounds_found = False
            for location, rank in self.player.wounds.items():
                if rank > 0:
                    wounds_found = True
                    break
            
            if wounds_found:
                self.player.send_message("\n--- [Active Wounds] ---")
                
                for location, rank in self.player.wounds.items():
                    if rank > 0:
                        readable_loc = normalize_location_name(location)
                        json_key = get_json_key(location)
                        
                        # Lookup description
                        loc_data = wound_table.get(json_key, {})
                        desc = loc_data.get(str(rank), f"rank {rank} injuries to your {readable_loc}")
                        
                        # Check Bandage status
                        if hasattr(self.player, "bandages") and location in self.player.bandages:
                            self.player.send_message(f"You have {desc} and your {readable_loc} is bandaged.")
                        else:
                            self.player.send_message(f"You have {desc}.")

        # Display Scars
        if hasattr(self.player, "scars") and self.player.scars:
             crit_data = getattr(self.world, "game_criticals", {})
             scar_table = crit_data.get("scars", {})
             
             scars_found = False
             for location, rank in self.player.scars.items():
                 if rank > 0:
                     scars_found = True
                     break
             
             if scars_found:
                 self.player.send_message("\n--- [Permanent Scars] ---")
                 for location, rank in self.player.scars.items():
                     if rank > 0:
                        readable_loc = normalize_location_name(location)
                        json_key = get_json_key(location)
                        
                        loc_data = scar_table.get(json_key, {})
                        desc = loc_data.get(str(rank), f"rank {rank} scarring on your {readable_loc}")
                        
                        self.player.send_message(f"You have {desc}.")


@VerbRegistry.register(["diagnose", "diag"])
class Diagnose(BaseVerb):
    """
    DIAGNOSE [target]
    Checks wounds, bleeding status, and scars with correct grammatical person.
    """
    def execute(self):
        target = self.player
        if self.args:
            target_name = self.args[0]
            if target_name.lower() != "my":
                found = self.world.get_player_obj(target_name.lower())
                if not found:
                    self.player.send_message(f"You don't see {target_name} here.")
                    return
                if found.current_room_id != self.player.current_room_id:
                     self.player.send_message(f"You don't see {target_name} here.")
                     return
                target = found

        # Determine grammatical person variables
        if target == self.player:
            target_display = "yourself"
            subject = "You"
            verb_be = "are"
            verb_have = "have"
            possessive = "your"
        else:
            target_display = target.name
            subject = target.name
            verb_be = "is"
            verb_have = "has"
            possessive = f"{target.name}'s"

        self.player.send_message(f"With a practiced eye, you glance over {target_display}:")

        # Health Status Check
        current_hp = target.hp
        max_hp = target.max_hp
        percent_hp = (current_hp / max_hp) * 100
        
        if current_hp <= 0: status = "DEAD"
        elif percent_hp > 90: status = "in good shape"
        elif percent_hp > 75: status = "in decent shape"
        elif percent_hp > 50: status = "looking a bit rough"
        elif percent_hp > 25: status = "badly wounded"
        else: status = "in critical condition"

        self.player.send_message(f"{subject} {verb_be} {status}.")

        # Get Data Tables
        crit_data = getattr(self.world, "game_criticals", {})
        wound_table = crit_data.get("wounds", {})
        scar_table = crit_data.get("scars", {})

        # Wound Checking
        found_issues = False
        
        if hasattr(target, "wounds") and target.wounds:
            for location, rank in target.wounds.items():
                if rank > 0:
                    found_issues = True
                    readable_loc = normalize_location_name(location)
                    json_key = get_json_key(location)
                    
                    # 1. Determine the Description from Table
                    loc_data = wound_table.get(json_key, {})
                    raw_desc = loc_data.get(str(rank))
                    
                    if raw_desc:
                        # Fix possessive in description: "cuts on your chest" -> "cuts on Sevax's chest"
                        wound_text = raw_desc.replace("your", possessive)
                    else:
                        # Fallback if no description found
                        wound_text = f"rank {rank} injuries to {possessive} {readable_loc}"

                    # 2. Check Bandages
                    is_bandaged = hasattr(target, "bandages") and location in target.bandages
                    
                    # 3. Construct the Message
                    if is_bandaged:
                        self.player.send_message(f"{subject} {verb_have} {wound_text} and {possessive} {readable_loc} is bandaged.")
                    else:
                        self.player.send_message(f"{subject} {verb_have} {wound_text}.")

        # Scar Checking
        if hasattr(target, "scars") and target.scars:
             for location, rank in target.scars.items():
                 if rank > 0:
                     found_issues = True
                     readable_loc = normalize_location_name(location)
                     json_key = get_json_key(location)
                     
                     loc_data = scar_table.get(json_key, {})
                     raw_desc = loc_data.get(str(rank))
                     
                     if raw_desc:
                         scar_text = raw_desc.replace("your", possessive)
                     else:
                         scar_text = f"rank {rank} scarring on {possessive} {readable_loc}"
                         
                     self.player.send_message(f"{subject} {verb_have} {scar_text}.")

        if not found_issues:
            self.player.send_message(f"{subject} {verb_have} no visible wounds or scars.")


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
            found_target = self.world.get_player_obj(potential_target_name)
            if found_target and found_target.current_room_id == self.player.current_room_id:
                target = found_target
                location_arg = " ".join(self.args[1:]).lower()
            else:
                # Assume implicit "my" if target not found (or args[0] is the location)
                target = self.player
                location_arg = " ".join(self.args).lower()

        if not location_arg:
            self.player.send_message("Which location do you want to tend?")
            return

        # Improved Lookup Logic
        # Try to find the exact wound key from the user input
        matched_wound_key = self._find_wound_key(target, location_arg)

        target_display = "You" if target == self.player else target.name
        
        # 2. Validate Target State (Demeanor/Stance)
        if target != self.player:
            if hasattr(target, "stance") and target.stance == "offensive":
                self.player.send_message(f"{target.name} is too aggressive to be tended right now.")
                return

        # 3. Validate Wound Existence
        if not matched_wound_key:
            if target == self.player:
                self.player.send_message(f"You do not have a wounded '{location_arg}'.")
            else:
                self.player.send_message(f"{target.name} does not have a wounded '{location_arg}'.")
            return

        # Use the key we found
        normalized_loc_key = matched_wound_key
        readable_loc = normalize_location_name(normalized_loc_key)
        rank = target.wounds[normalized_loc_key]
        
        # 4. Check if already bandaged
        if hasattr(target, "bandages") and normalized_loc_key in target.bandages:
             self.player.send_message("That area is already bandaged.")
             return

        # Eye injuries do not bleed (Per Prompt)
        if "eye" in readable_loc:
            self.player.send_message("Eye injuries do not bleed.")
            return

        # 5. Logic & Formulas
        bleed_amt = rank 
        severity = rank
        difficulty = self._get_difficulty(normalized_loc_key)
        
        # Formula: First Aid Ranks >= ((2 * Difficulty) + (6 * Severity) - 12) * (Bleed Per Round)
        required_ranks = ((2 * difficulty) + (6 * severity) - 12) * bleed_amt
        if required_ranks < 0: required_ranks = 0

        # Get Actor's Skill
        actor_ranks = 0
        if hasattr(self.player, "skills"):
            actor_ranks = self.player.skills.get("first_aid", 0)
        
        # Tend Lore Buff
        has_tend_lore = False
        if hasattr(self.player, "status_effects") and "tend_lore" in self.player.status_effects:
            has_tend_lore = True
            actor_ranks += 20 

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
        base_rt = (2 * difficulty) + (6 * severity) + (2 * bleed_amt) + 3
        rank_surplus = max(0, actor_ranks - required_ranks)
        calculated_rt = max(3, base_rt - rank_surplus)

        # Modifiers
        if has_tend_lore:
            calculated_rt = math.ceil(calculated_rt * 0.75)
        
        if hasattr(self.player, "status_effects") and "celerity" in self.player.status_effects:
            calculated_rt = math.ceil(calculated_rt * 0.5)

        calculated_rt = min(60, calculated_rt)

        # Apply Output
        possessive = "your" if target == self.player else f"{target.name}'s"
        self.player.send_message(f"You begin to do your best to bandage {possessive} {readable_loc}.")
        
        if success_type == "full":
            if not hasattr(target, "bandages"): target.bandages = {}
            
            # Duration: Ranks / 10 actions (Min 1)
            duration = max(1, int(actor_ranks / 10))
            
            target.bandages[normalized_loc_key] = {
                "duration": duration,
                "stopper": self.player.name
            }
            
            self.player.send_message("After some effort you manage to stop the bleeding.")
            if target != self.player:
                target.send_message(f"{self.player.name} bandages your {readable_loc}, stopping the bleeding.")

        elif success_type == "partial":
            self.player.send_message("After some effort you manage to reduce the bleeding somewhat.")
            if target != self.player:
                target.send_message(f"{self.player.name} bandages your {readable_loc}, reducing the bleeding.")

        # Apply RT
        self.player.send_message(f"Roundtime: {calculated_rt} sec.")
        
        if hasattr(self.player, "next_action_time"):
            import time
            self.player.next_action_time = time.time() + calculated_rt
            
        if target != self.player and hasattr(target, "next_action_time"):
            import time
            target.next_action_time = time.time() + calculated_rt

        target.mark_dirty()

    def _find_wound_key(self, target, input_arg):
        """
        Robustly finds a matching wound key in target.wounds based on user input.
        Handles: "lefteye" -> "left_eye", "left eye", "l_eye" matches.
        """
        if not hasattr(target, "wounds") or not target.wounds:
            return None

        # 1. Direct match
        if input_arg in target.wounds:
            return input_arg

        # 2. Normalized match (using local normalize)
        normalized = self._normalize_location(input_arg)
        if normalized in target.wounds:
            return normalized

        # 3. Fuzzy / Readable match
        clean_input = input_arg.lower().replace(" ", "")
        
        for key in target.wounds:
            readable = normalize_location_name(key) # e.g. "left eye"
            clean_readable = readable.replace(" ", "") # "lefteye"
            
            if clean_readable == clean_input:
                return key
            
            # Also check if the raw key matches the input (e.g. "l_eye" vs "lefteye")
            clean_key = key.lower().replace("_", "").replace(" ", "")
            if clean_key == clean_input:
                return key

        return None

    def _normalize_location(self, loc_str):
        # Maps input strings to internal keys (Helper for specific overrides)
        mapping = {
            "right arm": "r_arm", "r arm": "r_arm", "rightarm": "r_arm",
            "left arm": "l_arm", "l arm": "l_arm", "leftarm": "l_arm",
            "right leg": "r_leg", "r leg": "r_leg", "rightleg": "r_leg",
            "left leg": "l_leg", "l leg": "l_leg", "leftleg": "l_leg",
            "right hand": "r_hand", "r hand": "r_hand", "righthand": "r_hand",
            "left hand": "l_hand", "l hand": "l_hand", "lefthand": "l_hand",
            "right eye": "r_eye", "r eye": "r_eye", "righteye": "r_eye",
            "left eye": "l_eye", "l eye": "l_eye", "lefteye": "l_eye",
            "chest": "chest", "abdomen": "abdomen",
            "back": "back", "head": "head", "neck": "neck"
        }
        clean = loc_str.replace(" ", "_")
        return mapping.get(loc_str, clean)

    def _get_difficulty(self, loc_key):
        # 1: Back, Arms, Hands, Legs
        # 2: Head, Chest, Abdomen
        # 3: Neck
        group_2 = ["head", "chest", "abdomen"]
        group_3 = ["neck"]
        
        # Normalize key for difficulty check just in case
        check_key = loc_key.replace("lefteye", "head").replace("righteye", "head") 
        
        if loc_key in group_3: return 3
        if loc_key in group_2: return 2
        return 1