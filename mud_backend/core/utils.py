# mud_backend/core/utils.py
import math
import random
import time
import re
from typing import Dict, Any, List, Optional

def clean_name(name: str) -> str:
    """Helper to strip articles from names using regex."""
    if not name:
        return ""
    # Remove 'my', 'the', 'a', 'an' at the start of the string
    cleaned = re.sub(r'^(my|the|a|an)\s+', '', name.strip().lower())
    return cleaned.strip()

def get_stat_bonus(stat_value: int, stat_name: str, race_modifiers: Dict[str, int]) -> int:
    """
    Calculates the stat bonus based on Gemstone IV formula:
    Bonus = floor((RawStat - 50) / 2) + RaceModifier
    """
    base_bonus = math.floor((stat_value - 50) / 2)
    race_bonus = race_modifiers.get(stat_name, 0)
    return base_bonus + race_bonus

def calculate_skill_bonus(skill_rank: int) -> int:
    """
    Calculates the skill *bonus* based on the diminishing returns chart.
    - Ranks 1-10: +5 per rank
    - Ranks 11-20: +4 per rank
    - Ranks 21-30: +3 per rank
    - Ranks 31-40: +2 per rank
    - Ranks 41+: +1 per rank (bonus = rank + 100)
    """
    if skill_rank <= 0:
        return 0
    
    if skill_rank <= 10:
        return skill_rank * 5
    
    if skill_rank <= 20:
        return 50 + (skill_rank - 10) * 4
        
    if skill_rank <= 30:
        return 90 + (skill_rank - 20) * 3
        
    if skill_rank <= 40:
        return 120 + (skill_rank - 30) * 2
        
    return 140 + (skill_rank - 40) * 1

def roll_dice(num_dice, sides, modifier=0):
    total = 0
    for _ in range(num_dice):
        total += random.randint(1, sides)
    return total + modifier

# --- SEARCH HELPERS ---
def find_object_by_keyword_or_id(search_term: str, object_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Searches for an object in a list by either:
    1. Exact UUID match (if search_term starts with '#')
    2. Keyword match (name or keywords)
    """
    if not search_term:
        return None
    
    # 1. ID Lookup (Shadow Command support)
    if search_term.startswith('#'):
        target_uid = search_term[1:] # Strip the '#'
        for obj in object_list:
            if str(obj.get('uid')) == target_uid:
                return obj
        return None # If ID provided but not found, return None immediately

    # 2. Keyword/Name Lookup (Standard)
    clean_term = clean_name(search_term)
    
    # Priority 1: Exact Name Match
    for obj in object_list:
        if clean_name(obj.get("name", "")) == clean_term:
            return obj
            
    # Priority 2: Keyword Match
    for obj in object_list:
        keywords = [k.lower() for k in obj.get("keywords", [])]
        if clean_term in keywords:
            return obj
            
    # Priority 3: Partial Name Match
    for obj in object_list:
        if clean_term in clean_name(obj.get("name", "")):
            return obj

    return None

# --- ROUNDTIME HELPERS ---
def check_action_roundtime(player, action_type="other") -> bool:
    """Checks if player is in roundtime. Returns True if stuck in RT."""
    current_time = time.time()
    if getattr(player, 'roundtime', 0.0) > current_time:
        remaining = player.roundtime - current_time
        player.send_message(f"Wait {remaining:.1f} seconds.")
        return True
    return False

def set_action_roundtime(player, seconds, rt_type="soft"):
    """
    Sets player roundtime.
    rt_type: 'soft' (blue, non-blocking for some actions) or 'hard' (red, blocking).
    """
    player.roundtime = time.time() + seconds
    
    # Store metadata for the frontend
    player._rt_type = rt_type
    player._rt_duration = seconds
    
    # Trigger an update on the next tick
    if hasattr(player, "mark_dirty"):
        player.mark_dirty()