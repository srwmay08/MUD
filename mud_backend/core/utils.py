# mud_backend/core/utils.py
import math
from typing import Dict, Any

# --- NEW: Moved from combat_system.py ---

# Base racial stat modifiers
RACE_MODIFIERS: Dict[str, Dict[str, int]] = {
    "Human": {"STR": 5, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 5, "INT": 5, "WIS": 0, "INF": 0, "ZEA": 5, "ESS": 0, "DIS": 0, "AUR": 0},
    "Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": -10, "AUR": 5},
    "Dwarf": {"STR": 10, "CON": 15, "DEX": 0, "AGI": -5, "LOG": 5, "INT": 0, "WIS": 0, "INF": -5, "ZEA": 5, "ESS": 0, "DIS": 15, "AUR": 0},
    "Dark Elf": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 5, "LOG": 0, "INT": 5, "WIS": 5, "INF": -5, "ZEA": -5, "ESS": 0, "DIS": -10, "AUR": 10},
    # --- ADDED: Sylvan, Half-Elf, Aelotoi, Gnome, Halfling, Erithian, Giantman, Half-Krolvin for Spirit/Stamina calcs ---
    "Sylvan": {"STR": 0, "CON": -5, "DEX": 10, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": -10, "AUR": 5}, # Assumed same as Elf
    "Half-Elf": {"STR": 3, "CON": -3, "DEX": 5, "AGI": 8, "LOG": 3, "INT": 3, "WIS": 0, "INF": 3, "ZEA": 3, "ESS": 0, "DIS": -5, "AUR": 3}, # Guessed
    "Aelotoi": {"STR": -5, "CON": -5, "DEX": 10, "AGI": 20, "LOG": 0, "INT": 0, "WIS": 5, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": -10, "AUR": 10}, # Guessed
    "Burghal Gnome": {"STR": -5, "CON": 5, "DEX": 5, "AGI": 5, "LOG": 10, "INT": 10, "WIS": 0, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": 5, "AUR": -5}, # Guessed
    "Halfling": {"STR": -10, "CON": 10, "DEX": 10, "AGI": 15, "LOG": 0, "INT": 0, "WIS": 0, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": -5, "AUR": 0}, # Guessed
    "Erithian": {"STR": 0, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 10, "INT": 10, "WIS": 5, "INF": 5, "ZEA": 0, "ESS": 0, "DIS": 0, "AUR": 5}, # Guessed
    "Forest Gnome": {"STR": -5, "CON": 5, "DEX": 5, "AGI": 10, "LOG": 10, "INT": 10, "WIS": 5, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": 0, "AUR": -5}, # Guessed
    "Giantman": {"STR": 20, "CON": 10, "DEX": -10, "AGI": -10, "LOG": -5, "INT": -5, "WIS": 0, "INF": -5, "ZEA": 10, "ESS": 0, "DIS": 10, "AUR": 0}, # Guessed
    "Half-Krolvin": {"STR": 15, "CON": 10, "DEX": -5, "AGI": -5, "LOG": -5, "INT": -5, "WIS": 0, "INF": -5, "ZEA": 5, "ESS": 0, "DIS": 10, "AUR": 0}, # Guessed
}

# Default modifiers if a race is not found
DEFAULT_RACE_MODS: Dict[str, int] = {
    "STR": 0, "CON": 0, "DEX": 0, "AGI": 0, "LOG": 0, "INT": 0, 
    "WIS": 0, "INF": 0, "ZEA": 0, "ESS": 0, "DIS": 0, "AUR": 0
}

def get_stat_bonus(stat_value: int, stat_name: str, race: str) -> int:
    """Calculates the stat bonus, including racial modifiers."""
    base_bonus = math.floor((stat_value - 50) / 2)
    race_mods = RACE_MODIFIERS.get(race, DEFAULT_RACE_MODS)
    race_bonus = race_mods.get(stat_name, 0)
    return base_bonus + race_bonus

# --- END NEW ---


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