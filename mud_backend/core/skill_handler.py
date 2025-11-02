# mud_backend/core/skill_handler.py
import math
from typing import Dict, List, Optional
from mud_backend.core.game_objects import Player
from mud_backend.core import game_state

# ---
# Skill Cost Calculation Logic
# ---

def _calculate_final_cost(base_cost: int, player_stats: Dict[str, int], key_attrs: List[str]) -> int:
    """
    Calculates the final, discounted cost for one TP type (PTP, MTP, or STP).
    """
    if base_cost == 0:
        return 0
        
    attr1_val = 0
    attr2_val = 0

    # 1. Get Effective Stats
    if len(key_attrs) == 1:
        attr1_val = player_stats.get(key_attrs[0], 0)
        attr1_val = max(70, attr1_val)
        avg_stat = float(attr1_val)
    elif len(key_attrs) >= 2:
        attr1_val = player_stats.get(key_attrs[0], 0)
        attr2_val = player_stats.get(key_attrs[1], 0)
        attr1_val = max(70, attr1_val)
        attr2_val = max(70, attr2_val)
        # 2. Get Average
        avg_stat = (attr1_val + attr2_val) / 2.0
    else:
        # No key attributes, return base cost
        return base_cost

    # 3. Clamp Average
    clamped_stat = min(avg_stat, 100.0)
    
    # 4. Find Discount Progress
    discount_progress = clamped_stat - 70.0
    
    # 5. Find Discount Percent
    discount_percent = discount_progress / 30.0
    
    # 6. Find Max Discount
    min_cost = math.ceil(base_cost / 2.0)
    max_discount_amount = base_cost - min_cost
    
    # 7. Calculate Final Cost
    final_cost = round(base_cost - (max_discount_amount * discount_percent))
    
    return int(final_cost)

def get_skill_costs(player: Player, skill_data: Dict) -> Dict[str, int]:
    """
    Gets the final PTP, MTP, and STP costs for a skill for a specific player.
    """
    player_stats = player.stats
    base_costs = skill_data.get("base_cost", {})
    key_attrs = skill_data.get("key_attributes", {})
    
    final_ptp = _calculate_final_cost(
        base_costs.get("ptp", 0),
        player_stats,
        key_attrs.get("ptp", [])
    )
    final_mtp = _calculate_final_cost(
        base_costs.get("mtp", 0),
        player_stats,
        key_attrs.get("mtp", [])
    )
    final_stp = _calculate_final_cost(
        base_costs.get("stp", 0),
        player_stats,
        key_attrs.get("stp", [])
    )
    
    return {"ptp": final_ptp, "mtp": final_mtp, "stp": final_stp}

def _find_skill_by_name(skill_name: str) -> Optional[Dict]:
    """Finds a skill in the global state by its name or keywords."""
    skill_name_lower = skill_name.lower()
    for skill_id, skill_data in game_state.GAME_SKILLS.items():
        if skill_name_lower == skill_data.get("name", "").lower():
            return skill_data
        if skill_name_lower in skill_data.get("keywords", []):
            return skill_data
    return None

# ---
# Training Menu / "GUI" Logic
# ---

def show_training_menu(player: Player):
    """
    Displays the main training menu and TP totals to the player.
    """
    player.send_message("\n--- **Skill Training** ---")
    player.send_message(f" <span class='keyword'>Physical TPs: {player.ptps}</span>")
    player.send_message(f" <span class='keyword'>Mental TPs:   {player.mtps}</span>")
    player.send_message(f" <span class='keyword'>Spiritual TPs: {player.stps}</span>")
    player.send_message("---")
    player.send_message("Type '<span class='keyword'>LIST &lt;category&gt;</span>' (e.g., LIST ARMOR, LIST WEAPON, LIST ALL)")
    player.send_message("Type '<span class='keyword'>TRAIN &lt;skill&gt; &lt;ranks&gt;</span>' (e.g., TRAIN BRAWLING 1)")
    player.send_message("Type '<span class='keyword'>DONE</span>' to finish training.")

def show_skill_list(player: Player, category: str):
    """
    Lists all skills, filtered by category, showing ranks and costs.
    """
    category_lower = category.lower()
    found_skills = False
    
    # Get all categories
    all_categories = sorted(list(set(s.get("category", "Uncategorized") for s in game_state.GAME_SKILLS.values())))
    
    if category_lower == "all":
        player.send_message("--- **All Skill Categories** ---")
        for cat in all_categories:
            player.send_message(f"- {cat}")
        player.send_message("Type 'LIST <Category Name>' to see skills.")
        return
        
    if category_lower == "categories":
        player.send_message("--- **Skill Categories** ---")
        for cat in all_categories:
            player.send_message(f"- <span class='keyword' data-name='list {cat}' data-verbs='list'>{cat}</span>")
        return

    player.send_message(f"--- **{category.upper()}** ---")
    
    # Sort skills by name
    sorted_skills = sorted(game_state.GAME_SKILLS.values(), key=lambda s: s.get("name", "zzz"))
    
    for skill_data in sorted_skills:
        skill_cat = skill_data.get("category", "Uncategorized").lower()
        if category_lower != skill_cat.lower():
            continue
            
        found_skills = True
        skill_id = skill_data["skill_id"]
        skill_name = skill_data["name"]
        current_rank = player.skills.get(skill_id, 0)
        
        # Get final calculated costs
        costs = get_skill_costs(player, skill_data)
        
        cost_str = f"Cost: {costs['ptp']}p / {costs['mtp']}m / {costs['stp']}s"
        
        player.send_message(
            f"- <span class='keyword' data-name='train {skill_name} 1' data-verbs='train'>{skill_name:<24}</span> "
            f"(Rank: {current_rank:<3}) "
            f"[{cost_str}]"
        )
        
    if not found_skills:
        player.send_message(f"No skills found for category '{category}'.")
        player.send_message("Type '<span class='keyword'>LIST CATEGORIES</span>' to see all categories.")

def train_skill(player: Player, skill_name: str, ranks_to_train: int):
    """
    Attempts to train a skill a number of times, spending TPs.
    """
    if ranks_to_train <= 0:
        player.send_message("You must train at least 1 rank.")
        return
        
    skill_data = _find_skill_by_name(skill_name)
    if not skill_data:
        player.send_message(f"Unknown skill: '{skill_name}'.")
        return
        
    skill_id = skill_data["skill_id"]
    
    # 1. Get cost for *one* rank
    costs = get_skill_costs(player, skill_data)
    
    # 2. Calculate total cost
    total_ptp = costs["ptp"] * ranks_to_train
    total_mtp = costs["mtp"] * ranks_to_train
    total_stp = costs["stp"] * ranks_to_train
    
    # 3. Check if player can afford it
    if player.ptps < total_ptp:
        player.send_message(f"You need {total_ptp} PTPs but only have {player.ptps}.")
        return
    if player.mtps < total_mtp:
        player.send_message(f"You need {total_mtp} MTPs but only have {player.mtps}.")
        return
    if player.stps < total_stp:
        player.send_message(f"You need {total_stp} STPs but only have {player.stps}.")
        return
        
    # 4. Apply costs and add skill
    player.ptps -= total_ptp
    player.mtps -= total_mtp
    player.stps -= total_stp
    
    new_rank = player.skills.get(skill_id, 0) + ranks_to_train
    player.skills[skill_id] = new_rank
    
    player.send_message(f"You train **{skill_data['name']}** to rank **{new_rank}**!")
    
    # 5. Show the main menu again with updated TP totals
    show_training_menu(player)