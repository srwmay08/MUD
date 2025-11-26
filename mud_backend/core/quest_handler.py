# mud_backend/core/quest_handler.py
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from mud_backend.core.game_objects import Player

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

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
        if quest_id in player.completed_quests: continue
        
        reward_spell = quest_data.get("reward_spell")
        if reward_spell and reward_spell in player.known_spells: continue
        
        reward_maneuver = quest_data.get("reward_maneuver")
        if reward_maneuver:
            if reward_maneuver == "trip_training":
                if "trip" in player.known_maneuvers: continue
            elif reward_maneuver in player.known_maneuvers: continue

        # 2. Check prerequisites
        prereq_spell = quest_data.get("prereq_spell")
        if prereq_spell and prereq_spell not in player.known_spells:
            continue 
            
        prereq_quest = quest_data.get("prereq_quest")
        if prereq_quest and prereq_quest not in player.completed_quests:
            continue

        # 3. Check Counter Requirements
        # Used for "Kill X" or "Perform X Action" style steps.
        # We DO NOT skip the quest if counters aren't met; 
        # we return it as "active" so the Talk verb can tell the player "Not done yet".
        
        # Support single legacy counter
        req_counter_key = quest_data.get("req_counter")
        if req_counter_key:
             # Logic handled in Talk verb to show progress
             pass

        # Support multiple counters
        req_counters = quest_data.get("req_counters")
        if req_counters:
             # Logic handled in Talk verb to show progress
             pass

        # 4. If we are here, the quest is not complete AND prerequisites are met.
        # This is the active quest.
        return quest_data

    # No active quests found for this player
    return None