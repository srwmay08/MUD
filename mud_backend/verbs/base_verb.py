# mud_backend/verbs/base_verb.py
from mud_backend.core.game_objects import Player, Room 
from typing import List, TYPE_CHECKING

# --- REFACTORED: Add TYPE_CHECKING for World ---
if TYPE_CHECKING:
    from mud_backend.core.game_state import World
# --- END REFACTOR ---

class BaseVerb:
    """
    Base class for all in-game commands (Verbs).
    All verbs must override the execute method.
    """
    
    # --- REFACTORED: Add 'world' to __init__ ---
    def __init__(self, world: 'World', player: Player, room: Room, args: List[str], command: str = ""):
        self.world = world
        self.player = player
        self.room = room
        self.args = args
        self.command = command
    # --- END REFACTOR ---
 
    def execute(self):
        """
        The main logic for the verb. 
        This method must be implemented by all derived classes.
        It should update the player or room state and use 
        self.player.send_message() to send output to the player.
        """
        raise NotImplementedError("The execute method must be overridden by the derived verb class.")