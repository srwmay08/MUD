# mud_backend/core/game_loop/environment.py
import random
import datetime
import pytz 

# (MockConfig and imports... no changes needed here)
class MockConfig:
    DEBUG_MODE = True
    TIME_CHANGE_INTERVAL_TICKS = 20
    WEATHER_CHANGE_INTERVAL_TICKS = 15
    WEATHER_SEVERITY_ORDER = ["clear", "light clouds", "overcast", "fog", 
                              "light rain", "rain", "heavy rain", "storm"]
    WEATHER_STAY_CLEAR_BASE_CHANCE = 0.65
    WEATHER_WORSEN_FROM_CLEAR_START_CHANCE = 0.10
    WEATHER_WORSEN_ESCALATION = 0.03
    WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE = 0.75
    WEATHER_IMPROVE_BASE_CHANCE = 0.50
    WEATHER_STAY_SAME_BAD_CHANCE = 0.40
config = MockConfig()

try:
    from mud_backend.core import game_state
except ImportError:
    print("ERROR (environment.py): Failed to import 'game_state'. Using mock.")
    class MockGameState:
        GAME_ROOMS = {}
    game_state = MockGameState()

# (Module-level state... no changes)
current_time_of_day = "day"
current_weather = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear"])[0]
consecutive_clear_checks = 0 
TIME_CYCLE = ["dawn", "day", "dusk", "night"]
WEATHER_ORDER = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear", "fog", "rain", "snow", "storm"])

# (is_room_exposed... no changes)
def is_room_exposed(room_data):
    if not room_data: return False
    is_outdoor = room_data.get("is_outdoor", False)
    is_underground = room_data.get("is_underground", False)
    return is_outdoor and not is_underground

# (get_description_for_room... no changes)
def get_description_for_room(room_data):
    # ... (this function is unchanged)
    global current_time_of_day, current_weather
    if not room_data: return "A featureless void."
    base_description = room_data.get("description", "No description available.")
    # ... (all the logic for checking weather/time descriptions) ...
    return base_description # (or base_description + additions)


def update_environment_state(game_tick_counter, 
                             active_players_dict, 
                             log_time_prefix, 
                             broadcast_callback): # <-- We will now use this
    
    game_rooms_dict = game_state.GAME_ROOMS
    
    global current_time_of_day, current_weather, consecutive_clear_checks

    time_change_interval = getattr(config, 'TIME_CHANGE_INTERVAL_TICKS', 20) 
    weather_change_interval = getattr(config, 'WEATHER_CHANGE_INTERVAL_TICKS', 15)

    time_changed_this_tick = False
    weather_changed_this_tick = False
    old_time = current_time_of_day
    old_weather = current_weather

    # --- Update Time of Day ---
    # This check will now work correctly
    if game_tick_counter > 0 and game_tick_counter % time_change_interval == 0:
        current_time_index = TIME_CYCLE.index(current_time_of_day)
        current_time_of_day = TIME_CYCLE[(current_time_index + 1) % len(TIME_CYCLE)]
        time_changed_this_tick = True
        if config.DEBUG_MODE: 
            print(f"{log_time_prefix} - ENV_SYSTEM: Time shifted from {old_time} to {current_time_of_day}")

    # --- Update Weather ---
    # This check will now work correctly
    if game_tick_counter > 0 and game_tick_counter % weather_change_interval == 0:
        # (weather change logic is unchanged)
        # ...
        roll = random.random()
        new_weather_candidate = old_weather
        current_weather_idx = WEATHER_ORDER.index(old_weather)
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
            else: # Worsen further (if not already the worst)
                if current_weather_idx < len(WEATHER_ORDER) - 1:
                    new_weather_candidate = WEATHER_ORDER[current_weather_idx + 1]
                else: # Already at worst, stays the same
                    new_weather_candidate = old_weather
        
        if new_weather_candidate != old_weather:
            current_weather = new_weather_candidate
            weather_changed_this_tick = True
            if config.DEBUG_MODE: 
                worsen_info = f" (Worsen chance was {current_worsen_chance:.2f}, {consecutive_clear_checks} clear checks prior)" if old_weather == WEATHER_ORDER[0] else ""
                print(f"{log_time_prefix} - ENV_SYSTEM: Weather changed from {old_weather} to {current_weather}.{worsen_info}")
        # ... (end of weather logic)


    # --- Broadcast Ambient Messages ---
    time_message_str = ""
    if time_changed_this_tick:
        # (message string logic is unchanged)
        if current_time_of_day == "dusk": time_message_str = "The sun begins its descent, painting the sky with hues of orange and purple. Evening approaches."
        elif current_time_of_day == "night": time_message_str = "Darkness blankets the land as night takes hold."
        elif current_time_of_day == "dawn": time_message_str = "The first faint light of dawn breaks on the eastern horizon."
        elif current_time_of_day == "day" and old_time == "dawn": time_message_str = "The sun rises fully, bathing the world in the light of a new day."
    
    weather_message_str = ""
    if weather_changed_this_tick:
        # (message string logic is unchanged)
        if current_weather == "clear": weather_message_str = "The skies clear, revealing brilliant sunshine." if current_time_of_day == "day" else "The skies clear, revealing a canopy of stars."
        elif current_weather == "light clouds": weather_message_str = "A few wispy clouds drift across the sky."
        elif current_weather == "overcast": weather_message_str = "The sky becomes overcast with a thick blanket of grey clouds."
        elif current_weather == "fog": weather_message_str = "A damp fog rolls in, obscuring the distance."
        elif current_weather == "light rain": weather_message_str = "A light rain begins to patter down."
        elif current_weather == "rain": weather_message_str = "Rain starts to fall more steadily."
        elif current_weather == "heavy rain": weather_message_str = "The heavens open and a heavy rain pours down."
        elif current_weather == "light snow": weather_message_str = "Light, fluffy snowflakes begin to dance in the air."
        elif current_weather == "snow": weather_message_str = "Snow begins to fall, covering the ground in a soft white layer."
        elif current_weather == "heavy snow": weather_message_str = "Heavy snow starts to fall, quickly accumulating."
        elif current_weather == "storm": weather_message_str = "Dark clouds roil as a fierce storm begins to brew!"
        elif current_weather == "blizzard": weather_message_str = "The wind howls as a blinding blizzard descends!"


    if time_message_str or weather_message_str:
        for p_obj in active_players_dict.values():
            p_room_data = game_rooms_dict.get(p_obj.current_room_id)
            if p_room_data and is_room_exposed(p_room_data):
                
                # --- THIS IS THE FIX ---
                # Use the broadcast_callback, which knows how to send
                # messages to the player object.
                if time_message_str: 
                    broadcast_callback(p_obj.current_room_id, time_message_str, "ambient_time")
                if weather_message_str:
                    broadcast_callback(p_obj.current_room_id, weather_message_str, "ambient_weather")
                # --- END FIX ---

def get_current_time_of_day_str():
    return current_time_of_day

def get_current_weather_str():
    return current_weather

if config.DEBUG_MODE:
    print("game_logic.environment loaded with dynamic weather.")