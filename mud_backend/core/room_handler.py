# mud_backend/core/room_handler.py
from mud_backend.core.game_objects import Player, Room

def show_room_to_player(player: Player, room: Room):
    """
    Sends all room information (name, desc, objects, exits) to the player.
    This is the new "central" function for looking at a room.
    """
    player.send_message(f"**{room.name}**")
    player.send_message(room.description)
    
    # 1. Show Objects
    if room.objects:
        html_objects = []
        for obj in room.objects:
            obj_name = obj['name']
            verbs = obj.get('verbs', ['look'])
            verb_str = ','.join(verbs).lower()
            html_objects.append(
                f'<span class="keyword" data-name="{obj_name}" data-verbs="{verb_str}">{obj_name}</span>'
            )
        player.send_message(f"\nObvious objects here: {', '.join(html_objects)}.")
    
    # 2. Show Exits
    if room.exits:
        # Capitalize direction names for display
        exit_names = [name.capitalize() for name in room.exits.keys()]
        player.send_message(f"Obvious exits: {', '.join(exit_names)}")