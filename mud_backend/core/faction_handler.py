# mud_backend/core/faction_handler.py
from typing import Dict, Any, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
    from mud_backend.core.game_objects import Player

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
        
    faction_value = player.factions.get(target_faction, 0)
    return get_con_level(player.world, faction_value)

def adjust_player_faction(player: 'Player', faction_id: str, amount: int):
    """
    Adjusts a player's faction standing by a specific amount and
    sends a feedback message.
    """
    if amount == 0:
        return

    current_value = player.factions.get(faction_id, 0)
    new_value = current_value + amount
    
    # Clamp values to the max/min defined
    con_levels = player.world.game_factions.get("config", {}).get("con_levels", [])
    min_faction = min(level.get("min", 0) for level in con_levels) if con_levels else -2000
    max_faction = max(level.get("max", 0) for level in con_levels) if con_levels else 2000
    
    new_value = max(min_faction, min(max_faction, new_value))
    
    player.factions[faction_id] = new_value
    
    # Get faction display name
    faction_name = player.world.game_factions.get("factions", {}).get(faction_id, {}).get("name", faction_id)
    
    if amount > 0:
        player.send_message(f"Your standing with {faction_name} has improved.")
    else:
        player.send_message(f"Your standing with {faction_name} has worsened.")

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
    Checks if the player is KOS to an entity based on the player's
    faction standing with that entity's group.
    
    (e.g., Orcs hate you, so they will attack you).
    """
    entity_faction = entity.get("faction")
    if not entity_faction:
        return False # Entity has no faction, won't attack
        
    player_faction_value = player.factions.get(entity_faction, 0)
    
    con_level = get_con_level(player.world, player_faction_value)
    
    if con_level in ["Threatening", "Scowls"]:
        return True
        
    return False

def get_faction_adjustments_on_kill(world: 'World', entity_faction: str) -> Dict[str, int]:
    """
    Gets the dictionary of faction adjustments for killing a member
    of the given faction.
    """
    if not entity_faction:
        return {}
        
    faction_data = world.game_factions.get("factions", {}).get(entity_faction, {})
    return faction_data.get("on_kill", {})