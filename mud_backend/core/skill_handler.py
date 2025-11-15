# mud_backend/core/skill_handler.py
import math
import random # <-- NEW IMPORT
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from mud_backend.core.game_objects import Player
# --- REMOVED: from mud_backend.core import game_state ---
# --- NEW: Import get_stat_bonus ---
from mud_backend.core.utils import get_stat_bonus
# --- END NEW ---

# --- NEW: Type hint for World ---
if TYPE_CHECKING:
    from mud_backend.core.game_state import World

# ---
# --- FUNCTION REMOVED (MOVED TO utils.py) ---
# ---

# ---
# Skill Cost Calculation Logic (UNCHANGED)
# ---
def _calculate_final_cost(base_cost: int, player_stats: Dict[str, int], key_attrs: List[str]) -> int:
    """
    Calculates the final, discounted cost for one TP type (PTP, MTP, or STP).
    """
    # ... (function contents unchanged) ...
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

# ... (rest of skill_handler.py is unchanged) ...
def get_skill_costs(player: Player, skill_data: Dict) -> Dict[str, int]:
# ... (function contents unchanged) ...
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

# --- REFACTORED: Accept world object ---
def _find_skill_by_name(world: 'World', skill_name: str) -> Optional[Dict]:
# ... (function contents unchanged) ...
    skill_name_lower = skill_name.lower()
    # --- FIX: Use world.game_skills ---
    for skill_id, skill_data in world.game_skills.items():
        if skill_name_lower == skill_data.get("name", "").lower():
            return skill_data
        if skill_name_lower in skill_data.get("keywords", []):
            return skill_data
    return None

# ... (inside skill_handler.py)

def _format_skill_line(player: Player, skill_data: Dict) -> str:
# ... (function contents unchanged) ...
    skill_id = skill_data["skill_id"]
    skill_name = skill_data["name"]
    current_rank = player.skills.get(skill_id, 0)
    
    ranks_trained_this_lvl = player.ranks_trained_this_level.get(skill_id, 0)
    
    rank_str = f"({current_rank})"
    cost_str = ""
    
    # --- ADD THIS FLAG ---
    is_trainable = skill_data.get("trainable", True)

    if ranks_trained_this_lvl >= 3:
        cost_str = "[Maxed]"
    # --- ADD THIS ELIF ---
    elif not is_trainable:
        cost_str = "[LBD Only]"
    else:
        costs = get_skill_costs(player, skill_data)
        multiplier = ranks_trained_this_lvl + 1
        
        cost_str = (
            f"{costs['ptp'] * multiplier}/{costs['mtp'] * multiplier}/{costs['stp'] * multiplier}"
        )
        
    # --- MODIFY THIS BLOCK ---
    if not is_trainable:
        clickable_name = skill_name # Not clickable
    else:
        clickable_name = (
            f"<span class='keyword' data-command='train {skill_name} 1'>"
            f"{skill_name}</span>"
        )
    # --- END MODIFICATION ---
        
    # Use white-space:nowrap to ensure the name doesn't break
    return f"<tr><td style='white-space:nowrap;'>- {clickable_name}</td><td style='text-align:center; white-space:nowrap;'>{cost_str}</td><td style='text-align:right;'>{rank_str}</td></tr>"

