# mud_backend/core/room_handler.py
import copy
import uuid
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
    player.send_message(f"**{room.name}**")
    
    # --- NEW LOGIC FOR DESCRIPTIONS ---
    room_descriptions = room.description
    current_time = environment.current_time_of_day # Get current time
    current_weather = environment.current_weather # Get current weather
    
    # Use the new helper to find the best description
    room_desc_text = _get_dynamic_description(
        room_descriptions, 
        current_time, 
        current_weather
    )
        
    player.send_message(room_desc_text)
    # --- END NEW LOGIC ---
    
    # ---
    # --- REMOVED redundant ambient_desc. The main description
    # --- now contains all the time and weather info.
    # ---
    
    # ---
    # --- THIS IS THE FIX: Insert Template Merging Logic
    # ---
    live_room_objects = []
    all_objects = room.objects # Get the raw list from the Room object
    
    if all_objects:
        for obj in all_objects:
            is_monster = obj.get("is_monster")
            is_npc = obj.get("is_npc")
            node_id = obj.get("node_id")

            if (is_monster or is_npc) and not node_id:
                uid = obj.get("uid")
                if player.world.get_defeated_monster(uid) is not None:
                    continue 
                
                monster_id = obj.get("monster_id")
                if monster_id and "stats" not in obj:
                    template = player.world.game_monster_templates.get(monster_id)
                    if template:
                        # --- Create a new object by merging ---
                        merged_obj = copy.deepcopy(template)
                        merged_obj.update(obj)
                        # Ensure original UID is preserved
                        if "uid" in obj:
                            merged_obj["uid"] = obj["uid"]
                        live_room_objects.append(merged_obj)
                    else:
                         live_room_objects.append(obj) # Append original if template not found
                else:
                    live_room_objects.append(obj) # Already a full object (or corpse)
            
            elif node_id:
                template = player.world.game_nodes.get(node_id)
                if template:
                    merged_obj = copy.deepcopy(template)
                    merged_obj.update(obj)
                    if "uid" not in merged_obj:
                         merged_obj["uid"] = uuid.uuid4().hex
                    live_room_objects.append(merged_obj)
                # If template not found, it's skipped (no "else")
            
            else:
                live_room_objects.append(obj)
    # ---
    # --- END FIX
    # ---

    # --- Skill-Based Object Perception ---
    player_perception = player.stats.get("WIS", 0)
    
    # 1. Show Objects
    # --- MODIFIED: Iterate over live_room_objects ---
    if live_room_objects:
        html_objects = []
        for obj in live_room_objects:
    # --- END MODIFIED ---
            obj_dc = obj.get("perception_dc", 0)
            if player_perception >= obj_dc:
                # --- This line will no longer crash ---
                obj_name = obj['name'] 
                verbs = obj.get('verbs', ['look', 'examine', 'investigate'])
                verb_str = ','.join(verbs).lower()
                html_objects.append(
                    f'<span class="keyword" data-name="{obj_name}" data-verbs="{verb_str}">{obj_name}</span>'
                )
        
        if html_objects:
            player.send_message(f"\nObvious objects here: {', '.join(html_objects)}.")
    
    # --- UPDATED: Show Other Players ---
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

    # 2. Show Exits
    if room.exits:
        # --- MODIFICATION: Create clickable exit links ---
        exit_names = []
        for name in room.exits.keys():
            exit_names.append(f'<span class="keyword" data-command="{name}">{name.capitalize()}</span>')
        player.send_message(f"Obvious exits: {', '.join(exit_names)}")
        # --- END MODIFICATION ---