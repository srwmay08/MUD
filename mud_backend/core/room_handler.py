# mud_backend/core/room_handler.py
from mud_backend.core.game_objects import Player, Room
# --- NEW IMPORT ---
from mud_backend.core import game_state

def show_room_to_player(player: Player, room: Room):
    """
    Sends all room information (name, desc, objects, exits, players) to the player.
    """
    player.send_message(f"**{room.name}**")
    player.send_message(room.description)
    
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
    
    # --- NEW: Show Other Players ---
    other_players_in_room = []
    for player_name, data in game_state.ACTIVE_PLAYERS.items():
        # Don't show the player themselves
        if player_name.lower() == player.name.lower():
            continue
        
        # If the other player is in this room, add them
        if data["current_room_id"] == room.room_id:
            # Format them as a clickable keyword
            other_players_in_room.append(
                f'<span class="keyword" data-name="{player_name}" data-verbs="look">{player_name}</span>'
            )
            
    if other_players_in_room:
        player.send_message(f"Also here: {', '.join(other_players_in_room)}.")
    # --- END NEW LOGIC ---

    # 2. Show Exits
    if room.exits:
        exit_names = [name.capitalize() for name in room.exits.keys()]
        player.send_message(f"Obvious exits: {', '.join(exit_names)}")