# --- REFACTORED: Use player.world ---
def _show_all_skills_by_category(player: Player):
# ... (function contents unchanged) ...
    # Your custom category order
    COLUMN_1_CATEGORIES = [
        "Armor Skills", "Weapon Skills", "Combat Skills", 
        "Defensive Skills", "Physical Skills"
    ]
    COLUMN_2_CATEGORIES = [
        "General Skills", "Subterfuge Skills", "Magical Skills", 
        "Lore Skills", "Mental Skills", "Spiritual Skills"
    ]
    
    # --- NEW: Define custom skill ordering ---
    SKILL_ORDERING = {
        "Weapon Skills": [
            "brawling", "small_edged", "edged_weapons", "two_handed_edged", 
            "small_blunt", "blunt_weapons", "two_handed_blunt", "polearms", 
            "bows", "crossbows", "small_thrown", "large_thrown", "slings", "staves"
        ]
        # You can add other categories here later if you want them reordered
    }
    
    # --- NEW: Get all skills as a dictionary for easy lookup ---
    # --- FIX: Use player.world ---
    all_skills_dict = player.world.game_skills
    
    # --- UPDATED: TIGHTER HEADER ROW ---
    HEADER_ROW = "<tr><td></td><td style='text-decoration: underline; text-align:center;'>PTP/MTP/STP</td><td>Rank</td></tr>"

    # --- Build Column 1 Lines (as HTML table rows) ---
    column_1_lines = []
    # --- FIX: Add header ONCE, *before* the loop ---
    column_1_lines.append(HEADER_ROW)
    
    for category in COLUMN_1_CATEGORIES:
        
        # --- UPDATED: Remove extra space/formatting from category header ---
        column_1_lines.append(f"<tr><td colspan='3'>--- **{category.upper()}** ---</td></tr>")
        
        # --- NEW: Check for custom order ---
        custom_order = SKILL_ORDERING.get(category)
        if custom_order:
            for skill_id in custom_order:
                skill_data = all_skills_dict.get(skill_id)
                # Check if skill exists and *also* matches the category (in case of bad config)
                if skill_data and skill_data.get("category", "Uncategorized") == category:
                    column_1_lines.append(_format_skill_line(player, skill_data))
        else:
            # --- Fallback to alphabetical order ---
            category_skills = []
            for skill_data in all_skills_dict.values():
                if skill_data.get("category", "Uncategorized") == category:
                    category_skills.append(skill_data)
            
            category_skills.sort(key=lambda s: s.get("name", "zzz"))
            
            for skill_data in category_skills:
                column_1_lines.append(_format_skill_line(player, skill_data))
        # --- END NEW LOGIC ---

    # ---
    # --- FIX: ADD THE TRAINING MENU TO THE END OF COLUMN 1 ---
    # ---
    column_1_lines.append("<tr><td colspan='3'>&nbsp;</td></tr>") # Spacer
    column_1_lines.append("<tr><td colspan='3'>--- **SKILL TRAINING** ---</td></tr>")
    # --- UPDATED: CONDENSED TP LINES ---
    column_1_lines.append(f"<tr><td colspan='3'>TPs: P:{player.ptps} / M:{player.mtps} / S:{player.stps}</td></tr>")
    column_1_lines.append("<tr><td colspan='3'>---</td></tr>")
    column_1_lines.append("<tr><td colspan='3'>- Type '<span class='keyword' data-command='list all'>LIST ALL</span>' to see all skills.</td></tr>")
    column_1_lines.append("<tr><td colspan='3'>- Type '<span class='keyword' data-command='list categories'>LIST CATEGORIES</span>' to see skill groups.</td></tr>")
    column_1_lines.append("<tr><td colspan='3'>- Type '<span class='keyword'>TRAIN &lt;skill&gt; &lt;ranks&gt;</span>'</td></tr>")
    column_1_lines.append("<tr><td colspan='3'>- Type '<span class='keyword' data-command='done'>DONE</span>' to finish training.</td></tr>")
    # --- END UPDATED ---


    # --- Build Column 2 Lines (as HTML table rows) ---
    column_2_lines = []
    # --- FIX: Add header ONCE, *before* the loop ---
    column_2_lines.append(HEADER_ROW)

    for category in COLUMN_2_CATEGORIES:
        
        # --- UPDATED: Remove extra space/formatting from category header ---
        column_2_lines.append(f"<tr><td colspan='3'>--- **{category.upper()}** ---</td></tr>")
        
        custom_order = SKILL_ORDERING.get(category)
        if custom_order:
            for skill_id in custom_order:
                skill_data = all_skills_dict.get(skill_id)
                if skill_data and skill_data.get("category", "UncategorDized") == category:
                    column_2_lines.append(_format_skill_line(player, skill_data))
        else:
            category_skills = []
            for skill_data in all_skills_dict.values():
                if skill_data.get("category", "Uncategorized") == category:
                    category_skills.append(skill_data)
            
            category_skills.sort(key=lambda s: s.get("name", "zzz"))
            
            for skill_data in category_skills:
                column_2_lines.append(_format_skill_line(player, skill_data))

    # --- (HTML table assembly logic) ---
    html_lines = []
    COL_1_WIDTH = "50%"
    
    html_lines.append("<table style='width:100%; border-spacing: 0;'>")
    html_lines.append("  <tr style='vertical-align: top;'>") # Align columns to the top
    html_lines.append(f"    <td style='width:{COL_1_WIDTH}; padding-right:10px;'>") # Added right padding
    
    html_lines.append("      <table style='width:100%;'>") # Set inner table to 100% width
    for line in column_1_lines:
        html_lines.append(f"        {line}")
    html_lines.append("      </table>")
    
    html_lines.append("    </td>")
    html_lines.append("    <td>")
    
    html_lines.append("      <table style='width:100%;'>") # Set inner table to 100% width
    for line in column_2_lines:
        html_lines.append(f"        {line}")
    html_lines.append("      </table>")
    
    html_lines.append("    </td>")
    html_lines.append("  </tr>")
    html_lines.append("</table>")

    player.send_message("\n".join(html_lines))

