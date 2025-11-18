# mud_backend/core/room_handler.py
import copy
import uuid
import random # <-- NEW IMPORT
from mud_backend.core.game_objects import Player, Room
# --- MODIFIED: Import environment module and global weather ---
from mud_backend.core.game_loop import environment
from typing import Dict, Any, Optional, TYPE_CHECKING # <-- MODIFIED
# --- NEW: Import quest handler ---
from mud_backend.core.quest_handler import get_active_quest_for_npc

if TYPE_CHECKING:
    from mud_backend.core.game_state import World
# --- END NEW ---


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


# ---
# --- THIS IS THE NEW SORTING HELPER
# ---
def _get_object_sort_priority(obj: Dict[str, Any]) -> int:
    """Assigns a numerical priority to objects for sorting."""
    if obj.get("is_npc"):
        return 1
    if obj.get("is_monster"):
        return 2
    if obj.get("is_gathering_node"):
        return 3
    if obj.get("is_item") or obj.get("is_corpse"):
        return 4
    return 5 # Other objects (doors, ponds, statues, etc.)
# ---
# --- END NEW HELPER
# ---

def show_room_to_player(player: Player, room: Room):
    """
    Sends all room information (name, desc, objects, exits, players) to the player.
    """
    player.send_message(f"**{room.name}**")
    
    # ---
    # --- MODIFIED: Check DESCRIPTIONS flag
    # ---
    desc_flag = player.flags.get("descriptions", "on")

    if desc_flag == "on":
        # Full dynamic description
        room_descriptions = room.description
        current_time = environment.current_time_of_day # Get current time
        current_weather = environment.current_weather # Get current weather
        
        room_desc_text = _get_dynamic_description(
            room_descriptions, 
            current_time, 
            current_weather
        )
        player.send_message(room_desc_text)

    elif desc_flag == "brief":
        # Brief description, with fallback to default
        room_descriptions = room.description
        brief_desc = room.description.get("brief")
        
        if not brief_desc:
            # Fallback to default
            brief_desc = room.description.get("default")
            # If default is a dict, get its default
            if isinstance(brief_desc, dict):
                brief_desc = brief_desc.get("default", "A room.")
        
        if isinstance(brief_desc, str):
             player.send_message(brief_desc)
        else:
             player.send_message("A brief room.") # Ultimate fallback

    elif desc_flag == "off":
        # Do not send any description
        pass
    # ---
    # --- END MODIFIED
    # ---
    
    # ---
    # --- THIS IS THE FIX: Object merging logic is now here.
    # ---
    world = player.world
    merged_objects = []
    # Get the raw stubs from the room's db_data
    all_objects_stubs = room.db_data.get("objects", []) 
    
    # Get a reference to the stubs list in the *cache* to update UIDs
    room_data_in_cache = world.game_rooms.get(room.room_id, {})
    all_objects_stubs_in_cache = room_data_in_cache.get("objects", [])
    
    # A safer way to map, just in case
    # This maps the *string representation* of a stub to its *cache instance*
    cache_stubs_by_content = {}
    if all_objects_stubs_in_cache:
        cache_stubs_by_content = {str(s): s for s in all_objects_stubs_in_cache}


    if all_objects_stubs:
        for obj_stub in all_objects_stubs: # obj is a dict (a stub) in the list
            node_id = obj_stub.get("node_id")
            monster_id = obj_stub.get("monster_id")
            
            # Find the corresponding stub in the cache to update it
            obj_stub_in_cache = cache_stubs_by_content.get(str(obj_stub))

            # 1. Is it a node?
            if node_id:
                template = world.game_nodes.get(node_id)
                if template:
                    merged_obj = copy.deepcopy(template)
                    merged_obj.update(obj_stub) 
                    if "uid" not in merged_obj:
                         merged_obj["uid"] = uuid.uuid4().hex
                         if obj_stub_in_cache:
                            obj_stub_in_cache["uid"] = merged_obj["uid"] # Save UID
                    merged_objects.append(merged_obj)
            
            # 2. Is it a monster/NPC stub?
            elif monster_id:
                uid = obj_stub.get("uid")
                if not uid:
                    uid = uuid.uuid4().hex
                    if obj_stub_in_cache:
                        obj_stub_in_cache["uid"] = uid # Save UID back to the stub in cache
                
                if uid and world.get_defeated_monster(uid) is not None:
                    continue # It's defeated, skip it
                
                template = world.game_monster_templates.get(monster_id)
                if template:
                    merged_obj = copy.deepcopy(template)
                    merged_obj.update(obj_stub) # Apply instance vars (like the UID)
                    merged_obj["uid"] = uid # Ensure UID is set
                    merged_objects.append(merged_obj)

            # 3. Is it a simple object (door, corpse, item, etc.)?
            else:
                if obj_stub.get("is_npc") and "uid" not in obj_stub:
                    uid = uuid.uuid4().hex
                    obj_stub["uid"] = uid
                    if obj_stub_in_cache:
                        obj_stub_in_cache["uid"] = uid
                    
                merged_objects.append(obj_stub)
    
    # Now that merging is done, we overwrite the room's object list
    # with the live, merged data for the rest of this function.
    room.objects = merged_objects
    # ---
    # --- END FIX
    # ---
    
    # --- Skill-Based Object Perception ---
    player_perception = player.stats.get("WIS", 0)
    
    # ---
    # --- THIS IS THE NEW SORTING FIX
    # ---
    # Sort the objects list before displaying it
    if room.objects:
        room.objects.sort(key=lambda obj: (
            _get_object_sort_priority(obj), 
            obj.get("name", "z") # Secondary sort by name
        ))
    # ---
    # --- END SORTING FIX
    # ---
    
    # 1. Show Objects
    # --- MODIFIED: Iterate over room.objects (which is now pre-merged) ---
    if room.objects:
        html_objects = []
        for obj in room.objects:
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

