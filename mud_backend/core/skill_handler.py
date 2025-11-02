# mud_backend/core/skill_handler.py
import math
from typing import Dict, List, Optional
from mud_backend.core.game_objects import Player
from mud_backend.core import game_state

# ---
# Skill Cost Calculation Logic
# ---

# (This function is unchanged)
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

# (This function is unchanged)
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

# (This function is unchanged)
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
    player.send_message(f" <span class='keyword' data-command='list physical tps'>Physical TPs: {player.ptps}</span>")
    player.send_message(f" <span class='keyword' data-command='list mental tps'>Mental TPs:   {player.mtps}</span>")
    player.send_message(f" <span class='keyword' data-command='list spiritual tps'>Spiritual TPs: {player.stps}</span>")
    player.send_message("---")
    player.send_message("Type '<span class='keyword' data-command='list all'>LIST ALL</span>' to see all skills.")
    player.send_message("Type '<span class='keyword' data-command='list categories'>LIST CATEGORIES</span>' to see skill groups.")
    player.send_message("Type '<span class='keyword'>TRAIN &lt;skill&gt; &lt;ranks&gt;</span>' (e.g., TRAIN BRAWLING 1)")
    player.send_message("Type '<span class='keyword' data-command='done'>DONE</span>' to finish training.")


def _format_skill_line(player: Player, skill_data: Dict) -> str:
    """
    Formats a single skill line as a <tr> for the HTML table.
    """
    skill_id = skill_data["skill_id"]
    skill_name = skill_data["name"]
    current_rank = player.skills.get(skill_id, 0)
    
    ranks_trained_this_lvl = player.ranks_trained_this_level.get(skill_id, 0)
    
    # Use <td> for table cells
    rank_str = f"<td>(Rank: {current_rank:<3})</td>"
    cost_str = ""
    skill_name_str = ""

    if ranks_trained_this_lvl >= 3:
        cost_str = "<td>[Maxed for level]</td>"
        skill_name_str = f"<td>- {skill_name}</td>"
    else:
        costs = get_skill_costs(player, skill_data)
        multiplier = ranks_trained_this_lvl + 1
        cost_str = (
            f"<td>[Cost: {costs['ptp'] * multiplier}p / "
            f"{costs['mtp'] * multiplier}m / "
            f"{costs['stp'] * multiplier}s]</td>"
        )
        # --- UPDATED: Use data-command for direct clicking ---
        skill_name_str = (
            f"<td>- <span class='keyword' data-command='train {skill_name} 1'>"
            f"{skill_name}</span></td>"
        )
        # ---
    
    # Return as a table row
    return f"<tr>{skill_name_str}{rank_str}{cost_str}</tr>"


def _show_all_skills_by_category(player: Player):
    """
    Internal helper to list all skills, grouped by category, in two columns.
    """
    # Your custom category order
    COLUMN_1_CATEGORIES = [
        "Armor Skills", "Weapon Skills", "Combat Skills", 
        "Defensive Skills", "Physical Skills"
    ]
    COLUMN_2_CATEGORIES = [
        "General Skills", "Subterfuge Skills", "Magical Skills", 
        "Lore Skills", "Mental Skills", "Spiritual Skills"
    ]
    
    all_skills = sorted(game_state.GAME_SKILLS.values(), key=lambda s: s.get("name", "zzz"))
    
    # --- Build Column 1 Lines (as HTML table rows) ---
    column_1_lines = []
    for category in COLUMN_1_CATEGORIES:
        if column_1_lines:
            column_1_lines.append("<tr><td>&nbsp;</td></tr>") # Spacer row
            
        column_1_lines.append(f"<tr><td colspan='3'>--- **{category.upper()}** ---</td></tr>")
        
        for skill_data in all_skills:
            if skill_data.get("category", "Uncategorized") == category:
                column_1_lines.append(_format_skill_line(player, skill_data))

    # --- Build Column 2 Lines (as HTML table rows) ---
    column_2_lines = []
    for category in COLUMN_2_CATEGORIES:
        if column_2_lines:
            column_2_lines.append("<tr><td>&nbsp;</td></tr>") # Spacer row
            
        column_2_lines.append(f"<tr><td colspan='3'>--- **{category.upper()}** ---</td></tr>")
        
        for skill_data in all_skills:
            if skill_data.get("category", "Uncategorized") == category:
                column_2_lines.append(_format_skill_line(player, skill_data))

    # --- Print the two columns side-by-side using a table ---
    
    # Set a width for the left column's table
    COL_1_WIDTH = "60%"
    
    # Start the table
    player.send_message("<table style='width:100%; border-spacing: 0;'>")
    player.send_message("  <tr style='vertical-align: top;'>") # Align columns to the top
    player.send_message(f"    <td style='width:{COL_1_WIDTH};'>")
    
    # --- Print Column 1 ---
    player.send_message("      <table style='width:100%;'>")
    for line in column_1_lines:
        player.send_message(f"        {line}")
    player.send_message("      </table>")
    
    player.send_message("    </td>")
    player.send_message("    <td>")
    
    # --- Print Column 2 ---
    player.send_message("      <table style='width:100%;'>")
    for line in column_2_lines:
        player.send_message(f"        {line}")
    player.send_message("      </table>")
    
    player.send_message("    </td>")
    player.send_message("  </tr>")
    player.send_message("</table>")


