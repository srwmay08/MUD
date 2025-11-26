# mud_backend/core/game_loop/environment.py
import random
import datetime
import pytz 
from typing import TYPE_CHECKING, Optional, Dict, Any

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

from mud_backend import config

# (Module-level state)
current_time_of_day = "mid morning"
current_weather = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear"])[0]
consecutive_clear_checks = 0 

TIME_CYCLE = [
    "dawn", "early morning", "mid morning", "late morning", "noon", 
    "early afternoon", "mid afternoon", "late afternoon", "dusk", 
    "early evening", "mid evening", "late evening", "night", 
    "early night", "midnight", "late night"
]
WEATHER_ORDER = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear", "fog", "rain", "storm"])

def is_room_exposed(room_data):
    if not room_data: return False
    if not isinstance(room_data, dict):
        if hasattr(room_data, 'db_data'):
            room_data = room_data.db_data
        else:
            return False
            
    is_outdoor = room_data.get("is_outdoor", False)
    is_underground = room_data.get("is_underground", False)
    
    return is_outdoor and not is_underground

def _get_time_grouping(time_of_day_str: str) -> str:
    """Categorizes the 16-step time into 5 broad groups."""
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

def _get_time_change_message(new_time: str, new_time_group: str) -> Optional[str]:
    if new_time_group == "DAWN": return "The first faint light of dawn breaks on the eastern horizon."
    if new_time_group == "NOON": return "The sun hangs high in the sky. It is noon."
    if new_time_group == "DUSK": return "The sun dips below the horizon, painting the sky in hues of orange and purple."
    if new_time_group == "MIDNIGHT": return "The hour of midnight passes. The world is still and dark."
    if new_time_group == "MORNING": return "The morning sun climbs higher, burning off the night's chill."
    if new_time_group == "AFTERNOON": return "Long shadows stretch eastward as the afternoon wanes."
    if new_time_group == "EVENING": return "The sky deepens to twilight as the first stars appear."
    if new_time_group == "NIGHT": return "The world grows dark as night settles in."
    return None

def _get_weather_change_message(new_weather: str, old_weather: str) -> Optional[str]:
    if new_weather in ["clear", "light clouds"]:
        if old_weather not in ["clear", "light clouds"]:
            return "The skies begin to clear."
        return None 

    messages = {
        "overcast": "A thick blanket of grey clouds rolls in, hiding the sun.",
        "fog": "A thick, damp fog clings to the ground, muffling all sound.",
        "light rain": "A light, steady rain begins to patter down from the grey sky.",
        "rain": "A steady rain begins to fall, drumming on roofs and turning paths to mud.",
        "heavy rain": "A torrential downpour hammers the land, turning the world into a churning mass of water and noise.",
        "storm": "Dark clouds roil as a fierce storm begins! Lightning flashes, followed by a sharp crack of thunder."
    }
    return messages.get(new_weather)

# --- NEW: Process Periodic Room Ambiance ---
def process_room_periodic_events(world: 'World'):
    """
    Iterates through active rooms and triggers random ambient events.
    """
    # Iterate active rooms safely
    with world.room_directory_lock:
        active_room_ids = list(world.active_rooms.keys())

    for room_id in active_room_ids:
        room = world.get_active_room_safe(room_id)
        if not room or not room.ambient_events: continue
        
        # Iterate through events
        for event in room.ambient_events:
            if event.get("type") == "periodic":
                chance = event.get("chance", 0.05)
                if random.random() < chance:
                    message = event.get("message")
                    if message:
                        world.broadcast_to_room(room_id, message, "ambient")
                    # Trigger only one per tick per room to avoid spam? 
                    # Or check all. Let's break after one to be safe.
                    break

# --- NEW: Trigger Room Time Events ---
def trigger_room_time_events(world: 'World', new_time_group: str):
    """
    Iterates through active rooms and triggers specific time-based events.
    """
    with world.room_directory_lock:
        active_room_ids = list(world.active_rooms.keys())

    for room_id in active_room_ids:
        room = world.get_active_room_safe(room_id)
        if not room or not room.ambient_events: continue
        
        for event in room.ambient_events:
            if event.get("type") == "time":
                if event.get("time") == new_time_group:
                    message = event.get("message")
                    if message:
                        world.broadcast_to_room(room_id, message, "ambient")

