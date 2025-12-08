# mud_backend/core/room_handler.py
import copy
import uuid
import random 
from mud_backend.core.game_objects import Player, Room
from mud_backend.core.game_loop import environment
from typing import Dict, Any, Optional, TYPE_CHECKING
from mud_backend.core.quest_handler import get_active_quest_for_npc

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

def _get_time_grouping(time_of_day_str: str) -> str:
    """Categorizes the 16-step time into 5 broad groups for fallbacks."""
    if time_of_day_str in ["dawn", "noon", "dusk", "midnight"]:
        return time_of_day_str.upper()
    if time_of_day_str in ["early morning", "mid morning", "late morning"]:
        return "MORNING"
    if time_of_day_str in ["early afternoon", "mid afternoon", "late afternoon"]:
        return "AFTERNOON"
    if time_of_day_str in ["early evening", "mid evening", "late evening"]:
        return "EVENING"
    if time_of_day_str in ["night", "early night", "late night"]:
        return "NIGHT"
    return "NIGHT"

def _get_dynamic_description(
    room_descriptions: Any, 
    time_of_day: str, 
    weather: str
) -> str:
    """
    Finds the best matching description from the room's description block.
    """
    if isinstance(room_descriptions, str):
        return room_descriptions
    if not isinstance(room_descriptions, dict):
        return "It is a room. (Description Error)"

    time_key = _get_time_grouping(time_of_day)

    # 1. Specific time
    time_block = room_descriptions.get(time_key)
    if isinstance(time_block, dict):
        desc = time_block.get(weather)
        if desc: return desc
        desc = time_block.get("clear")
        if desc: return desc
            
    # 2. Default time
    default_block = room_descriptions.get("default")
    if isinstance(default_block, dict):
        desc = default_block.get(weather)
        if desc: return desc
        desc = default_block.get("clear")
        if desc: return desc
            
    # 3. Fallback strings
    desc = room_descriptions.get(weather)
    if isinstance(desc, str): return desc
    desc = room_descriptions.get("default")
    if isinstance(desc, str): return desc

    return "You are in a nondescript location."

def _get_object_sort_priority(obj: Dict[str, Any]) -> int:
    """Assigns a numerical priority to objects for sorting."""
    if obj.get("is_npc"): return 1
    if obj.get("is_monster"): return 2
    if obj.get("is_gathering_node"): return 3
    if obj.get("is_item") or obj.get("is_corpse"): return 4
    return 5

def hydrate_room_objects(room: Room, world: 'World'):
    """
    Merges object stubs from the room's DB data with live asset templates (Nodes, Monsters, Items).
    Populates room.objects with fully hydrated dictionaries containing verbs, keywords, etc.
    """
    merged_objects = []
    
    all_objects_stubs = room.data.get("objects", []) 
    
    room_data_in_cache = world.game_rooms.get(room.room_id, {})
    all_objects_stubs_in_cache = room_data_in_cache.get("objects", [])
    
    cache_stubs_by_content = {}
    if all_objects_stubs_in_cache:
        cache_stubs_by_content = {str(s): s for s in all_objects_stubs_in_cache}

    if all_objects_stubs:
        for obj_stub in all_objects_stubs: 
            node_id = obj_stub.get("node_id")
            monster_id = obj_stub.get("monster_id")
            obj_stub_in_cache = cache_stubs_by_content.get(str(obj_stub))

            merged_obj = None

            if node_id:
                template = world.game_nodes.get(node_id)
                if template:
                    merged_obj = copy.deepcopy(template)
                    merged_obj.update(obj_stub) 
                    if "uid" not in merged_obj:
                         merged_obj["uid"] = uuid.uuid4().hex
                         if obj_stub_in_cache: obj_stub_in_cache["uid"] = merged_obj["uid"]
            
            elif monster_id:
                uid = obj_stub.get("uid")
                if not uid:
                    uid = uuid.uuid4().hex
                    if obj_stub_in_cache: obj_stub_in_cache["uid"] = uid
                
                # Check if defeated
                if uid and world.get_defeated_monster(uid) is not None:
                    continue 
                
                template = world.game_monster_templates.get(monster_id)
                if template:
                    merged_obj = copy.deepcopy(template)
                    merged_obj.update(obj_stub) 
                    merged_obj["uid"] = uid 

            else:
                merged_obj = obj_stub
                if obj_stub.get("is_npc") and "uid" not in obj_stub:
                    uid = uuid.uuid4().hex
                    obj_stub["uid"] = uid
                    if obj_stub_in_cache: obj_stub_in_cache["uid"] = uid
            
            # --- FIX: Normalize Verbs to Uppercase ---
            if merged_obj:
                if "verbs" in merged_obj:
                    merged_obj["verbs"] = [v.upper() for v in merged_obj["verbs"]]
                merged_objects.append(merged_obj)
            # -----------------------------------------
    
    room.objects = merged_objects
    
    if room.objects:
        room.objects.sort(key=lambda obj: (_get_object_sort_priority(obj), obj.get("name", "z")))

