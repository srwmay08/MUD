# mud_backend/core/quest_handler.py
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from mud_backend.core.game_objects import Player

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
    from mud_backend.core.game_objects import Player

def get_active_quest_for_npc(player: Player, npc_quest_ids: List[str]) -> Optional[Dict[str, Any]]:
    """
    Finds the first available quest for a player from an NPC's quest list.

    Returns:
        The quest dictionary (from game_quests) if an active quest is found,
        otherwise None.
    """
    if not npc_quest_ids:
        return None

    all_quests = player.world.game_quests
    
    for quest_id in npc_quest_ids:
        quest_data = all_quests.get(quest_id)
        if not quest_data:
            continue

        # 1. Check if quest is already complete
        reward_spell = quest_data.get("reward_spell")
        reward_maneuver = quest_data.get("reward_maneuver")
        
        # ---
        # --- THIS IS THE FIX ---
        # We need to correctly check if the quest is done, specifically
        # for the "trip_training" maneuver.
        # ---
        is_done = False
        if quest_id in player.completed_quests:
            is_done = True
        elif reward_spell and reward_spell in player.known_spells:
            is_done = True
        elif reward_maneuver:
            if reward_maneuver == "trip_training":
                # For this quest, only knowing the *final* skill "trip"
                # counts as being done.
                if "trip" in player.known_maneuvers:
                    is_done = True
            else:
                # For any other maneuver (e.g., "bash"),
                # knowing it counts as completion.
                if reward_maneuver in player.known_maneuvers:
                    is_done = True
        # --- END FIX ---

        if is_done:
            continue # This quest is done, check the next one

        # 2. Check prerequisites
        prereq_spell = quest_data.get("prereq_spell")
        if prereq_spell and prereq_spell not in player.known_spells:
            continue # Player doesn't meet the prereq, so this isn't active yet

        # 3. If we are here, the quest is not complete AND prerequisites are met.
        # This is the active quest.
        return quest_data

    # No active quests found for this player
    return None