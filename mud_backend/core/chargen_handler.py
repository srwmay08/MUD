# mud_backend/core/chargen_handler.py
from mud_backend.core.game_objects import Player
from mud_backend.core.db import fetch_room_data
from mud_backend import config 

# --- NEW IMPORTS ---
from mud_backend.core.room_handler import show_room_to_player
from mud_backend.core.skill_handler import show_training_menu, show_skill_list # <-- UPDATED
# ---

from mud_backend.core.stat_roller import (
    roll_stat_pool,
    assign_stats_physical,
    assign_stats_intellectual,
    assign_stats_spiritual,
    format_stats
)

# --- Helper function for "a" vs "an" ---
def get_article(word: str) -> str:
    """Returns 'an' if the word starts with a vowel, otherwise 'a'."""
    if not word:
        return "a"
    return "an" if word.lower().strip()[0] in 'aeiou' else "a"

# --- (CHARGEN_QUESTIONS list is unchanged) ---
CHARGEN_QUESTIONS = [
    {
        "key": "race",
        "prompt": "You see your reflection. What is your **Race**?\n(Options: <span class='keyword'>Human</span>, <span class='keyword'>Elf</span>, <span class='keyword'>Dwarf</span>, <span class='keyword'>Dark Elf</span>)"
    },
    {
        "key": "height",
        "prompt": "What is your **Height**?\n(Options: <span class='keyword'>shorter than average</span>, <span class='keyword'>average</span>, <span class='keyword'>taller than average</span>)"
    },
    {
        "key": "build",
        "prompt": "What is your **Body Build**?\n(Options: <span class='keyword'>slender</span>, <span class='keyword'>average</span>, <span class='keyword'>athletic</span>, <span class='keyword'>stocky</span>, <span class='keyword'>burly</span>)"
    },
    {
        "key": "age",
        "prompt": "How **Old** do you appear?\n(Options: <span class='keyword'>youthful</span>, <span class='keyword'>in your prime</span>, <span class='keyword'>middle-aged</span>, <span class='keyword'>wizened with age</span>)"
    },
    {
        "key": "eye_char",
        "prompt": "What is your **Eye Characteristic**?\n(Options: <span class='keyword'>piercing</span>, <span class='keyword'>clear</span>, <span class='keyword'>hooded</span>, <span class='keyword'>bright</span>, <span class='keyword'>deep-set</span>)"
    },
    {
        "key": "eye_color",
        "prompt": "What is your **Eye Color**?\n(Options: <span class='keyword'>blue</span>, <span class='keyword'>brown</span>, <span class='keyword'>green</span>, <span class='keyword'>hazel</span>, <span class='keyword'>violet</span>, <span class='keyword'>silver</span>)"
    },
    {
        "key": "complexion",
        "prompt": "What is your **Complexion**?\n(Options: <span class='keyword'>pale</span>, <span class='keyword'>fair</span>, <span class='keyword'>tan</span>, <span class='keyword'>dark</span>, <span class='keyword'>ashen</span>, <span class='keyword'>ruddy</span>)"
    },
    {
        "key": "hair_style",
        "prompt": "What is your **Hair Style**?\n(Options: <span class='keyword'>short</span>, <span class='keyword'>long</span>, <span class='keyword'>shoulder-length</span>, <span class='keyword'>shaved</span>, <span class='keyword'>cropped</span>)"
    },
    {
        "key": "hair_texture",
        "prompt": "What is your **Hair Texture**?\n(Options: <span class='keyword'>straight</span>, <span class='keyword'>wavy</span>, <span class='keyword'>curly</span>, <span class='keyword'>braided</span>)"
    },
    {
        "key": "hair_color",
        "prompt": "What is your **Hair Color**?\n(Options: <span class='keyword'>black</span>, <span class='keyword'>brown</span>, <span class='keyword'>blonde</span>, <span class='keyword'>red</span>, <span class='keyword'>silver</span>, <span class='keyword'>white</span>)"
    },
    {
        "key": "hair_quirk",
        "prompt": "What is your **Hair Quirk**?\n(e.g., <span class='keyword'>swept back</span>, <span class='keyword'>messy</span>, <span class='keyword'>in a ponytail</span>, <span class='keyword'>none</span>)"
    },
    {
        "key": "face",
        "prompt": "What is your **Face Shape**?\n(Options: <span class='keyword'>angular</span>, <span class='keyword'>round</span>, <span class='keyword'>square</span>, <span class='keyword'>oval</span>)"
    },
    {
        "key": "nose",
        "prompt": "What is your **Nose Shape**?\n(Options: <span class='keyword'>straight</span>, <span class='keyword'>aquiline</span>, <span class='keyword'>broad</span>, <span class='keyword'>button</span>)"
    },
    {
        "key": "mark",
        "prompt": "Any **Distinguishing Mark**?\n(e.g., <span class='keyword'>a scar over one eye</span>, <span class='keyword'>none</span>)"
    },
    {
        "key": "unique",
        "prompt": "Finally, what **Unique Feature** do you have?\n(e.g., <span class='keyword'>a silver locket</span>, <span class='keyword'>a faint aura</span>, <span class='keyword'>none</span>)"
    }
]

