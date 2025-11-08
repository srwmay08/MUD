# mud_backend/core/utils.py
import math

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
        # Ranks 1-10: +5 bonus per rank
        return skill_rank * 5
    
    if skill_rank <= 20:
        # 50 from first 10 ranks, +4 for ranks 11-20
        return 50 + (skill_rank - 10) * 4
        
    if skill_rank <= 30:
        # 90 from first 20 ranks (50 + 40), +3 for ranks 21-30
        return 90 + (skill_rank - 20) * 3
        
    if skill_rank <= 40:
        # 120 from first 30 ranks (90 + 30), +2 for ranks 31-40
        return 120 + (skill_rank - 30) * 2
        
    # Ranks 41+
    # 140 from first 40 ranks (120 + 20), +1 for ranks 41+
    # This simplifies to the user's provided formula: rank + 100
    return 140 + (skill_rank - 40) * 1