# mud_backend/core/room_handler.py
from mud_backend.core.game_objects import Player, Room
# --- REMOVED: from mud_backend.core import game_state ---
# --- NEW: Import environment module ---
from mud_backend.core.game_loop import environment
# --- END NEW ---

def show_room_to_player(player: Player, room: Room):
    """
    Sends all room information (name, desc, objects, exits, players) to the player.
    """
    player.send_message(f"**{room.name}**")
    player.send_message(room.description)
    
    # --- NEW: Add ambient time/weather description ---
    ambient_desc = environment.get_ambient_description(room.db_data)
    if ambient_desc:
        player.send_message(ambient_desc)
    # --- END NEW ---
    
    # --- Skill-Based Object Perception ---
    player_perception = player.stats.get("WIS", 0)
    
    # 1. Show Objects
    if room.objects:
        html_objects = []
        for obj in room.objects:
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
    
    # --- UPDATED: Show Other Players ---
    other_players_in_room = []
    
    # --- FIX: Get player list from the injected player.world object ---
    # The key is 'sid', the value is 'data'
    for sid, data in player.world.get_all_players_info():
        
        # --- FIX: Get the name from the data value ---
        player_name_in_room = data["player_name"] 

        # Don't show the player themselves
        if player_name_in_room.lower() == player.name.lower():
            continue
        
        # If the other player is in this room, add them
        if data["current_room_id"] == room.room_id:
            other_players_in_room.append(
                f'<span class="keyword" data-name="{player_name_in_room}" data-verbs="look">{player_name_in_room}</span>'
            )
            
    if other_players_in_room:
        player.send_message(f"Also here: {', '.join(other_players_in_room)}.")
    # --- END UPDATED LOGIC ---

    # 2. Show Exits
    if room.exits:
        exit_names = [name.capitalize() for name in room.exits.keys()]
        player.send_message(f"Obvious exits: {', '.join(exit_names)}")