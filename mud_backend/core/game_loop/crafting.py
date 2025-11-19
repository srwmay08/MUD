# mud_backend/core/game_loop/crafting.py
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

# Smelting Constants
MAX_TEMP = 2000
AMBIENT_TEMP = 20
FUEL_BURN_RATE = 5
TEMP_GAIN_PER_FUEL = 10
TEMP_LOSS_RATE = 2 # Base cooling rate

def process_crafting_stations(world: 'World', broadcast_callback):
    """
    Iterates through all rooms and processes any active crafting stations (furnaces).
    This simulates heat, fuel consumption, and chemical reactions.
    """
    
    for room_id, room_data in world.game_rooms.items():
        if not room_data or "objects" not in room_data:
            continue
            
        for obj in room_data["objects"]:
            # Check for Furnace by keyword and state existence
            if obj.get("keywords") and "furnace" in obj.get("keywords") and "state" in obj:
                _process_furnace_tick(obj, room_id, broadcast_callback)

def _process_furnace_tick(furnace: dict, room_id: str, broadcast_callback):
    state = furnace["state"]
    
    # 1. Fuel & Temp Logic
    fuel = state.get("fuel", 0)
    temp = state.get("temp", AMBIENT_TEMP)
    air_flow = state.get("air_flow", 50) # 0-100 (Vent setting)
    
    # Oxygen factor: Open vents = hotter burn but faster fuel usage
    burn_rate = FUEL_BURN_RATE * (0.5 + (air_flow / 100.0))
    
    if fuel > 0:
        # Burn fuel
        consumed = min(fuel, burn_rate)
        state["fuel"] -= consumed
        
        # Temp gain depends on Air Flow
        # Needs air to burn hot
        efficiency = 0.2 + (air_flow / 125.0) 
        temp_gain = consumed * TEMP_GAIN_PER_FUEL * efficiency
        
        temp += temp_gain
    
    # Cooling Logic
    # Cooling is faster if vents are open
    cooling = TEMP_LOSS_RATE * (1.0 + (air_flow / 50.0))
    # Cooling is faster if temp is high (Newton's law approximation)
    cooling += (temp - AMBIENT_TEMP) * 0.05
    
    temp -= cooling
    state["temp"] = max(AMBIENT_TEMP, min(MAX_TEMP, temp))
    
    # 2. Smelting Logic
    # If temp > 1000, ore starts turning to bloom state
    if temp > 1000 and state.get("ore", 0) > 0:
        flux = state.get("flux", 0)
        ore = state.get("ore", 0)
        
        # Consume some ore
        conversion_amt = 10
        if ore >= conversion_amt:
            state["ore"] -= conversion_amt
            
            # Flux reduces slag generation
            slag_generated = 5 # Base slag
            if flux >= conversion_amt:
                state["flux"] -= conversion_amt
                slag_generated = 2 # Reduced slag
            
            state["slag"] = state.get("slag", 0) + slag_generated
            
            # Create 'ready metal' which will become the bloom
            state["ready_metal"] = state.get("ready_metal", 0) + conversion_amt

    # 3. Feedback (Ambient messages for players in the room)
    if random.random() < 0.05 and temp > 500:
        broadcast_callback(room_id, f"The {furnace['name']} rumbles and crackles.", "ambient")