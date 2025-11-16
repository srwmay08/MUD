# mud_backend/core/room_handler.py
from mud_backend.core.game_objects import Player, Room
# --- MODIFIED: Import environment module and global weather ---
from mud_backend.core.game_loop import environment
from typing import Dict, Any, Optional

# ---
# --- NEW HELPER FUNCTION
# ---
# ... (rest of _get_time_grouping and _get_dynamic_description are unchanged) ...
def _get_time_grouping(time_of_day_str: str) -> str:
    """Categorizes the 16-step time into 5 broad groups for fallbacks."""
    # Specific keys are checked first
    if time_of_day_str in ["dawn", "noon", "dusk", "midnight"]:
        return time_of_day_str.upper() # DAWN, NOON, DUSK, MIDNIGHT
        
    if time_of_day_str in ["early morning", "mid morning", "late morning"]:
        return "MORNING"
    if time_of_day_str in ["early afternoon", "mid afternoon", "late afternoon"]:
        return "AFTERNOON"
    if time_of_day_str in ["early evening", "mid evening", "late evening"]:
        return "EVENING"
    if time_of_day_str in ["night", "early night", "late night"]:
        return "NIGHT"
    return "NIGHT" # Default case

def _get_dynamic_description(
    room_descriptions: Any, 
    time_of_day: str, 
    weather: str
) -> str:
    """
    Finds the best matching description from the room's description block.
    """
    
    # 1. Handle old, simple string descriptions
    if isinstance(room_descriptions, str):
        return room_descriptions
        
    # 2. Handle missing or non-dict descriptions
    if not isinstance(room_descriptions, dict):
        return "It is a room. (Description Error)"

    # Get the time "group" (e.g., DAWN, MORNING, NOON, AFTERNOON, etc.)
    time_key = _get_time_grouping(time_of_day)

    # --- Start Fallback Chain ---

    # 1. Try to get the specific time block (e.g., "DAWN")
    time_block = room_descriptions.get(time_key)
    if isinstance(time_block, dict):
        # 1a. Try to get specific weather (e.g., "DAWN" -> "storm")
        desc = time_block.get(weather)
        if desc:
            return desc
        # 1b. Fallback to clear weather (e.g., "DAWN" -> "clear")
        desc = time_block.get("clear")
        if desc:
            return desc
            
    # 2. Try to get the "default" time block
    default_block = room_descriptions.get("default")
    if isinstance(default_block, dict):
        # 2a. Try to get specific weather (e.g., "default" -> "storm")
        # (This is for the old format, like your original file)
        desc = default_block.get(weather)
        if desc:
            return desc
        # 2b. Fallback to clear weather (e.g., "default" -> "clear")
        desc = default_block.get("clear")
        if desc:
            return desc
            
    # 3. Fallback to the simple "default" string
    # (This catches both "default": "..." and the old "storm": "...")
    desc = room_descriptions.get(weather)
    if isinstance(desc, str):
        return desc
        
    desc = room_descriptions.get("default")
    if isinstance(desc, str):
        return desc

    # 4. Total failure
    return "You are in a nondescript location."


def show_room_to_player(player: Player, room: Room):
    """
    Sends all room information (name, desc, objects, exits, players) to the player.
    """
    # Send Room Name
    player.send_message(f"**{room.name}**")
    
    # Get Dynamic Description
    room_descriptions = room.description
    current_time = environment.current_time_of_day # Get current time
    current_weather = environment.current_weather # Get current weather
    
    room_desc_text = _get_dynamic_description(
        room_descriptions, 
        current_time, 
        current_weather
    )
    
    # --- START MODIFICATION ---
    
    # 1. Get all visible objects
    player_perception = player.stats.get("WIS", 0)
    visible_objects = []
    if room.objects:
        for obj in room.objects:
            obj_dc = obj.get("perception_dc", 0)
            if player_perception >= obj_dc:
                visible_objects.append(obj)
    
    # 2. Define the sorting key function
    def get_sort_key(obj):
        # True = 1, False = 0.
        # We sort by (not is_npc), (not is_monster), name.
        # NPC: (not True, ...) -> (0, ...) -> First
        # Monster: (not False, not True, ...) -> (1, 0, ...) -> Second
        # Object: (not False, not False, ...) -> (1, 1, ...) -> Third
        is_npc = obj.get('is_npc', False)
        is_monster = obj.get('is_monster', False)
        name = obj.get('name', '')
        
        # Ensure NPCs that are *also* monsters (like guards) are still NPCs
        if is_npc:
            is_monster = False # Treat them only as NPCs for sorting
            
        return (not is_npc, not is_monster, name)

    # 3. Sort the visible objects
    sorted_objects = sorted(visible_objects, key=get_sort_key)
    
    # 4. Build the clickable object names from the sorted list
    object_names = []
    for obj in sorted_objects:
        obj_name = obj['name']
        verbs = obj.get('verbs', ['look', 'examine', 'investigate'])
        verb_str = ','.join(verbs).lower()
        object_names.append(
            f'<span class="keyword" data-name="{obj_name}" data-verbs="{verb_str}">{obj_name}</span>'
        )
    
    # 5. Build the "You also see..." string
    if object_names:
        objects_str = ""
        if len(object_names) == 1:
            objects_str = f"You also see {object_names[0]}."
        elif len(object_names) == 2:
            objects_str = f"You also see {object_names[0]} and {object_names[1]}."
        else:
            # Join all but the last with a comma, then add "and" before the last one
            all_but_last = ", ".join(object_names[:-1])
            last = object_names[-1]
            objects_str = f"You also see {all_but_last}, and {last}."
        
        # Append this string to the main description as a new line
        room_desc_text += f"\n{objects_str}"
        
    # 6. Send the combined room description and object list
    player.send_message(room_desc_text)

    # 7. REMOVED the old "Obvious objects here:" block
    
    # --- END MODIFICATION ---
    
    # --- Show Other Players (Unchanged) ---
    other_players_in_room = []
    
    for sid, data in player.world.get_all_players_info():
        player_name_in_room = data["player_name"] 

        if player_name_in_room.lower() == player.name.lower():
            continue
        
        if data["current_room_id"] == room.room_id:
            other_players_in_room.append(
                f'<span class="keyword" data-name="{player_name_in_room}" data-verbs="look">{player_name_in_room}</span>'
            )
            
    if other_players_in_room:
        player.send_message(f"Also here: {', '.join(other_players_in_room)}.")
    # --- END UPDATED LOGIC ---

    # --- Show Exits (Modified for paths/exits) ---
    if room.exits:
        exit_names = []
        for name in room.exits.keys():
            exit_names.append(f'<span class="keyword" data-command="{name}">{name.capitalize()}</span>')
        
        # --- START MODIFICATION ---
        # Use the room's data to check if it's an outdoor room
        is_outdoor = room.db_data.get("is_outdoor", False)
        exit_label = "Obvious paths" if is_outdoor else "Obvious exits"
        
        player.send_message(f"{exit_label}: {', '.join(exit_names)}")
        # --- END MODIFICATION ---