def show_skill_list(player: Player, category: str):
    """
    Lists all skills, filtered by category, showing ranks and costs.
    """
    category_lower = category.lower()
    
    all_categories = sorted(list(set(s.get("category", "Uncategorized") for s in game_state.GAME_SKILLS.values())))
    
    if category_lower == "all":
        _show_all_skills_by_category(player)
        return
        
    if category_lower == "categories":
        player.send_message("--- **Skill Categories** ---")
        for cat in all_categories:
            player.send_message(f"- <span class='keyword' data-command='list {cat}'>{cat}</span>")
        return

    if category.lower() not in [cat.lower() for cat in all_categories]:
        player.send_message(f"No skills found for category '{category}'.")
        player.send_message("Type '<span class='keyword' data-command='list categories'>LIST CATEGORIES</span>' to see all categories.")
        return
        
    player.send_message(f"--- **{category.upper()}** ---")
    
    sorted_skills = sorted(game_state.GAME_SKILLS.values(), key=lambda s: s.get("name", "zzz"))
    
    # Use a simple table for single-column lists too
    player.send_message("<table>")
    for skill_data in sorted_skills:
        skill_cat = skill_data.get("category", "Uncategorized").lower()
        if category_lower != skill_cat.lower():
            continue
        
        player.send_message(_format_skill_line(player, skill_data))
    player.send_message("</table>")


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
    
    ranks_already_trained = player.ranks_trained_this_level.get(skill_id, 0)
    
    if ranks_already_trained >= 3:
        player.send_message(f"You have already trained **{skill_data['name']}** 3 times this level.")
        return
        
    if ranks_already_trained + ranks_to_train > 3:
        player.send_message(f"You can only train {3 - ranks_already_trained} more rank(s) in **{skill_data['name']}** this level.")
        return
    
    costs = get_skill_costs(player, skill_data)
    
    total_ptp = 0
    total_mtp = 0
    total_stp = 0
    
    for i in range(ranks_to_train):
        multiplier = (ranks_already_trained + 1) + i
        
        total_ptp += costs["ptp"] * multiplier
        total_mtp += costs["mtp"] * multiplier
        total_stp += costs["stp"] * multiplier
    
    if player.ptps < total_ptp:
        player.send_message(f"You need {total_ptp} PTPs but only have {player.ptps}.")
        return
    if player.mtps < total_mtp:
        player.send_message(f"You need {total_mtp} MTPs but only have {player.mtps}.")
        return
    if player.stps < total_stp:
        player.send_message(f"You need {total_stp} STPs but only have {player.stps}.")
        return
        
    player.ptps -= total_ptp
    player.mtps -= total_mtp
    player.stps -= total_stp
    
    new_rank = player.skills.get(skill_id, 0) + ranks_to_train
    player.skills[skill_id] = new_rank
    
    player.ranks_trained_this_level[skill_id] = ranks_already_trained + ranks_to_train
    
    player.send_message(f"You train **{skill_data['name']}** to rank **{new_rank}**!")
    
    # --- UPDATED: Show menu AND list ---
    show_training_menu(player)
    player.send_message("\n--- **All Skills** ---")
    _show_all_skills_by_category(player)
    # ---