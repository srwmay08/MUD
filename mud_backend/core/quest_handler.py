# mud_backend/core/quest_handler.py
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from mud_backend.core.game_objects import Player

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

def initialize_quest_listeners(world: 'World'):
    """
    Registers quest logic to the Event Bus.
    Call this during server startup.
    """
    world.event_bus.subscribe("mob_death", lambda **kwargs: _handle_mob_death_event(world, **kwargs))
    world.event_bus.subscribe("room_enter", lambda **kwargs: _handle_room_enter_event(world, **kwargs))
    world.event_bus.subscribe("social_success", lambda **kwargs: _handle_social_event(world, **kwargs))
    world.event_bus.subscribe("craft_success", lambda **kwargs: _handle_craft_event(world, **kwargs))

def _handle_mob_death_event(world, player: Player, monster_id: str, source_type: str = "physical", source_id: str = None, **kwargs):
    """
    Handles 'Kill X' and 'Syntax Kill' quest updates.
    """
    for quest_id, quest_data in world.game_quests.items():
        # Skip if already complete or not active (prereqs not met)
        if not _is_quest_available(player, quest_data, check_prereqs_only=True):
            continue
            
        # 1. Standard Kill Counter
        req_counters = quest_data.get("req_counters", {})
        
        # Direct Monster ID Match
        counter_key = f"{monster_id}_kills"
        if counter_key in req_counters:
            # 2. Syntax Kill Check (Specific Method)
            required_method = quest_data.get("required_kill_method") # e.g. {"source": "spell", "id": "fireball"}
            
            if required_method:
                req_src = required_method.get("source")
                req_id = required_method.get("id")
                if req_src and req_src != source_type: continue
                if req_id and req_id != source_id: continue
            
            # Increment
            current_val = player.quest_counters.get(counter_key, 0)
            if current_val < req_counters[counter_key]:
                player.quest_counters[counter_key] = current_val + 1
                player.send_message(f"[Quest Update] {counter_key.replace('_', ' ').title()}: {player.quest_counters[counter_key]}/{req_counters[counter_key]}")
                player.mark_dirty()

def _handle_room_enter_event(world, player: Player, room_id: str, **kwargs):
    """
    Handles 'Cartographer' and 'Ghost Walk' updates.
    """
    # Update visited rooms for map logic
    if room_id not in player.visited_rooms:
        player.visited_rooms.append(room_id)

    for quest_id, quest_data in world.game_quests.items():
        if not _is_quest_available(player, quest_data, check_prereqs_only=True): continue

        # Cartographer Logic
        req_rooms = quest_data.get("required_rooms_visited", [])
        if room_id in req_rooms:
            counter_key = f"visited_{room_id}"
            if not player.quest_counters.get(counter_key):
                player.quest_counters[counter_key] = 1
                player.send_message(f"[Quest Update] You have scouted {room_id}!")
                player.mark_dirty()

        # Ghost Walk Logic (Fail condition)
        forbidden_detection = quest_data.get("fail_on_detection", False)
        if forbidden_detection:
            # Check if player is sneaking (flag handled in movement/stealth)
            is_sneaking = player.flags.get("sneaking", "off") == "on"
            # If room has mobs and player isn't sneaking -> Fail
            room = world.get_active_room_safe(room_id)
            has_mobs = any(obj.get("is_monster") for obj in room.objects)
            
            if has_mobs and not is_sneaking:
                player.send_message(f"**!** You were spotted! The '{quest_data['name']}' quest has failed.")
                # Reset counters or mark failed state
                player.quest_counters[f"{quest_id}_failed"] = 1

def _handle_social_event(world, player: Player, npc_id: str, action_type: str, **kwargs):
    """
    Handles 'Social Duel' updates (Bribe/Threaten success).
    """
    for quest_id, quest_data in world.game_quests.items():
        if not _is_quest_available(player, quest_data, check_prereqs_only=True): continue
        
        target_npc = quest_data.get("social_target_id")
        required_action = quest_data.get("social_action_type") # e.g. "bribe"
        
        if target_npc == npc_id and required_action == action_type:
            counter_key = f"social_{npc_id}_{action_type}"
            current = player.quest_counters.get(counter_key, 0)
            player.quest_counters[counter_key] = current + 1
            player.send_message(f"[Quest Update] Social progress made with {npc_id}.")
            player.mark_dirty()

def _handle_craft_event(world, player: Player, item_id: str, **kwargs):
    """
    Handles 'Crafter's Order' updates.
    """
    for quest_id, quest_data in world.game_quests.items():
        if not _is_quest_available(player, quest_data, check_prereqs_only=True): continue
        
        if quest_data.get("crafted_item_id") == item_id:
            counter_key = f"crafted_{item_id}"
            current = player.quest_counters.get(counter_key, 0)
            target = quest_data.get("crafted_item_quantity", 1)
            
            if current < target:
                player.quest_counters[counter_key] = current + 1
                player.send_message(f"[Quest Update] Crafted {item_id}: {player.quest_counters[counter_key]}/{target}")
                player.mark_dirty()

def _is_quest_available(player: Player, quest_data: Dict, check_prereqs_only: bool = False) -> bool:
    """Helper to check if a quest is active/available for the player."""
    # --- FIX: Prefer 'id' if injected, fallback to 'name' but beware of conflicts ---
    quest_id = quest_data.get("id", quest_data.get("name"))
    if not quest_id: return False
    
    # If checking for active updates, we only care if it's NOT complete
    if check_prereqs_only and quest_id in player.completed_quests:
        return False

    prereq_quest = quest_data.get("prereq_quest")
    if prereq_quest and prereq_quest not in player.completed_quests:
        return False
        
    # Reputation Gate Check
    required_rep = quest_data.get("required_faction_score")
    if required_rep:
        faction = required_rep.get("faction")
        min_score = required_rep.get("min_score", -9999)
        max_score = required_rep.get("max_score", 9999)
        
        # Import locally to avoid circular dependency if needed, 
        # or assume player has factions dict populated
        current_score = player.factions.get(faction, 0)
        if not (min_score <= current_score <= max_score):
            return False

    return True

def get_active_quest_for_npc(player: Player, npc_quest_ids: List[str]) -> Optional[Dict[str, Any]]:
    """
    Legacy wrapper: Finds the first available quest for Talk interaction.
    """
    if not npc_quest_ids: return None
    for qid in npc_quest_ids:
        q_data = player.world.game_quests.get(qid)
        if q_data and _is_quest_available(player, q_data):
            if qid in player.completed_quests: continue
            return q_data
    return None