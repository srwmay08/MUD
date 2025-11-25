# mud_backend/core/utils.py
import math
from typing import Dict, Any

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