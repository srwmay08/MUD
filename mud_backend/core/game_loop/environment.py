# mud_backend/core/game_loop/environment.py
import random
import datetime
import pytz 
from typing import TYPE_CHECKING # <-- NEW

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
    
    # Let's add a check for town_square explicitly
    if room_data.get("room_id") == "town_square":
        return True # Town square is always exposed
        
    return is_outdoor and not is_underground

# (get_description_for_room... no changes)
def get_description_for_room(room_data):
    # ... (this function is unchanged)
    global current_time_of_day, current_weather
    if not room_data: return "A featureless void."
    base_description = room_data.get("description", "No description available.")
    # ... (all the logic for checking weather/time descriptions) ...
    return base_description # (or base_description + additions)

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
        print(f"{log_time_prefix} - ENV_SYSTEM: Checking for events...")
        print(f"{log_time_prefix} - ENV_SYSTEM: Tick count is {game_tick_counter}.")
        # Check if it's time for a weather event
        is_weather_tick = (game_tick_counter > 0 and game_tick_counter % weather_change_interval == 0)
        print(f"{log_time_prefix} - ENV_SYSTEM: Weather changes every {weather_change_interval} ticks. (Will run: {is_weather_tick})")
        # Check if it's time for a time event
        is_time_tick = (game_tick_counter > 0 and game_tick_counter % time_change_interval == 0)
        print(f"{log_time_prefix} - ENV_SYSTEM: Time changes every {time_change_interval} ticks. (Will run: {is_time_tick})")
    # --- END NEW DEBUGGING BLOCK ---

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
            print(f"{log_time_prefix} - ENV_SYSTEM: Time shifted from {old_time} to {current_time_of_day}")

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
                print(f"{log_time_prefix} - ENV_SYSTEM: Weather changed from {old_weather} to {current_weather}.{worsen_info}")
        else:
             if config.DEBUG_MODE:
                print(f"{log_time_prefix} - ENV_SYSTEM: Weather check rolled, but weather stayed the same: {current_weather}")


    # --- Broadcast Ambient Messages ---
    
    # --- (Time message logic from previous turn) ---
    time_message_str = ""
    if time_changed_this_tick:
        if current_time_of_day == "dawn":
            time_message_str = "The first faint light of dawn breaks on the eastern horizon."
        elif current_time_of_day == "early morning":
            time_message_str = "The sun rises fully, bathing the world in the light of a new morning."
        elif current_time_of_day == "mid morning":
            time_message_str = "The morning sun climbs higher, burning off the last of the night's chill."
        elif current_time_of_day == "late morning":
            time_message_str = "The sun approaches its zenith as the morning wanes."
        elif current_time_of_day == "noon":
            time_message_str = "The sun hangs high in the sky. It is noon."
        elif current_time_of_day == "early afternoon":
            time_message_str = "The heat of the day settles in as the afternoon begins."
        elif current_time_of_day == "mid afternoon":
            time_message_str = "The afternoon sun drifts slowly westward."
        elif current_time_of_day == "late afternoon":
            time_message_str = "Long shadows stretch eastward as the afternoon draws to a close."
        elif current_time_of_day == "dusk":
            time_message_str = "The sun begins its descent, painting the sky with hues of orange and purple. Evening approaches."
        elif current_time_of_day == "early evening":
            time_message_str = "The sky deepens to twilight as the first stars appear."
        elif current_time_of_day == "mid evening":
            time_message_str = "The evening grows darker, and the sounds of the night begin to stir."
        elif current_time_of_day == "late evening":
            time_message_str = "The world is quiet, cloaked in the deep blue of late evening."
        elif current_time_of_day == "night":
            time_message_str = "Darkness blankets the land as night takes hold."
        elif current_time_of_day == "early night":
            time_message_str = "The land is bathed in moonlight as the night truly begins."
        elif current_time_of_day == "midnight":
            time_message_str = "The hour of midnight passes. The world is still and dark."
        elif current_time_of_day == "late night":
            time_message_str = "The deepest part of the night is here, long before the first hint of dawn."
    
    # --- NEW: Time-Dependent Weather Messages ---
    weather_message_str = ""
    if weather_changed_this_tick:
        time_group = _get_time_grouping(current_time_of_day)
        
        if current_weather == "clear":
            if time_group == "dawn_morning":
                weather_message_str = "The morning sky is brilliant and clear."
            elif time_group == "midday":
                weather_message_str = "Not a cloud is in sight under the bright noon sun."
            elif time_group == "afternoon":
                weather_message_str = "The afternoon sky remains clear and blue."
            elif time_group == "evening":
                weather_message_str = "The clear evening sky fades to a deep indigo, revealing a canopy of stars."
            elif time_group == "night":
                weather_message_str = "The night is clear and sharp, the stars brilliant against the blackness."
                
        elif current_weather == "light clouds":
            if time_group == "dawn_morning":
                weather_message_str = "A few wispy clouds drift across the morning sky."
            elif time_group in ["midday", "afternoon"]:
                weather_message_str = "Wisps of white cloud drift lazily across the sky, offering little relief from the sun."
            elif time_group == "evening":
                weather_message_str = "High, thin clouds are stained purple and orange by the setting sun."
            elif time_group == "night":
                weather_message_str = "Thin clouds scud across the face of the moon."
                
        elif current_weather == "overcast":
            if time_group in ["dawn_morning", "midday", "afternoon"]:
                weather_message_str = "The sky becomes overcast with a thick, uniform blanket of grey clouds, hiding the sun."
            elif time_group in ["evening", "night"]:
                weather_message_str = "A low, dark ceiling of clouds blankets the sky, obscuring the stars and moon."
                
        elif current_weather == "fog":
            if time_group == "dawn_morning":
                weather_message_str = "A thick, damp fog rolls in, obscuring the morning light and muffling all sound."
            elif time_group in ["midday", "afternoon"]:
                weather_message_str = "An unnatural fog clings to the ground, cold and damp despite the hour."
            elif time_group in ["evening", "night"]:
                weather_message_str = "A heavy fog descends, swallowing the world in a grey, silent shroud."
                
        elif current_weather == "light rain":
            if time_group in ["dawn_morning", "midday", "afternoon"]:
                weather_message_str = "A light, steady rain begins to patter down from the grey sky."
            elif time_group in ["evening", "night"]:
                weather_message_str = "A cold drizzle begins to fall, slicking the ground and chilling the air."
                
        elif current_weather == "rain":
            if time_group in ["dawn_morning", "midday", "afternoon"]:
                weather_message_str = "A steady rain falls, drumming on roofs and turning the paths to mud."
            elif time_group in ["evening", "night"]:
                weather_message_str = "Rain falls steadily from the black sky, endless and cold."
                
        elif current_weather == "heavy rain":
            if time_group in ["dawn_morning", "midday", "afternoon"]:
                weather_message_str = "The heavens open and a heavy rain pours down, flooding the streets."
            elif time_group in ["evening", "night"]:
                weather_message_str = "A torrential downpour hammers the land, turning the world into a churning mass of water and noise."
                
        elif current_weather == "storm":
            if time_group in ["dawn_morning", "midday", "afternoon"]:
                weather_message_str = "Dark clouds roil as a fierce storm begins! A flash of lightning is followed by a sharp crack of thunder."
            elif time_group in ["evening", "night"]:
                weather_message_str = "The night is torn asunder by a fierce storm! Lightning flashes, illuminating the lashing rain."

    # --- (Broadcast logic... no changes) ---
    if time_message_str or weather_message_str:
        
        # --- FIX: Find unique rooms that need messages ---
        exposed_rooms_with_players = set()
        for p_obj in active_players_dict.values():
            p_room_data = game_rooms_dict.get(p_obj.current_room_id)
            room_is_exposed = p_room_data and is_room_exposed(p_room_data)
            
            if config.DEBUG_MODE:
                room_id_str = p_room_data.get('room_id', 'Unknown') if p_room_data else 'Unknown'
                print(f"{log_time_prefix} - ENV_SYSTEM: Player {p_obj.name} is in room {room_id_str}. Exposed: {room_is_exposed}")
            
            if room_is_exposed:
                exposed_rooms_with_players.add(p_obj.current_room_id)
        
        # --- Now, broadcast ONCE per room ---
        if config.DEBUG_MODE:
            print(f"{log_time_prefix} - ENV_SYSTEM: Broadcasting to unique exposed rooms: {exposed_rooms_with_players}")

        for room_id in exposed_rooms_with_players:
            if time_message_str: 
                broadcast_callback(room_id, time_message_str, "ambient_time")
            if weather_message_str:
                broadcast_callback(room_id, weather_message_str, "ambient_weather")
        # --- END FIX ---
    
    elif config.DEBUG_MODE:
        if game_tick_counter > 0 and (game_tick_counter % weather_change_interval == 0 or game_tick_counter % time_change_interval == 0):
            print(f"{log_time_prefix} - ENV_SYSTEM: Tick event ran, but no new messages were generated.")