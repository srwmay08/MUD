# mud_backend/core/faction_handler.py
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
    from mud_backend.core.game_objects import Player

def get_effective_faction_value(player: 'Player', faction_id: str) -> int:
    """
    Calculates the effective faction standing.
    Effective = Earned (Quests/Kills) + Racial Modifiers + Deity Modifiers
    """
    # 1. Earned Value (Mutable)
    earned_value = player.factions.get(faction_id, 0)
    
    # 2. Racial Modifiers (Permanent)
    race_mods = player.race_data.get("faction_modifiers", {})
    race_bonus = race_mods.get(faction_id, 0)
    
    # 3. Deity Modifiers (Permanent)
    deity_bonus = 0
    for deity_key in player.deities:
        deity_data = player.world.assets.deities.get(deity_key)
        if deity_data:
            d_mods = deity_data.get("faction_modifiers", {})
            deity_bonus += d_mods.get(faction_id, 0)
            
    return earned_value + race_bonus + deity_bonus

def get_con_level(world: 'World', faction_value: int) -> str:
    """
    Takes a numerical faction value and returns the corresponding
    con level string (e.g., "Amiable", "Threatening").
    """
    con_levels = world.game_factions.get("config", {}).get("con_levels", [])
    default_con = world.game_factions.get("config", {}).get("default_con", "Indifferent")
    
    for level in con_levels:
        if level.get("min", 0) <= faction_value <= level.get("max", 0):
            return level.get("name", default_con)
            
    return default_con

def get_player_faction_con(player: 'Player', target_faction: str) -> str:
    """
    Gets the player's current con level (string) for a specific faction.
    """
    if not target_faction:
        return get_con_level(player.world, 0)
        
    effective_value = get_effective_faction_value(player, target_faction)
    return get_con_level(player.world, effective_value)

def adjust_player_faction(player: 'Player', faction_id: str, amount: int, propagate: bool = True):
    """
    Adjusts a player's EARNED faction standing.
    If propagate is True, it also adjusts opposing factions inversely.
    """
    if amount == 0:
        return

    # Update Earned Value
    current_earned = player.factions.get(faction_id, 0)
    new_earned = current_earned + amount
    
    # Clamp earned values (optional, prevents integer overflow or excessive grinding)
    # We clamp the EARNED portion, though effective can go higher due to race/deity
    new_earned = max(-5000, min(5000, new_earned))
    
    player.factions[faction_id] = new_earned
    
    # Feedback
    faction_config = player.world.game_factions.get("factions", {}).get(faction_id, {})
    faction_name = faction_config.get("name", faction_id)
    
    if amount > 0:
        player.send_message(f"Your standing with {faction_name} has improved.")
    else:
        player.send_message(f"Your standing with {faction_name} has worsened.")

    # Handle Opposing Factions
    if propagate:
        opposing_ids = faction_config.get("opposing_factions", [])
        for opp_id in opposing_ids:
            # Inverse adjustment
            # You can tune the ratio. Here it is 1:1 inverse.
            inverse_amount = -amount
            adjust_player_faction(player, opp_id, inverse_amount, propagate=False)

def are_factions_kos(world: 'World', faction_a: str, faction_b: str) -> bool:
    """
    Checks if two factions are inherently Kill-on-Sight (KOS) with each other.
    """
    if not faction_a or not faction_b:
        return False
        
    all_factions = world.game_factions.get("factions", {})
    
    faction_a_data = all_factions.get(faction_a)
    faction_b_data = all_factions.get(faction_b)
    
    if not faction_a_data or not faction_b_data:
        return False
        
    if faction_b in faction_a_data.get("kos_factions", []):
        return True
    if faction_a in faction_b_data.get("kos_factions", []):
        return True
        
    return False

def is_player_kos_to_entity(player: 'Player', entity: Dict[str, Any]) -> bool:
    """
    Checks if the player is KOS to an entity based on effective standing.
    """
    entity_faction = entity.get("faction")
    if not entity_faction:
        return False 
        
    effective_value = get_effective_faction_value(player, entity_faction)
    con_level = get_con_level(player.world, effective_value)
    
    if con_level in ["Threatening", "Scowls"]:
        return True
        
    return False

def get_faction_adjustments_on_kill(world: 'World', entity_faction: str) -> Dict[str, int]:
    if not entity_faction:
        return {}
    faction_data = world.game_factions.get("factions", {}).get(entity_faction, {})
    return faction_data.get("on_kill", {})