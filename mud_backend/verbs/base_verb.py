# mud_backend/verbs/base_verb.py
from mud_backend.core.game_objects import Player, Room 
from typing import List, TYPE_CHECKING, Dict, Any, Optional
from mud_backend.core.room_handler import hydrate_room_objects
from mud_backend.core.utils import find_object_by_keyword_or_id

if TYPE_CHECKING:
    from mud_backend.core.game_state import World

class BaseVerb:
    """
    Base class for all in-game commands (Verbs).
    All verbs must override the execute method.
    """
    
    def __init__(self, world: 'World', player: Player, room: Room, args: List[str], command: str = ""):
        self.world = world
        self.player = player
        self.room = room
        self.args = args
        self.command = command

        # Ensure room objects are fully hydrated so commands like 'go table' 
        # can find the correct keywords and verbs.
        if self.room:
             hydrate_room_objects(self.room, self.world)
 
    def execute(self):
        """
        The main logic for the verb. 
        This method must be implemented by all derived classes.
        It should update the player or room state and use 
        self.player.send_message() to send output to the player.
        """
        raise NotImplementedError("The execute method must be overridden by the derived verb class.")

    def find_target(self, search_term: str, search_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Wrapper to find an object in a list using ID (#uuid) or Name.
        Usage in subclasses:
            target = self.find_target(self.args[0], self.room.objects)
        """
        return find_object_by_keyword_or_id(search_term, search_list)