def _show_simple_training_menu(player: Player):
# ... (function contents unchanged) ...
    player.send_message("\n--- **SKILL TRAINING** ---")
    player.send_message(f"--- TPs: P:{player.ptps} / M:{player.mtps} / S:{player.stps} ---")
    player.send_message("- Type '<span class='keyword' data-command='list all'>LIST ALL</span>' to see all skills.")
    player.send_message("- Type '<span class='keyword' data-command='list categories'>LIST CATEGORIES</span>' to see skill groups.")
    player.send_message("- Type '<span class='keyword'>TRAIN &lt;skill&gt; &lt;ranks&gt;</span>' (e.g., TRAIN BRAWLING 1)")
    player.send_message("- Type '<span class='keyword' data-command='done'>DONE</span>' to finish training.")

# --- REFACTORED: Use player.world ---
def show_skill_list(player: Player, category: str):
# ... (function contents unchanged) ...
    category_lower = category.lower()
    
    # --- FIX: Use player.world ---
    all_categories = sorted(list(set(s.get("category", "Uncategorized") for s in player.world.game_skills.values())))
    
    if category_lower == "all":
        _show_all_skills_by_category(player)
        return
        
    if category_lower == "categories":
        player.send_message("--- **Skill Categories** ---")
        for cat in all_categories:
            player.send_message(f"- <span class='keyword' data-command='list {cat}'>{cat}</span>")
        # --- FIX: We must now *manually* show the menu here ---
        # (This is a new function just for this purpose)
        _show_simple_training_menu(player) 
        return

    if category.lower() not in [cat.lower() for cat in all_categories]:
        player.send_message(f"No skills found for category '{category}'.")
        player.send_message("Type '<span class='keyword' data-command='list categories'>LIST CATEGORIES</span>' to see all categories.")
        # --- FIX: We must now *manually* show the menu here ---
        _show_simple_training_menu(player)
        return
        
    player.send_message(f"--- **{category.upper()}** ---")
    
    # --- UPDATED: Sort alphabetically here for the single-category view ---
    sorted_skills = []
    # --- FIX: Use player.world ---
    for skill_data in player.world.game_skills.values():
        if skill_data.get("category", "Uncategorized").lower() == category_lower:
            sorted_skills.append(skill_data)
    sorted_skills.sort(key=lambda s: s.get("name", "zzz"))
    # ---
    
    html_lines = []
    html_lines.append("<table style='width:100%;'>")
    
    html_lines.append("<tr><td></td><td style='text-decoration: underline; text-align:center;'>PTP/MTP/STP</td><td>Rank</td></tr>")
    
    if not sorted_skills:
        player.send_message("No skills are listed in this category.")
        # --- FIX: We must now *manually* show the menu here ---
        _show_simple_training_menu(player)
        return
        
    for skill_data in sorted_skills:
        html_lines.append(_format_skill_line(player, skill_data))
        
    html_lines.append("</table>")
    player.send_message("\n".join(html_lines))
    # --- FIX: We must now *manUally* show the menu here ---
    _show_simple_training_menu(player)

