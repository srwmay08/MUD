# mud_backend/verbs/investigate.py
from mud_backend.verbs.base_verb import BaseVerb
# We just re-use the "Examine" class from the examine.py file
from mud_backend.verbs.examine import Examine

class Investigate(Examine):
    """
    Handles the 'investigate' command.
    This verb is an alias for 'examine' and uses the same logic.
    """
    # By inheriting from Examine, it will run the Examine.execute() method
    pass