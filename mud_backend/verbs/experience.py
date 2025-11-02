# mud_backend/verbs/experience.py
from mud_backend.verbs.base_verb import BaseVerb
import math

class Experience(BaseVerb):
    """
    Handles the 'experience' (and 'exp') command.
    Displays all experience, level, and training point information.
    """
    
    def execute(self):
        player = self.player

        # --- Gather All Implemented Data ---
        level = player.level
        absorbed_exp = player.experience
        field_exp = player.unabsorbed_exp
        field_exp_cap = player.field_exp_capacity
        total_exp = player.experience
        ptps = player.ptps
        mtps = player.mtps
        stps = player.stps # We'll add this to your example's PTPs/MTPs
        mind_status = player.mind_status.capitalize() # e.g. "Clear as a bell"

        # --- Handle Level 100+ "Exp to next TP" ---
        level_label = ""
        exp_to_next = 0
        if player.level < 100:
            level_label = "Exp until lvl:"
            exp_to_next = player.level_xp_target - player.experience
        else:
            level_label = "Exp to next TP:"
            exp_to_next = player.level_xp_target - player.experience

        # --- Stub Unimplemented Data (from your example) ---
        fame = 0
        ascension_exp = 0
        recent_deaths = 0
        deaths_sting = "None"
        long_term_exp = 0
        deeds = 0
        exp_to_atp = 0
        atps = 0

        # --- Format and Send the Output ---
        # We use f-string alignment (<35) to create the two columns
        
        line1_left = f" Level: {level}"
        line1_right = f"Fame: {fame:,}"
        player.send_message(f" {line1_left:<35} {line1_right}")

        line2_left = f" Experience: {absorbed_exp:,}"
        line2_right = f"Field Exp: {field_exp:,}/{field_exp_cap:,}"
        player.send_message(f" {line2_left:<35} {line2_right}")

        line3_left = f" Ascension Exp: {ascension_exp:,}"
        line3_right = f"Recent Deaths: {recent_deaths}"
        player.send_message(f" {line3_left:<35} {line3_right}")

        line4_left = f" Total Exp: {total_exp:,}"
        line4_right = f"Death's Sting: {deaths_sting}"
        player.send_message(f" {line4_left:<35} {line4_right}")

        line5_left = f" Long-Term Exp: {long_term_exp:,}"
        line5_right = f"Deeds: {deeds}"
        player.send_message(f" {line5_left:<35} {line5_right}")
        
        line6_left = f" {level_label} {exp_to_next:,}"
        player.send_message(f" {line6_left:<35} ")

        line7_left = f" PTPs/MTPs/STPs: {ptps}/{mtps}/{stps}"
        player.send_message(f" {line7_left:<35} ")

        # Send the mind status
        player.send_message(f"\nYour mind is {mind_status}.")