# ---
# --- NEW: FUNCTION MOVED FROM command_executor.py
# ---
def _get_map_data(player: Player, world: 'World') -> Dict[str, Any]:
    """
    Builds a dictionary of map data for all rooms the player has visited.
    """
    map_data = {}
    for room_id in player.visited_rooms:
        # Use world.get_room to get the raw data from cache
        room = world.game_rooms.get(room_id)
        if room:
            # Extract only what the client needs
            special_exits = []
            for obj in room.get("objects", []):
                verb = None
                target_room = obj.get("target_room")
                
                if not target_room:
                    continue
                    
                if "ENTER" in obj.get("verbs", []):
                    verb = "ENTER"
                elif "CLIMB" in obj.get("verbs", []):
                    verb = "CLIMB"
                elif "EXIT" in obj.get("verbs", []):
                    verb = "EXIT" # e.g., "out"
                
                if verb:
                    special_exits.append({
                        "name": obj.get("name", "door"),
                        "target_room": target_room,
                        "verb": verb
                    })

            map_data[room_id] = {
                "room_id": room.get("room_id"),
                "name": room.get("name"),
                "x": room.get("x"), # Will be None if not set
                "y": room.get("y"),
                "z": room.get("z"),
                "interior_id": room.get("interior_id"), # Add this line
                "exits": room.get("exits", {}),
                "special_exits": special_exits
            }
    return map_data
# ---
# --- END MOVED FUNCTION
# ---

# ---
# --- NEW: FUNCTION MOVED FROM app.py
# ---
def _handle_npc_idle_dialogue(world: 'World', player_name: str, room_id: str):
    """
    Waits a random time, then checks for NPCs and sends idle quest prompts.
    This is run in a background thread by socketio.
    """
    try:
        delay = random.randint(3, 10)
        world.socketio.sleep(delay)

        player_obj = world.get_player_obj(player_name.lower())
        if not player_obj:
            return 

        if player_obj.current_room_id != room_id:
            return 

        room_data = world.game_rooms.get(room_id)
        if not room_data:
            return
            
        npcs = []
        for obj in room_data.get("objects", []):
            if obj.get("quest_giver_ids") and not obj.get("is_monster"):
                npcs.append(obj)
        
        if not npcs:
            return
            
        for npc in npcs:
            npc_quest_ids = npc.get("quest_giver_ids", [])
            active_quest = get_active_quest_for_npc(player_obj, npc_quest_ids)
            
            if active_quest:
                idle_prompt = active_quest.get("idle_prompt")
                give_target = active_quest.get("give_target_name")
                
                # NEW CHECK: Don't say the idle prompt if this NPC is just the item receiver
                if idle_prompt:
                    is_just_receiver = (give_target and give_target == npc.get("name", "").lower())
                    
                    if not is_just_receiver:
                        if player_obj.current_room_id == room_id:
                            npc_name = npc.get("name", "Someone")
                            world.send_message_to_player(
                                player_name.lower(),
                                f"The {npc_name} says, \"{idle_prompt}\"",
                                "message"
                            )
                            return # Only one idle prompt per room
                        
    except Exception as e:
        print(f"[IDLE_DIALOGUE_ERROR] Error in _handle_npc_idle_dialogue: {e}")
# ---
# --- END MOVED FUNCTION
# ---