def update_environment_state(world: 'World',
                             game_tick_counter: int, 
                             active_players_dict: Dict[str, Any], 
                             log_time_prefix: str, 
                             broadcast_callback: Any):
    
    game_rooms_dict = world.game_rooms
    global current_time_of_day, current_weather, consecutive_clear_checks

    time_change_interval = getattr(config, 'TIME_CHANGE_INTERVAL_TICKS', 12) 
    weather_change_interval = getattr(config, 'WEATHER_CHANGE_INTERVAL_TICKS', 10)

    time_changed_this_tick = False
    weather_changed_this_tick = False
    old_time = current_time_of_day
    old_weather = current_weather

    # --- Update Time of Day ---
    if game_tick_counter > 0 and game_tick_counter % time_change_interval == 0:
        current_time_index = TIME_CYCLE.index(current_time_of_day)
        current_time_of_day = TIME_CYCLE[(current_time_index + 1) % len(TIME_CYCLE)]
        time_changed_this_tick = True

    # --- Update Weather ---
    if game_tick_counter > 0 and game_tick_counter % weather_change_interval == 0:
        roll = random.random()
        new_weather_candidate = old_weather
        current_weather_idx = WEATHER_ORDER.index(old_weather)
        
        if old_weather == WEATHER_ORDER[0]: 
            current_worsen_chance = min(
                getattr(config, 'WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE', 0.75),
                getattr(config, 'WEATHER_WORSEN_FROM_CLEAR_START_CHANCE', 0.10) + (consecutive_clear_checks * getattr(config, 'WEATHER_WORSEN_ESCALATION', 0.03))
            )
            if roll < current_worsen_chance:
                if len(WEATHER_ORDER) > 1:
                    worsen_options = WEATHER_ORDER[1:min(3, len(WEATHER_ORDER))] 
                    new_weather_candidate = random.choice(worsen_options) if worsen_options else WEATHER_ORDER[1]
                consecutive_clear_checks = 0 
            else:
                new_weather_candidate = old_weather
                consecutive_clear_checks += 1
        else:
            consecutive_clear_checks = 0 
            improve_chance = getattr(config, 'WEATHER_IMPROVE_BASE_CHANCE', 0.50)
            stay_same_chance = getattr(config, 'WEATHER_STAY_SAME_BAD_CHANCE', 0.40)
            if roll < improve_chance and current_weather_idx > 0:
                new_weather_candidate = WEATHER_ORDER[current_weather_idx - 1]
            elif roll < improve_chance + stay_same_chance and current_weather_idx < len(WEATHER_ORDER):
                new_weather_candidate = old_weather
            else:
                if current_weather_idx < len(WEATHER_ORDER) - 1:
                    new_weather_candidate = WEATHER_ORDER[current_weather_idx + 1]
                else: 
                    new_weather_candidate = old_weather
        
        if new_weather_candidate != old_weather:
            current_weather = new_weather_candidate
            weather_changed_this_tick = True

    # 1. Broadcast Global Messages
    time_broadcast_msg = None
    if time_changed_this_tick:
        old_time_group = _get_time_grouping(old_time)
        new_time_group = _get_time_grouping(current_time_of_day)
        
        if old_time_group != new_time_group:
            time_broadcast_msg = _get_time_change_message(current_time_of_day, new_time_group)
            # --- NEW: Trigger Room Specific Time Events ---
            trigger_room_time_events(world, new_time_group)
            # --- END NEW ---

    weather_broadcast_msg = None
    if weather_changed_this_tick:
        weather_broadcast_msg = _get_weather_change_message(current_weather, old_weather)

    if time_broadcast_msg or weather_broadcast_msg:
        exposed_room_ids = set()
        for room_id, room_data in game_rooms_dict.items():
            if is_room_exposed(room_data):
                exposed_room_ids.add(room_id)
        
        for player_name, player_data in active_players_dict.items():
            player_obj = player_data 
            if player_obj and player_obj.current_room_id in exposed_room_ids:
                if player_obj.game_state != "playing": continue 
                
                if time_broadcast_msg:
                    player_obj.world.send_message_to_player(player_name, time_broadcast_msg, "message")
                if weather_broadcast_msg:
                    player_obj.world.send_message_to_player(player_name, weather_broadcast_msg, "message")