def show_room_to_player(player: Player, room: Room):
    """
    Sends all room information (name, desc, objects, exits, players) to the player.
    """
    player.send_message(f"**{room.name}**")
    
    desc_flag = player.flags.get("descriptions", "on")

    if desc_flag == "on":
        room_descriptions = room.description
        current_time = environment.current_time_of_day
        current_weather = environment.current_weather
        room_desc_text = _get_dynamic_description(room_descriptions, current_time, current_weather)
        player.send_message(room_desc_text)

    elif desc_flag == "brief":
        brief_desc = room.description.get("brief")
        if not brief_desc:
            brief_desc = room.description.get("default")
            if isinstance(brief_desc, dict):
                brief_desc = brief_desc.get("default", "A room.")
        if isinstance(brief_desc, str):
             player.send_message(brief_desc)
        else:
             player.send_message("A brief room.")

    # Merge objects from DB stubs with live asset templates
    hydrate_room_objects(room, player.world)
    
    player_perception = player.stats.get("WIS", 0)
    
    if room.objects:
        html_objects = []
        for obj in room.objects:
            # --- SKIP HIDDEN OBJECTS OR TABLES ---
            # We skip tables here so they don't clutter the main room view.
            # Players can still interact with them via LOOK TABLES or LOOK <NAME>.
            if obj.get("hidden", False) or obj.get("is_table", False):
                continue
            # -------------------------------------
            
            obj_dc = obj.get("perception_dc", 0)
            if player_perception >= obj_dc:
                obj_name = obj['name'] 
                verbs = obj.get('verbs', ['look', 'examine', 'investigate'])
                verb_str = ','.join(verbs).lower()
                html_objects.append(
                    f'<span class="keyword" data-name="{obj_name}" data-verbs="{verb_str}">{obj_name}</span>'
                )
        if html_objects:
            player.send_message(f"\nObvious objects here: {', '.join(html_objects)}.")
    
    other_players_in_room = []
    for sid, data in player.world.get_all_players_info():
        player_name_in_room = data["player_name"] 
        target_player_obj = data.get("player_obj")
        
        if player_name_in_room.lower() == player.name.lower(): continue
        
        # --- NEW: Invisibility Check ---
        if target_player_obj:
            is_invis = target_player_obj.flags.get("invisible", "off") == "on"
            # If invisible, check if observer is admin
            if is_invis:
                # Use getattr to be safe if you haven't updated Player class yet
                if not getattr(player, "is_admin", False):
                    continue
        # -------------------------------

        if data["current_room_id"] == room.room_id:
            other_players_in_room.append(
                f'<span class="keyword" data-name="{player_name_in_room}" data-verbs="look">{player_name_in_room}</span>'
            )
    if other_players_in_room:
        player.send_message(f"Also here: {', '.join(other_players_in_room)}.")

    # --- NEW: Visibility Outside Tables ---
    if getattr(room, "is_table", False) and "out" in room.exits:
        parent_room_id = room.exits["out"]
        outside_players = []
        for sid, data in player.world.get_all_players_info():
             p_name = data["player_name"]
             if p_name.lower() == player.name.lower(): continue # Skip self
             
             if data["current_room_id"] == parent_room_id:
                 outside_players.append(f'<span class="keyword" data-name="{p_name}" data-verbs="look">{p_name}</span>')
        
        if outside_players:
            player.send_message(f"Outside the booth, you see: {', '.join(outside_players)}.")
    # --------------------------------------

    if room.exits:
        exit_names = []
        for name in room.exits.keys():
            exit_names.append(f'<span class="keyword" data-command="{name}">{name.capitalize()}</span>')
        player.send_message(f"Obvious exits: {', '.join(exit_names)}")


