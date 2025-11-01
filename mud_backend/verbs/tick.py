# mud_backend/verbs/tick.py
from mud_backend.verbs.base_verb import BaseVerb

class Tick(BaseVerb):
    """
    Handles the 'ping' command from the client.
    This is a silent verb that does nothing on its own.
    Its only purpose is to trigger the _check_and_run_game_tick 
    function in the command_executor.
    """
    
    def execute(self):
        # Do nothing.
        # The game tick logic will have already run
        # inside command_executor before this verb was called.
        pass