# ---
# (Step 1: Stat Rolling Logic is unchanged)
# ---

def do_initial_stat_roll(player: Player):
    """
    Performs the player's first stat roll, sets it as both CURRENT and BEST,
    and sends the prompt.
    """
    player.send_message("\nFirst, you must roll your 12 base stats.")
    
    new_pool = roll_stat_pool()
    player.current_stat_pool = new_pool
    player.best_stat_pool = new_pool # The first roll is always the best
    
    # Send the first prompt
    send_stat_roll_prompt(player)

def send_stat_roll_prompt(player: Player):
    """
    Sends the player their CURRENT roll and their BEST roll, with options.
    """
    # Format CURRENT roll
    sorted_current_pool = sorted(player.current_stat_pool, reverse=True)
    current_pool_str = ", ".join(map(str, sorted_current_pool))
    current_total = sum(player.current_stat_pool)
    
    player.send_message("\n--- **Your CURRENT Stat Roll** ---")
    player.send_message(f"Roll:  {current_pool_str}")
    player.send_message(f"Total: **{current_total}**")

    # Format BEST roll
    sorted_best_pool = sorted(player.best_stat_pool, reverse=True)
    best_pool_str = ", ".join(map(str, sorted_best_pool))
    best_total = sum(player.best_stat_pool)
    
    player.send_message("--- **Your BEST Stat Roll** ---")
    player.send_message(f"Pool:  {best_pool_str}")
    player.send_message(f"Total: **{best_total}**")
    
    # Show Options
    player.send_message("--- Options ---")
    player.send_message("- <span class='keyword'>REROLL</span>")
    player.send_message("- <span class='keyword'>USE THIS ROLL</span> (Selects the CURRENT roll)")
    player.send_message("- <span class='keyword'>USE BEST ROLL</span> (Selects the BEST roll)")

def _handle_stat_roll_input(player: Player, command: str):
    """Handles commands during the stat rolling step (step 1)."""
    
    if command == "reroll":
        player.send_message("> REROLL")
        
        # Roll a new pool and set it as current
        new_pool = roll_stat_pool()
        new_total = sum(new_pool)
        player.current_stat_pool = new_pool
        
        # Check if it's the new best
        best_total = sum(player.best_stat_pool)
        if new_total > best_total:
            player.send_message(f"New total: {new_total}. **This is your new BEST roll!**")
            player.best_stat_pool = new_pool
        else:
            player.send_message(f"New total: {new_total}. Your best remains {best_total}.")
        
        # Re-send the prompt
        send_stat_roll_prompt(player)
        
    elif command == "use this roll":
        player.send_message("> USE THIS ROLL")
        player.stats_to_assign = player.current_stat_pool
        player.chargen_step = 2 # Advance to assignment step
        send_assignment_prompt(player, "CURRENT")

    elif command == "use best roll":
        player.send_message("> USE BEST ROLL")
        player.stats_to_assign = player.best_stat_pool
        player.chargen_step = 2 # Advance to assignment step
        send_assignment_prompt(player, "BEST")
        
    else:
        player.send_message("That is not a valid command.")
        send_stat_roll_prompt(player)

