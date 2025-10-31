# mud_backend/core/stat_roller.py
import random
from typing import List, Dict

# Define the 12 stat roll ranges as (min, max) tuples
STAT_ROLL_RANGES = [
    (30, 90),  # 1 roll
    (70, 90),  # 3 rolls
    (70, 90),
    (70, 90),
    (60, 80),  # 5 rolls
    (60, 80),
    (60, 80),
    (60, 80),
    (60, 80),
    (40, 75),  # 2 rolls
    (40, 75),
    (40, 80)   # 1 roll
]

# Define the master list of all 12 stats
STAT_LIST = [
    "STR", "CON", "DEX", "AGI", 
    "LOG", "INT", "WIS", "INF",
    "ZEA", "ESS", "DIS", "AUR"
]

# Define the priority lists for auto-assignment
PHYSICAL_PRIORITY = ["STR", "DEX", "CON", "AGI"]
INTELLECTUAL_PRIORITY = ["LOG", "INT", "WIS", "INF"]
SPIRITUAL_PRIORITY = ["ZEA", "ESS", "WIS", "DIS"] # Based on your description

def roll_stat_pool() -> List[int]:
    """Rolls a new 12-point stat pool based on the defined ranges."""
    pool = []
    for min_val, max_val in STAT_ROLL_RANGES:
        pool.append(random.randint(min_val, max_val))
    return pool

def _assign_stats_by_priority(pool: List[int], priority_list: List[str]) -> Dict[str, int]:
    """Helper function to assign stats based on a priority list."""
    
    # Sort the rolled pool, highest to lowest
    sorted_pool = sorted(pool, reverse=True)
    
    stats = {}
    
    # 1. Assign the 4 priority stats
    for i, stat_name in enumerate(priority_list):
        stats[stat_name] = sorted_pool[i]
        
    # 2. Get the remaining stats and remaining pool values
    remaining_stats = [s for s in STAT_LIST if s not in stats]
    remaining_pool = sorted_pool[4:] # Get all values from the 5th onwards
    
    # 3. Assign the remaining 8 stats
    # We'll assign them alphabetically for predictability
    remaining_stats.sort()
    for i, stat_name in enumerate(remaining_stats):
        stats[stat_name] = remaining_pool[i]
        
    return stats

def assign_stats_physical(pool: List[int]) -> Dict[str, int]:
    """Assigns the pool with priority given to Physical stats."""
    return _assign_stats_by_priority(pool, PHYSICAL_PRIORITY)

def assign_stats_intellectual(pool: List[int]) -> Dict[str, int]:
    """Assigns the pool with priority given to Intellectual stats."""
    return _assign_stats_by_priority(pool, INTELLECTUAL_PRIORITY)

def assign_stats_spiritual(pool: List[int]) -> Dict[str, int]:
    """Assigns the pool with priority given to Spiritual stats."""
    return _assign_stats_by_priority(pool, SPIRITUAL_PRIORITY)

def format_stats(stats_dict: Dict[str, int]) -> str:
    """Creates a formatted string to display all 12 stats."""
    if not stats_dict:
        return "Stats have not been assigned yet."
    
    lines = [
        "**Your Assigned Stats:**",
        "--- Physical ---",
        f"STR: {stats_dict.get('STR', 0):<3} CON: {stats_dict.get('CON', 0):<3} DEX: {stats_dict.get('DEX', 0):<3} AGI: {stats_dict.get('AGI', 0):<3}",
        "--- Mental ---",
        f"LOG: {stats_dict.get('LOG', 0):<3} INT: {stats_dict.get('INT', 0):<3} WIS: {stats_dict.get('WIS', 0):<3} INF: {stats_dict.get('INF', 0):<3}",
        "--- Spiritual ---",
        f"ZEA: {stats_dict.get('ZEA', 0):<3} ESS: {stats_dict.get('ESS', 0):<3}",
        "--- Hybrid ---",
        f"DIS: {stats_dict.get('DIS', 0):<3} AUR: {stats_dict.get('AUR', 0):<3}"
    ]
    return "\n".join(lines)