def _calculate_total_cost(player: Player, skill_data: Dict, ranks_to_train: int) -> Dict[str, int]:
# ... (function contents unchanged) ...
    skill_id = skill_data["skill_id"]
    ranks_already_trained = player.ranks_trained_this_level.get(skill_id, 0)
    costs = get_skill_costs(player, skill_data)
    
    total_ptp = 0
    total_mtp = 0
    total_stp = 0
    
    for i in range(ranks_to_train):
        multiplier = (ranks_already_trained + 1) + i
        total_ptp += costs["ptp"] * multiplier
        total_mtp += costs["mtp"] * multiplier
        total_stp += costs["stp"] * multiplier
        
    return {"ptp": total_ptp, "mtp": total_mtp, "stp": total_stp}

def _check_for_tp_conversion(player: Player, total_ptp: int, total_mtp: int, total_stp: int) -> Optional[Dict]:
# ... (function contents unchanged) ...
    ptp_needed = total_ptp - player.ptps
    mtp_needed = total_mtp - player.mtps
    stp_needed = total_stp - player.stps

    # Track what we will convert
    conversions = {
        "ptp_from_convert": 0,
        "mtp_from_convert": 0,
        "stp_from_convert": 0,
    }

    # Use copies of TPs for calculation
    temp_ptp = player.ptps
    temp_mtp = player.mtps
    temp_stp = player.stps
    
    msg = []

    # 1. Check PTP needs
    if ptp_needed > 0:
        # Need to convert MTP+STP -> PTP
        if temp_mtp >= ptp_needed and temp_stp >= ptp_needed:
            conversions["ptp_from_convert"] = ptp_needed
            temp_mtp -= ptp_needed # Cost to convert
            temp_stp -= ptp_needed # Cost to convert
            msg.append(f"convert {ptp_needed} MTP and {ptp_needed} STP into {ptp_needed} PTP")
        else:
            return None # Not enough points to convert for PTP

    # 2. Check MTP needs
    if mtp_needed > 0:
        # Need to convert PTP+STP -> MTP
        # Use temp_ptp (which *hasn't* been spent yet)
        if temp_ptp >= mtp_needed and temp_stp >= mtp_needed:
            conversions["mtp_from_convert"] = mtp_needed
            temp_ptp -= mtp_needed # Cost to convert
            temp_stp -= mtp_needed # Cost to convert
            msg.append(f"convert {mtp_needed} PTP and {mtp_needed} STP into {mtp_needed} MTP")
        else:
            return None # Not enough points to convert for MTP

    # 3. Check STP needs
    if stp_needed > 0:
        # Need to convert PTP+MTP -> STP
        if temp_ptp >= stp_needed and temp_mtp >= stp_needed:
            conversions["stp_from_convert"] = stp_needed
            temp_ptp -= stp_needed # Cost to convert
            temp_mtp -= stp_needed # Cost to convert
            msg.append(f"convert {stp_needed} PTP and {stp_needed} MTP into {stp_needed} STP")
        else:
            return None # Not enough points to convert for STP

    if not msg:
        # This should not be hit if train_skill() logic is correct
        return None 

    # Final check: Do we have enough *after* conversion costs?
    final_ptp = (player.ptps - (conversions["mtp_from_convert"] + conversions["stp_from_convert"]) 
                 + conversions["ptp_from_convert"])
    final_mtp = (player.mtps - (conversions["ptp_from_convert"] + conversions["stp_from_convert"])
                 + conversions["mtp_from_convert"])
    final_stp = (player.stps - (conversions["ptp_from_convert"] + conversions["mtp_from_convert"])
                 + conversions["stp_from_convert"])

    if final_ptp < total_ptp or final_mtp < total_mtp or final_stp < total_stp:
        # This catches complex cases, e.g. needing PTP but spending PTP to make MTP
        return None 

    return {
        "conversions": conversions,
        "msg": f"You do not have enough TPs. This will {', '.join(msg)}."
    }

