# mud_backend/verbs/ping.py
from mud_backend.verbs.base_verb import BaseVerb

class Ping(BaseVerb):
    """
    Handles the 'ping' command.
    This is a silent command sent by the client's game loop
    to trigger the server-side game tick.
    It produces no output.
    """
    
    def execute(self):
        # Do nothing.
        # The game tick logic will have already run
        # inside command_executor before this verb was called.
        pass