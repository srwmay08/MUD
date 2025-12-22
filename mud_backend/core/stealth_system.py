# mud_backend/core/stealth_system.py
import random
from typing import Tuple
from mud_backend.core.utils import calculate_skill_bonus, get_stat_bonus

def calculate_hide_result(player, room, world) -> Tuple[bool, str, float]:
    """
    Calculates the result of a hide attempt.
    Returns: (Success (bool), Message (str), Roundtime (float))
    """
    # 2. Base Calculation
    skill_rank = player.skills.get("stalking_and_hiding", 0)
    skill_bonus = calculate_skill_bonus(skill_rank)

    # Stat Bonus: Discipline
    dis_stat = player.stats.get("DIS", 50)
    dis_bonus = get_stat_bonus(dis_stat, "DIS", player.stat_modifiers)
    
    # Racial Modifier
    race_mod = player.race_data.get("hide_bonus", 0) 
    
    # --- Observational Check ---
    observers = 0
    
    # Check Players
    room_players = world.room_players.get(room.room_id, [])
    for p_name in room_players:
        if p_name != player.name.lower():
            observers += 1
    
    # Check Monsters (exclude generic NPCs)
    for obj in room.objects:
        if obj.get("is_monster"):
            observers += 1
            
    observer_penalty = 0
    environment_bonus = 0
    
    if observers == 0:
        environment_bonus = 50 
    else:
        # Small penalty per observer to scale difficulty in crowded rooms
        observer_penalty = observers * 5

    # Total Modifier
    total_mod = skill_bonus + dis_bonus + race_mod + environment_bonus - observer_penalty
    
    # Roll d100
    roll = random.randint(1, 100)
    result = roll + total_mod
    
    # Base Difficulty
    difficulty = 100
    
    # 3. Roundtime Calculation
    rt = 10.0
    if skill_rank >= 120:
        rt -= 2.0
    elif skill_rank >= 60:
        rt -= 1.0
        
    has_celerity = False
    for buff in player.buffs.values():
        if buff.get("id") == "506" or buff.get("name") == "Celerity":
            has_celerity = True
            break
    
    if has_celerity:
        rt -= 1.0 

    rt = max(3.0, rt) 

    if result > difficulty:
        msg = ""
        if observers > 0:
            notice_roll = random.randint(1, 100)
            if notice_roll > 70:
                msg = "You see no one turn their head in your direction as you hide. "
        msg += "You slip into the shadows and are now hidden."
        return True, msg, rt
    else:
        msg = ""
        if observers > 0:
            msg = f"You see {random.choice(['someone', 'something'])} turn their head in your direction as you hide. "
        msg += "You attempt to blend with the surroundings, but don't feel very confident about your success."
        return False, msg, rt