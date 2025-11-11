# mud_backend/core/game_loop/environment.py
import random
import datetime
import pytz 
from typing import TYPE_CHECKING, Optional # <-- NEW

# --- REFACTORED: Import World for type hinting ---
if TYPE_CHECKING:
    from mud_backend.core.game_state import World
# --- END REFACTORED ---

# (MockConfig and imports... no changes needed here)
class MockConfig:
    DEBUG_MODE = True
    TIME_CHANGE_INTERVAL_TICKS = 4
    WEATHER_CHANGE_INTERVAL_TICKS = 3
    WEATHER_SEVERITY_ORDER = ["clear", "light clouds", "overcast", "fog", 
                              "light rain", "rain", "heavy rain", "storm"]
    WEATHER_STAY_CLEAR_BASE_CHANCE = 0.65
    WEATHER_WORSEN_FROM_CLEAR_START_CHANCE = 0.10
    WEATHER_WORSEN_ESCALATION = 0.03
    WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE = 0.75
    WEATHER_IMPROVE_BASE_CHANCE = 0.50
    WEATHER_STAY_SAME_BAD_CHANCE = 0.40
config = MockConfig()

# --- REMOVED: game_state import ---

# (Module-level state... no changes)
current_time_of_day = "mid morning" # Start at a reasonable time
current_weather = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear"])[0]
consecutive_clear_checks = 0 

# --- UPDATED TIME_CYCLE ---
TIME_CYCLE = [
    "dawn", "early morning", "mid morning", "late morning", "noon", 
    "early afternoon", "mid afternoon", "late afternoon", "dusk", 
    "early evening", "mid evening", "late evening", "night", 
    "early night", "midnight", "late night"
]
WEATHER_ORDER = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear", "fog", "rain", "snow", "storm"])

# (is_room_exposed... no changes)
def is_room_exposed(room_data):
    if not room_data: return False
    # --- FIX: Ensure room_data is a dict before .get() ---
    if not isinstance(room_data, dict):
        # This can happen if game_state.GAME_ROOMS contains Room objects
        # instead of dicts, but let's be safe.
        if hasattr(room_data, 'db_data'):
            room_data = room_data.db_data
        else:
            return False
            
    is_outdoor = room_data.get("is_outdoor", False)
    is_underground = room_data.get("is_underground", False)
    
    # --- MODIFIED: Check all town rooms ---
    # (This ensures descriptions appear in all parts of the town)
    # --- FIX: Use getattr to safely access config ---
    if room_data.get("room_id") in getattr(config, 'TOWN_ROOM_IDS', []):
        return True
    # --- END MODIFIED ---
        
    return is_outdoor and not is_underground

# ---
# --- MODIFIED: This function is now the primary way to get ambient descriptions
# ---
def get_ambient_description(room_data) -> Optional[str]:
    """
    Returns a string describing the time and weather *if* the
    room is exposed, otherwise returns None.
    """
    global current_time_of_day, current_weather
    if not room_data or not is_room_exposed(room_data):
        return None

    time_group = _get_time_grouping(current_time_of_day)
    
    # --- Time Description ---
    time_desc = ""
    if time_group == "dawn_morning":
        time_desc = "The morning sun climbs higher, burning off the night's chill."
    elif time_group == "midday":
        time_desc = "The sun hangs high overhead."
    elif time_group == "afternoon":
        time_desc = "Long shadows stretch eastward as the afternoon wanes."
    elif time_group == "evening":
        time_desc = "The sky deepens to twilight as the first stars appear."
    elif time_group == "night":
        time_desc = "The world is dark, lit only by the stars and moon."
    
    if current_time_of_day == "dawn":
        time_desc = "The first faint light of dawn breaks on the eastern horizon."
    elif current_time_of_day == "noon":
        time_desc = "The sun hangs high in the sky. It is noon."
    elif current_time_of_day == "dusk":
        time_desc = "The sun dips below the horizon, painting the sky in hues of orange and purple."
    elif current_time_of_day == "midnight":
        time_desc = "The hour of midnight passes. The world is still and dark."

    # --- Weather Description ---
    weather_desc = ""
    if current_weather == "light clouds":
        weather_desc = "A few wispy clouds drift across the sky."
    elif current_weather == "overcast":
        weather_desc = "A thick, uniform blanket of grey clouds hides the sun."
    elif current_weather == "fog":
        weather_desc = "A thick, damp fog clings to the ground, muffling all sound."
    elif current_weather == "light rain":
        weather_desc = "A light, steady rain patters down from the grey sky."
    elif current_weather == "rain":
        weather_desc = "A steady rain falls, drumming on roofs and turning paths to mud."
    elif current_weather == "heavy rain":
        weather_desc = "A torrential downpour hammers the land, turning the world into a churning mass of water and noise."
    elif current_weather == "storm":
        weather_desc = "Dark clouds roil as a fierce storm rages! Lightning flashes, followed by a sharp crack of thunder."
    
    # Combine them
    if weather_desc:
        return f"{time_desc} {weather_desc}"
    else:
        # Only return a time description if the weather is clear
        return f"{time_desc} The sky is clear."
# --- END MODIFIED FUNCTION ---


# --- REMOVED: get_description_for_room (no longer used) ---

# --- NEW HELPER FUNCTION ---
def _get_time_grouping(time_of_day_str: str) -> str:
    """Categorizes the 16-step time into 5 broad groups."""
    if time_of_day_str in ["dawn", "early morning", "mid morning", "late morning"]:
        return "dawn_morning"
    if time_of_day_str == "noon":
        return "midday"
    if time_of_day_str in ["early afternoon", "mid afternoon", "late afternoon"]:
        return "afternoon"
    if time_of_day_str in ["dusk", "early evening", "mid evening", "late evening"]:
        return "evening"
    if time_of_day_str in ["night", "early night", "midnight", "late night"]:
        return "night"
    return "night" # Default case

