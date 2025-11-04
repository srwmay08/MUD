# verbs/base_verb.py
# FIX: Change to absolute import using the top package name
from mud_backend.core.game_objects import Player, Room 
from typing import List, TYPE_CHECKING
# TYPE_CHECKING is used for type hints to avoid circular imports, 
# though not strictly necessary for this simple example.

# if TYPE_CHECKING:
#     from core.command_executor import CommandExecutor # example

class BaseVerb:
    """
    Base class for all in-game commands (Verbs).
    All verbs must override the execute method.
    """
    
    def __init__(self, player: Player, room: Room, args: List[str], command: str = ""):
        self.player = player
        self.room = room
        self.args = args
        self.command = command # <-- NEW: Store the original command
 
    def execute(self):
        """
        The main logic for the verb. 
        This method must be implemented by all derived classes.
        It should update the player or room state and use 
        self.player.send_message() to send output to the player.
        """
        raise NotImplementedError("The execute method must be overridden by the derived verb class.")