# ---
# (Step 2: Stat Assignment Logic is unchanged)
# ---

def send_assignment_prompt(player: Player, pool_name: str):
    """
    Shows the player the pool they selected and asks how to assign it.
    """
    sorted_pool = sorted(player.stats_to_assign, reverse=True)
    pool_str = ", ".join(map(str, sorted_pool))
    
    player.send_message(f"\n--- Assigning your **{pool_name}** Roll ---")
    player.send_message(f"Pool: {pool_str}")
    player.send_message("How would you like to assign these stats?")
    player.send_message("- <span class='keyword'>ASSIGN PHYSICAL</span> (Prioritizes STR, DEX, CON, AGI)")
    player.send_message("- <span class='keyword'>ASSIGN INTELLECTUAL</span> (Prioritizes LOG, INT, WIS, INF)")
    player.send_message("- <span class='keyword'>ASSIGN SPIRITUAL</span> (Prioritizes ZEA, ESS, WIS, DIS)")

def _handle_assignment_input(player: Player, command: str):
    """Handles commands during the stat assignment step (step 2)."""

    if command == "assign physical":
        player.send_message("> ASSIGN PHYSICAL")
        player.stats = assign_stats_physical(player.stats_to_assign)
    
    elif command == "assign intellectual":
        player.send_message("> ASSIGN INTELLECTUAL")
        player.stats = assign_stats_intellectual(player.stats_to_assign)
        
    elif command == "assign spiritual":
        player.send_message("> ASSIGN SPIRITUAL")
        player.stats = assign_stats_spiritual(player.stats_to_assign)
        
    else:
        player.send_message("That is not a valid assignment command.")
        send_assignment_prompt(player, "SELECTED") # Re-show the prompt
        return # Don't advance to the next step

    # If successful, show stats and move to appearance questions
    player.send_message(format_stats(player.stats))
    player.chargen_step = 3 # Advance to appearance questions
    get_chargen_prompt(player) # Ask the first appearance question

# ---
# Step 3: Appearance Logic
# ---

def get_chargen_prompt(player: Player):
    """
    Gets the correct *appearance* question prompt based on the player's step.
    Note: Appearance questions now start at step 3.
    """
    question_index = player.chargen_step - 3 # Adjust index
    
    if 0 <= question_index < len(CHARGEN_QUESTIONS):
        question = CHARGEN_QUESTIONS[question_index]
        player.send_message("\n" + question["prompt"])
    else:
        player.send_message("An error occurred in character creation.")
        player.game_state = "playing"