# --- REFACTORED: Accept world object ---
def update_environment_state(world: 'World',
                             game_tick_counter, 
                             active_players_dict, 
                             log_time_prefix, 
                             broadcast_callback):
    
    # --- FIX: Get game_rooms from world ---
    game_rooms_dict = world.game_rooms
    
    global current_time_of_day, current_weather, consecutive_clear_checks

    time_change_interval = getattr(config, 'TIME_CHANGE_INTERVAL_TICKS', 20) 
    weather_change_interval = getattr(config, 'WEATHER_CHANGE_INTERVAL_TICKS', 15)

    # --- (Debugging block... no changes) ---
    if config.DEBUG_MODE:
        # ---
        # --- THIS IS THE FIX: Changed log_prefix to log_time_prefix
        # ---
        print(f"{log_time_prefix} - ENV_SYSTEM: Checking for events...")
        print(f"{log_time_prefix} - ENV_SYSTEM: Tick count is {game_tick_counter}.")
        # Check if it's time for a weather event
        is_weather_tick = (game_tick_counter > 0 and game_tick_counter % weather_change_interval == 0)
        print(f"{log_time_prefix} - ENV_SYSTEM: Weather changes every {weather_change_interval} ticks. (Will run: {is_weather_tick})")
        # Check if it's time for a time event
        is_time_tick = (game_tick_counter > 0 and game_tick_counter % time_change_interval == 0)
        print(f"{log_time_prefix} - ENV_SYSTEM: Time changes every {time_change_interval} ticks. (Will run: {is_time_tick})")
    # --- END NEW DEBUGGING BLOCK (AND FIX) ---

    time_changed_this_tick = False
    weather_changed_this_tick = False
    old_time = current_time_of_day
    old_weather = current_weather

    # --- Update Time of Day (no changes) ---
    if game_tick_counter > 0 and game_tick_counter % time_change_interval == 0:
        current_time_index = TIME_CYCLE.index(current_time_of_day)
        current_time_of_day = TIME_CYCLE[(current_time_index + 1) % len(TIME_CYCLE)]
        time_changed_this_tick = True
        if config.DEBUG_MODE: 
            # --- THIS IS THE FIX ---
            print(f"{log_time_prefix} - ENV_SYSTEM: Time shifted from {old_time} to {current_time_of_day}")
            # --- END FIX ---

    # --- Update Weather (no changes) ---
    if game_tick_counter > 0 and game_tick_counter % weather_change_interval == 0:
        roll = random.random()
        new_weather_candidate = old_weather
        current_weather_idx = WEATHER_ORDER.index(old_weather)
        
        # (Using the config variables we defined at the top)
        if old_weather == WEATHER_ORDER[0]: # If current weather is "clear"
            current_worsen_chance = min(config.WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE, config.WEATHER_WORSEN_FROM_CLEAR_START_CHANCE + (consecutive_clear_checks * config.WEATHER_WORSEN_ESCALATION))
            if roll < current_worsen_chance: # Worsen from clear
                if len(WEATHER_ORDER) > 1:
                    worsen_options = WEATHER_ORDER[1:min(3, len(WEATHER_ORDER))] 
                    new_weather_candidate = random.choice(worsen_options) if worsen_options else WEATHER_ORDER[1]
                consecutive_clear_checks = 0 
            else: # Stays clear
                new_weather_candidate = old_weather
                consecutive_clear_checks += 1
        else: # Current weather is not "clear"
            consecutive_clear_checks = 0 
            if roll < config.WEATHER_IMPROVE_BASE_CHANCE and current_weather_idx > 0: # Improve
                new_weather_candidate = WEATHER_ORDER[current_weather_idx - 1]
            elif roll < config.WEATHER_IMPROVE_BASE_CHANCE + config.WEATHER_STAY_SAME_BAD_CHANCE and current_weather_idx < len(WEATHER_ORDER): # Stay the same
                new_weather_candidate = old_weather
            else: # Worsen further
                if current_weather_idx < len(WEATHER_ORDER) - 1:
                    new_weather_candidate = WEATHER_ORDER[current_weather_idx + 1]
                else: 
                    new_weather_candidate = old_weather
        
        if new_weather_candidate != old_weather:
            current_weather = new_weather_candidate
            weather_changed_this_tick = True
            if config.DEBUG_MODE: 
                worsen_info = f" (Worsen chance was {current_worsen_chance:.2f}, {consecutive_clear_checks} clear checks prior)" if old_weather == WEATHER_ORDER[0] else ""
                # --- THIS IS THE FIX ---
                print(f"{log_time_prefix} - ENV_SYSTEM: Weather changed from {old_weather} to {current_weather}.{worsen_info}")
                # --- END FIX ---
        else:
             if config.DEBUG_MODE:
                # --- THIS IS THE FIX ---
                print(f"{log_time_prefix} - ENV_SYSTEM: Weather check rolled, but weather stayed the same: {current_weather}")
                # --- END FIX ---


    # ---
    # --- MODIFIED: All broadcast logic has been removed.
    # --- The global time/weather is now updated, and
    # --- room_handler.py will query it on LOOK/MOVE.
    # ---
    
    if config.DEBUG_MODE:
        if game_tick_counter > 0 and (game_tick_counter % weather_change_interval == 0 or game_tick_counter % time_change_interval == 0):
            if not time_changed_this_tick and not weather_changed_this_tick:
                # --- THIS IS THE FIX ---
                print(f"{log_time_prefix} - ENV_SYSTEM: Tick event ran, but no new messages were generated.")
                # --- END FIX ---