def _perform_conversion_and_train(player: Player, pending_data: Dict):
# ... (function contents unchanged) ...
    skill_id = pending_data["skill_id"]
    skill_name = pending_data["skill_name"]
    ranks_to_train = pending_data["ranks_to_train"]
    total_cost = pending_data["total_cost"]
    conversion_data = pending_data.get("conversion_data") # Might be None

    if conversion_data:
        conversions = conversion_data["conversions"]
        
        # 1. Apply Conversions
        # 1a. Spend TPs for PTP
        ptp_gained = conversions["ptp_from_convert"]
        if ptp_gained > 0:
            player.mtps -= ptp_gained
            player.stps -= ptp_gained
            player.ptps += ptp_gained
            player.send_message(f"You converted {ptp_gained} MTP and {ptp_gained} STP into {ptp_gained} PTP.")

        # 1b. Spend TPs for MTP
        mtp_gained = conversions["mtp_from_convert"]
        if mtp_gained > 0:
            player.ptps -= mtp_gained
            player.stps -= mtp_gained
            player.mtps += mtp_gained
            player.send_message(f"You converted {mtp_gained} PTP and {mtp_gained} STP into {mtp_gained} MTP.")
            
        # 1c. Spend TPs for STP
        stp_gained = conversions["stp_from_convert"]
        if stp_gained > 0:
            player.ptps -= stp_gained
            player.mtps -= stp_gained
            player.stps += stp_gained
            player.send_message(f"You converted {stp_gained} PTP and {stp_gained} MTP into {stp_gained} STP.")

    # 2. Spend TPs for the skill
    player.ptps -= total_cost["ptp"]
    player.mtps -= total_cost["mtp"]
    player.stps -= total_cost["stp"]

    # 3. Apply Skill Ranks
    ranks_already_trained = player.ranks_trained_this_level.get(skill_id, 0)
    new_rank = player.skills.get(skill_id, 0) + ranks_to_train
    player.skills[skill_id] = new_rank
    player.ranks_trained_this_level[skill_id] = ranks_already_trained + ranks_to_train
    
    player.send_message(f"You train **{skill_name}** to rank **{new_rank}**!")
    
    # 4. Clean up pending state
    player.db_data.pop('_pending_training', None)

    # 5. Show the menus
    # --- FIX: Removed the "All Skills" title ---
    _show_all_skills_by_category(player)
    # --- FIX: Removed call to show_training_menu ---
    # (It's now part of the function above)

# --- REFACTORED: Use player.world ---
def train_skill(player: Player, skill_name: str, ranks_to_train: int):
# ... (function contents unchanged) ...
    if ranks_to_train <= 0:
        player.send_message("You must train at least 1 rank.")
        return
        
    # --- FIX: Pass player.world to helper ---
    skill_data = _find_skill_by_name(player.world, skill_name)
    if not skill_data:
        player.send_message(f"Unknown skill: '{skill_name}'.")
        return
        
    # --- ADD THIS CHECK ---
    if not skill_data.get("trainable", True):
        player.send_message(f"You cannot train {skill_data['name']}. It can only be learned by doing.")
        return
    # --- END ADDITION ---

    skill_id = skill_data["skill_id"]
    
    # 1. Check level-based rank limits
    ranks_already_trained = player.ranks_trained_this_level.get(skill_id, 0)
    if ranks_already_trained >= 3:
        player.send_message(f"You have already trained **{skill_data['name']}** 3 times this level.")
        return
        
    if ranks_already_trained + ranks_to_train > 3:
        player.send_message(f"You can only train {3 - ranks_already_trained} more rank(s) in **{skill_data['name']}** this level.")
        return
    
    # 2. Calculate total cost
    total_cost = _calculate_total_cost(player, skill_data, ranks_to_train)
    total_ptp = total_cost["ptp"]
    total_mtp = total_cost["mtp"]
    total_stp = total_cost["stp"]

    # 3. Check if player has enough TPs
    has_enough_ptp = player.ptps >= total_ptp
    has_enough_mtp = player.mtps >= total_mtp
    has_enough_stp = player.stps >= total_stp
    
    pending_data = {
        "skill_id": skill_id,
        "skill_name": skill_data["name"],
        "ranks_to_train": ranks_to_train,
        "total_cost": total_cost,
        "conversion_data": None # Assume no conversion needed
    }

    if has_enough_ptp and has_enough_mtp and has_enough_stp:
        # 4. SUCCESS: Train immediately
        _perform_conversion_and_train(player, pending_data)
    else:
        # 5. FAILURE: Check for possible conversion
        conversion_data = _check_for_tp_conversion(player, total_ptp, total_mtp, total_stp)
        
        if conversion_data:
            # 6. CONVERSION POSSIBLE: Set pending state
            pending_data["conversion_data"] = conversion_data
            player.db_data['_pending_training'] = pending_data
            
            # Send confirmation prompt
            player.send_message(conversion_data['msg'])
            player.send_message("Type '<span class='keyword' data-command='train CONFIRM'>TRAIN CONFIRM</span>' to proceed with the conversion and training.")
            player.send_message("Type '<span class='keyword' data-command='train CANCEL'>TRAIN CANCEL</span>' to abort.")
        else:
            # 7. CONVERSION IMPOSSIBLE: Send error messages
            if not has_enough_ptp:
                player.send_message(f"You need {total_ptp} PTPs but only have {player.ptps} (and cannot convert).")
            if not has_enough_mtp:
                player.send_message(f"You need {total_mtp} MTPs but only have {player.mtps} (and cannot convert).")
            if not has_enough_stp:
                player.send_message(f"You need {total_stp} STPs but only have {player.stps} (and cannot convert).")