def _get_map_data(player: Player, world: 'World') -> Dict[str, Any]:
    """
    Builds a dictionary of map data for all rooms the player has visited.
    """
    map_data = {}
    for room_id in player.visited_rooms:
        room = world.game_rooms.get(room_id)
        if room:
            special_exits = []
            for obj in room.get("objects", []):
                verb = None
                target_room = obj.get("target_room")
                if not target_room: continue
                if "ENTER" in obj.get("verbs", []): verb = "ENTER"
                elif "CLIMB" in obj.get("verbs", []): verb = "CLIMB"
                elif "EXIT" in obj.get("verbs", []): verb = "EXIT"
                if verb:
                    special_exits.append({
                        "name": obj.get("name", "door"),
                        "target_room": target_room,
                        "verb": verb
                    })

            map_data[room_id] = {
                "room_id": room.get("room_id"),
                "name": room.get("name"),
                "x": room.get("x"), 
                "y": room.get("y"),
                "z": room.get("z"),
                "interior_id": room.get("interior_id"),
                "exits": room.get("exits", {}),
                "special_exits": special_exits
            }
    return map_data

def _handle_npc_idle_dialogue(world: 'World', player_name: str, room_id: str):
    """
    Waits a random time, then checks for NPCs and sends idle quest prompts.
    """
    try:
        delay = random.randint(3, 10)
        world.socketio.sleep(delay)

        player_obj = world.get_player_obj(player_name.lower())
        if not player_obj: return 
        if player_obj.current_room_id != room_id: return 

        room_data = world.game_rooms.get(room_id)
        if not room_data: return
            
        npcs = []
        for obj in room_data.get("objects", []):
            if obj.get("quest_giver_ids") and not obj.get("is_monster"):
                npcs.append(obj)
        
        if not npcs: return
            
        for npc in npcs:
            npc_quest_ids = npc.get("quest_giver_ids", [])
            active_quest = get_active_quest_for_npc(player_obj, npc_quest_ids)
            
            if active_quest:
                idle_prompt = active_quest.get("idle_prompt")
                give_target = active_quest.get("give_target_name")
                grant_item = active_quest.get("grant_item_on_talk")

                if idle_prompt:
                    is_just_receiver = (give_target and give_target == npc.get("name", "").lower())
                    
                    has_grant_item = False
                    if grant_item:
                        if grant_item in player_obj.inventory:
                            has_grant_item = True
                        else:
                            for slot, iid in player_obj.worn_items.items():
                                if iid == grant_item:
                                    has_grant_item = True
                                    break
                    
                    if not is_just_receiver and not has_grant_item:
                        if player_obj.current_room_id == room_id:
                            npc_name = npc.get("name", "Someone")
                            world.send_message_to_player(
                                player_name.lower(),
                                f"The {npc_name} says, \"{idle_prompt}\"",
                                "message"
                            )
                            return 
                        
    except Exception as e:
        print(f"[IDLE_DIALOGUE_ERROR] Error in _handle_npc_idle_dialogue: {e}")