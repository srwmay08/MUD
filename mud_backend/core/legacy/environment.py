# mud_project/game_logic/environment.py
import random
import datetime
import pytz 

try:
    import config
except ImportError as e:
    print(f"ERROR (environment.py): Failed to import 'config'. {e}")
    # Basic fallback for essential attributes if config fails to load
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

# --- Module-level state for environment ---
current_time_of_day = "day"
current_weather = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear"])[0] # Start with the best weather
consecutive_clear_checks = 0 # How many times weather check occurred while 'clear' and it stayed 'clear'

TIME_CYCLE = ["dawn", "day", "dusk", "night"]
WEATHER_ORDER = getattr(config, 'WEATHER_SEVERITY_ORDER', ["clear", "fog", "rain", "snow", "storm"])
# --- End Module-level state ---

def is_room_exposed(room_data):
    if not room_data: return False
    is_outdoor = room_data.get("is_outdoor", False)
    is_underground = room_data.get("is_underground", False)
    return is_outdoor and not is_underground

def get_description_for_room(room_data):
    global current_time_of_day, current_weather

    if not room_data: return "A featureless void."
    base_description = room_data.get("description", "No description available.")

    if is_room_exposed(room_data):
        # Check for specific, pre-written descriptions based on current weather first
        if current_weather == "storm" and "description_storm" in room_data: return room_data["description_storm"]
        if current_weather == "blizzard" and "description_blizzard" in room_data: return room_data["description_blizzard"] # Example
        if current_weather == "heavy rain" and "description_heavy_rain" in room_data: return room_data["description_heavy_rain"]
        if current_weather == "heavy snow" and "description_heavy_snow" in room_data: return room_data["description_heavy_snow"]
        if current_weather == "rain" and "description_rain" in room_data: return room_data["description_rain"]
        if current_weather == "snow" and "description_snow" in room_data: return room_data["description_snow"]
        if current_weather == "light rain" and "description_light_rain" in room_data: return room_data["description_light_rain"]
        if current_weather == "light snow" and "description_light_snow" in room_data: return room_data["description_light_snow"]
        if current_weather == "fog" and "description_fog" in room_data: return room_data["description_fog"]
        if current_weather == "overcast" and "description_overcast" in room_data: return room_data["description_overcast"]
        if current_weather == "light clouds" and "description_light_clouds" in room_data: return room_data["description_light_clouds"]
        
        # Then check for time-specific descriptions if no weather-specific one matched
        if current_time_of_day == "night" and "description_night" in room_data: return room_data["description_night"]
        if current_time_of_day == "dusk" and "description_dusk" in room_data: return room_data["description_dusk"]
        if current_time_of_day == "dawn" and "description_dawn" in room_data: return room_data["description_dawn"]
        
        # Fallback to appending generic descriptive text
        descriptive_additions = []
        
        # Time of day text
        if current_time_of_day == "night":
            descriptive_additions.append("It is dark.")
            if current_weather == "clear": descriptive_additions.append("The stars are brilliant above.")
        elif current_time_of_day == "dusk":
            descriptive_additions.append("The sun dips low, painting the sky in fading colors.")
        elif current_time_of_day == "dawn":
            descriptive_additions.append("The first light of dawn touches the land.")
        elif current_time_of_day == "day" and current_weather == "clear":
             descriptive_additions.append("The sun shines brightly.")
        
        # Weather text (only if not "clear" or if clear but no time text was specific enough)
        if current_weather == "light clouds": descriptive_additions.append("A few fluffy clouds drift lazily across the sky.")
        elif current_weather == "overcast": descriptive_additions.append("The sky is grey and overcast.")
        elif current_weather == "fog": descriptive_additions.append("A thick fog clings to everything, muffling sounds.")
        elif current_weather == "light rain": descriptive_additions.append("A light drizzle falls.")
        elif current_weather == "rain": descriptive_additions.append("Rain falls steadily.")
        elif current_weather == "heavy rain": descriptive_additions.append("Heavy rain pours down, soaking everything.")
        elif current_weather == "light snow": descriptive_additions.append("Light snowflakes dance in the air.")
        elif current_weather == "snow": descriptive_additions.append("Snow falls, blanketing the ground.")
        elif current_weather == "heavy snow": descriptive_additions.append("Heavy snow falls, quickly accumulating.")
        elif current_weather == "storm": descriptive_additions.append("A fierce storm rages, with lashing rain and howling winds!")
        elif current_weather == "blizzard": descriptive_additions.append("A blinding blizzard howls, whipping snow into a frenzy!")
        
        if descriptive_additions:
            return base_description + " " + " ".join(descriptive_additions)
        return base_description 
    else: # Indoors or shielded underground
        return base_description