# ---
# --- NEW: Learn By Doing (LBD) Function
# ---

# Define skill categories for stat-based learning
# (This is an approximation based on your description)
LBD_COMBAT_CATEGORIES = [
    "Armor Skills", "Weapon Skills", "Combat Skills", 
    "Defensive Skills", "Physical Skills", "Subterfuge Skills",
    "General Skills"
]
LBD_MAGIC_LORE_CATEGORIES = [
    "Magical Skills", "Lore Skills", "Mental Skills", "Spiritual Skills"
]

def attempt_skill_learning(player: Player, skill_id: str):
    """
    Attempts to gain skill experience (LBD) for a given skill.
    This function handles the roll, point gain, and rank-up.
    """
    
    skill_data = player.world.game_skills.get(skill_id)
    if not skill_data:
        print(f"[LBD ERROR] Invalid skill_id: {skill_id}")
        return
        
    skill_name = skill_data.get("name", "a skill")
    current_rank = player.skills.get(skill_id, 0)
    
    # 1. Define Gain Chance
    # Per your formula: Learn_Chance_Percent = max(5, Base_Learn_Chance - (Current_Rank * Diminishing_Return))
    base_learn_chance = 50.0 
    diminishing_return = 0.1

    learn_chance_percent = max(5.0, base_learn_chance - (current_rank * diminishing_return))
    
    roll = random.random() * 100 # Roll 0.0 to 99.99...
    
    if roll > learn_chance_percent:
        # Failed to learn
        return

    # 2. Define Learning Rate (Stat-Based)
    log_bonus = get_stat_bonus(player.stats.get("LOG", 50), "LOG", player.race)
    int_bonus = get_stat_bonus(player.stats.get("INT", 50), "INT", player.race)
    wis_bonus = get_stat_bonus(player.stats.get("WIS", 50), "WIS", player.race)
    
    learning_stat_bonus = 0
    skill_category = skill_data.get("category", "General Skills")
    
    if skill_category in LBD_MAGIC_LORE_CATEGORIES:
        # Magic/Lore skills
        learning_stat_bonus = math.trunc(log_bonus / 2) + math.trunc(wis_bonus / 2)
    else:
        # Combat / General / Other skills
        learning_stat_bonus = math.trunc(log_bonus / 2) + math.trunc(int_bonus / 2)
        
    points_gained = 1 + math.trunc(learning_stat_bonus / 10)
    
    # 3. Add Points and Check for Rank-Up
    current_points = player.skill_learning_progress.get(skill_id, 0)
    current_points += points_gained
    
    # Define Threshold
    # Using your example: Rank 0 -> 1 = 1000 points
    points_for_next_rank = (current_rank + 1) * 1000
    
    if current_points >= points_for_next_rank:
        # --- RANK UP! ---
        new_rank = current_rank + 1
        points_overflow = current_points - points_for_next_rank
        
        player.skills[skill_id] = new_rank
        player.skill_learning_progress[skill_id] = points_overflow
        
        player.send_message(f"**You have advanced to rank {new_rank} in {skill_name}!**")
        
        # Check for another rank up (in case of massive overflow)
        # This simple recursive call will handle it
        attempt_skill_learning(player, skill_id)
        
    else:
        # --- Gained Points ---
        player.skill_learning_progress[skill_id] = current_points
        player.send_message(
            f"You feel you have learned something new about {skill_name}. "
            f"({current_points}/{points_for_next_rank})"
        )