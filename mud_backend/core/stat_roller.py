# mud_backend/core/stat_roller.py
import random
from typing import List, Dict

# Define the 12 stat roll ranges as (min, max) tuples
STAT_ROLL_RANGES = [
    (30, 90),  # 1 roll
    (70, 90),  # 3 rolls
    (70, 90),
    (70, 90),
    (60, 80),  # 3 rolls
    (60, 80),
    (60, 80),
    (50, 80),  # 2 rolls
    (50, 80),
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

def _assign_stats_by_priority(pool: List[int], priority_list: List[str], stats_to_fill: List[str]) -> Dict[str, int]:
    """
    Helper function to assign stats based on a priority list.
    THIS IS THE MODIFIED FUNCTION.
    It now only assigns stats that are in the 'stats_to_fill' list,
    using the values from the provided 'pool' list.
    """
    
    # Sort the rolled pool, highest to lowest
    sorted_pool = sorted(pool, reverse=True)
    
    new_assignments = {}
    
    # 1. Create a mutable copy of the stats to fill
    remaining_stats_to_fill = list(stats_to_fill)

    # 2. Priority Pass: Assign stats that are in both the
    #    priority list AND the list of stats we need to fill.
    for stat_name in priority_list:
        if stat_name in remaining_stats_to_fill:
            if not sorted_pool: break # Stop if we run out of pool values
            new_assignments[stat_name] = sorted_pool.pop(0)
            remaining_stats_to_fill.remove(stat_name)
            
    # 3. Remaining Pass: Assign the rest of the pool to the
    #    rest of the stats (alphabetically).
    remaining_stats_to_fill.sort()
    for stat_name in remaining_stats_to_fill:
        if not sorted_pool: break # Stop if we run out of pool values
        new_assignments[stat_name] = sorted_pool.pop(0)
        
    return new_assignments

def assign_stats_physical(pool: List[int], stats_to_fill: List[str]) -> Dict[str, int]:
    """Assigns the pool with priority given to Physical stats."""
    return _assign_stats_by_priority(pool, PHYSICAL_PRIORITY, stats_to_fill)

def assign_stats_intellectual(pool: List[int], stats_to_fill: List[str]) -> Dict[str, int]:
    """Assigns the pool with priority given to Intellectual stats."""
    return _assign_stats_by_priority(pool, INTELLECTUAL_PRIORITY, stats_to_fill)

def assign_stats_spiritual(pool: List[int], stats_to_fill: List[str]) -> Dict[str, int]:
    """Assigns the pool with priority given to Spiritual stats."""
    return _assign_stats_by_priority(pool, SPIRITUAL_PRIORITY, stats_to_fill)

def format_stats(stats_dict: Dict[str, int]) -> str:
    """Creates a formatted string to display all 12 stats."""
    if not stats_dict:
        return "Stats have not been assigned yet."
    
    # --- MODIFIED: Show '---' if not assigned ---
    def get_stat(s):
        val = stats_dict.get(s)
        return f"{val:<3}" if val is not None else "---"

    lines = [
        "**Your Assigned Stats:**",
        "--- Physical ---",
        f"STR: {get_stat('STR')} CON: {get_stat('CON')} DEX: {get_stat('DEX')} AGI: {get_stat('AGI')}",
        "--- Mental ---",
        f"LOG: {get_stat('LOG')} INT: {get_stat('INT')} WIS: {get_stat('WIS')} INF: {get_stat('INF')}",
        "--- Spiritual ---",
        f"ZEA: {get_stat('ZEA')} ESS: {get_stat('ESS')}",
        "--- Hybrid ---",
        f"DIS: {get_stat('DIS')} AUR: {get_stat('AUR')}"
    ]
    # --- END MODIFIED ---
    return "\n".join(lines)