def update_environment_state(game_tick_counter, active_players_dict, game_rooms_dict, log_time_prefix, broadcast_callback):
    global current_time_of_day, current_weather, consecutive_clear_checks

    time_change_interval = getattr(config, 'TIME_CHANGE_INTERVAL_TICKS', 20) 
    weather_change_interval = getattr(config, 'WEATHER_CHANGE_INTERVAL_TICKS', 15)

    time_changed_this_tick = False
    weather_changed_this_tick = False
    old_time = current_time_of_day
    old_weather = current_weather

    # --- Update Time of Day ---
    if game_tick_counter > 0 and game_tick_counter % time_change_interval == 0:
        current_time_index = TIME_CYCLE.index(current_time_of_day)
        current_time_of_day = TIME_CYCLE[(current_time_index + 1) % len(TIME_CYCLE)]
        time_changed_this_tick = True
        if config.DEBUG_MODE: 
            print(f"{log_time_prefix} - ENV_SYSTEM: Time shifted from {old_time} to {current_time_of_day}")

    # --- Update Weather ---
    if game_tick_counter > 0 and game_tick_counter % weather_change_interval == 0:
        stay_clear_base = getattr(config, 'WEATHER_STAY_CLEAR_BASE_CHANCE', 0.65)
        worsen_from_clear_start = getattr(config, 'WEATHER_WORSEN_FROM_CLEAR_START_CHANCE', 0.10)
        worsen_escalation = getattr(config, 'WEATHER_WORSEN_ESCALATION', 0.03)
        max_worsen_chance = getattr(config, 'WEATHER_MAX_WORSEN_FROM_CLEAR_CHANCE', 0.75)
        improve_base = getattr(config, 'WEATHER_IMPROVE_BASE_CHANCE', 0.50)
        stay_same_bad = getattr(config, 'WEATHER_STAY_SAME_BAD_CHANCE', 0.40)

        roll = random.random()
        new_weather_candidate = old_weather # Default to no change

        current_weather_idx = WEATHER_ORDER.index(old_weather)

        if old_weather == WEATHER_ORDER[0]: # If current weather is "clear" (best weather)
            current_worsen_chance = min(max_worsen_chance, worsen_from_clear_start + (consecutive_clear_checks * worsen_escalation))
            
            if roll < current_worsen_chance: # Worsen from clear
                # Typically worsens by one step, but could be more dramatic occasionally
                if len(WEATHER_ORDER) > 1:
                    # Pick from the next 1 or 2 worse states
                    worsen_options = WEATHER_ORDER[1:min(3, len(WEATHER_ORDER))] 
                    new_weather_candidate = random.choice(worsen_options) if worsen_options else WEATHER_ORDER[1]
                consecutive_clear_checks = 0 
            else: # Stays clear
                new_weather_candidate = old_weather
                consecutive_clear_checks += 1
        else: # Current weather is not "clear"
            consecutive_clear_checks = 0 # Reset this counter
            
            if roll < improve_base and current_weather_idx > 0: # Improve
                new_weather_candidate = WEATHER_ORDER[current_weather_idx - 1]
            elif roll < improve_base + stay_same_bad and current_weather_idx < len(WEATHER_ORDER): # Stay the same
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


    # --- Broadcast Ambient Messages ---
    time_message_str = ""
    if time_changed_this_tick:
        # More descriptive time changes
        if current_time_of_day == "dusk": time_message_str = "The sun begins its descent, painting the sky with hues of orange and purple. Evening approaches."
        elif current_time_of_day == "night": time_message_str = "Darkness blankets the land as night takes hold."
        elif current_time_of_day == "dawn": time_message_str = "The first faint light of dawn breaks on the eastern horizon."
        elif current_time_of_day == "day" and old_time == "dawn": time_message_str = "The sun rises fully, bathing the world in the light of a new day."
    
    weather_message_str = ""
    if weather_changed_this_tick:
        # More descriptive weather changes
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
                if time_message_str: # Send as separate messages for clarity
                    p_obj.add_message(time_message_str, "ambient_time")
                if weather_message_str:
                    p_obj.add_message(weather_message_str, "ambient_weather")

def get_current_time_of_day_str():
    return current_time_of_day

def get_current_weather_str():
    return current_weather

if config.DEBUG_MODE:
    print("game_logic.environment loaded with dynamic weather.")