def _handle_appearance_input(player: Player, text_input: str):
    """Handles answers to appearance questions (step 3+)."""
    
    question_index = player.chargen_step - 3 # Adjust index
    
    if not (0 <= question_index < len(CHARGEN_QUESTIONS)):
        # This case should ideally not be hit if logic is correct
        player.game_state = "playing"
        return

    # 1. Get the current question and save the answer
    question = CHARGEN_QUESTIONS[question_index]
    answer = text_input.strip()
    
    if answer.lower() == "none":
        answer = "" # Store 'none' as an empty string
        
    player.appearance[question["key"]] = answer
    player.send_message(f"> {answer}") # Echo the choice

    # 2. Increment step and check if chargen is done
    player.chargen_step += 1
    next_question_index = player.chargen_step - 3

    if next_question_index < len(CHARGEN_QUESTIONS):
        # 3. Ask the next question
        get_chargen_prompt(player)
    else:
        # ---
        # 4. Chargen is complete!
        # ---
        
        # Mark chargen as "finished"
        player.chargen_step = 99 
        
        # Grant LEVEL 0 TRAINING POINTS
        ptps, mtps, stps = player._calculate_tps_per_level()
        player.ptps += ptps
        player.mtps += mtps
        player.stps += stps
        player.send_message("\nYou have received your initial training points:")
        player.send_message(f" {ptps} PTPs, {mtps} MTPs, {stps} STPs")
        
        # --- CHANGED: Set game state to 'training' ---
        player.game_state = "training"
        
        player.send_message("\nCharacter creation complete! You must now train your initial skills.")
        
        # --- NEW: Automatically list all skills ---
        # --- FIX: Removed the "All Skills" title ---
        show_skill_list(player, "all")
        # --- CHANGED: Show the training menu AT THE BOTTOM ---
        show_training_menu(player)
        
# ---
# (Main Input Router is unchanged)
# ---

def handle_chargen_input(player: Player, text_input: str):
    """
    Processes the player's input during character creation.
    Routes to the correct handler based on chargen_step.
    """
    step = player.chargen_step
    command = text_input.strip().lower()

    if step == 1:
        _handle_stat_roll_input(player, command)
    elif step == 2:
        _handle_assignment_input(player, command)
    elif step > 2 and step < 99: # Only process if not yet finished
        _handle_appearance_input(player, text_input)
    else:
        # This catches input if something went wrong
        player.send_message("An error occurred. Please refresh.")
        player.game_state = "playing"


# --- (format_player_description helper function is unchanged) ---
def format_player_description(player_data: dict) -> str:
    """
    Builds the formatted description string for a player
    based on their stored appearance data.
    """
    app = player_data.get("appearance", {})

    pronoun_map = {
        "he": {"subj": "He", "obj": "him", "poss": "his"},
        "she": {"subj": "She", "obj": "her", "poss": "her"},
        "they": {"subj": "They", "obj": "them", "poss": "their"},
    }
    pr = pronoun_map.get(player_data.get("gender", "they"), pronoun_map["they"])

    desc = []

    desc.append(f"{pr['subj']} appears to be {get_article(app.get('race', 'Human'))} **{app.get('race', 'Human')}**.")
    
    line2 = f"{pr['subj']} is {app.get('height', 'average')}"
    if app.get('build'):
        line2 += f" and has {get_article(app.get('build'))} {app.get('build')} build."
    else:
        line2 += "."
    desc.append(line2)

    desc.append(f"{pr['subj']} appears to be {app.get('age', 'in their prime')}.")

    line4 = f"{pr['subj']} has {app.get('eye_char', 'clear')} {app.get('eye_color', 'brown')} eyes"
    if app.get('complexion'):
        line4 += f" and {app.get('complexion')} skin."
    else:
        line4 += "."
    desc.append(line4)

    if app.get('hair_style'):
        line5 = f"{pr['subj']} has {app.get('hair_style', '')} {app.get('hair_texture', 'straight')} {app.get('hair_color', 'brown')} hair"
        if app.get('hair_quirk'):
            line5 += f" {app.get('hair_quirk')}."
        else:
            line5 += "."
        desc.append(line5)

    face_parts = []
    if app.get('face'):
        face_parts.append(f"{get_article(app.get('face'))} {app.get('face')} face")
    if app.get('nose'):
        face_parts.append(f"{get_article(app.get('nose'))} {app.get('nose')} nose")
    if app.get('mark'):
        face_parts.append(f"{get_article(app.get('mark'))} {app.get('mark')}")
    
    if face_parts:
        desc.append(f"{pr['subj']} has " + ", ".join(face_parts) + ".")

    if app.get('unique'):
        desc.append(app.get('unique') + ".")

    return "\n".join(desc)