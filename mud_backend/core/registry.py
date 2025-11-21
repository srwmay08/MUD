# mud_backend/core/registry.py
from typing import Callable, Dict, List, Type, Optional

class VerbRegistry:
    # Stores tuples: (VerbClass, is_admin_only)
    _verbs: Dict[str, Tuple[Type, bool]] = {}
    _aliases: Dict[str, str] = {}

    @classmethod
    def register(cls, aliases: List[str], admin_only: bool = False):
        """
        Decorator to register a verb class.
        Usage: @VerbRegistry.register(["teleport"], admin_only=True)
        """
        def decorator(verb_class):
            if not aliases:
                return verb_class
            
            primary_name = aliases[0].lower()
            # Store the class AND the restriction flag
            cls._verbs[primary_name] = (verb_class, admin_only)
            
            for alias in aliases:
                cls._aliases[alias.lower()] = primary_name
            
            return verb_class
        return decorator

    @classmethod
    def get_verb_info(cls, command_name: str) -> Optional[Tuple[Type, bool]]:
        """Returns (VerbClass, admin_only_bool) or None."""
        primary_name = cls._aliases.get(command_name.lower())
        if primary_name:
            return cls._verbs.get(primary_name)
        return None

    @classmethod
    def get_verb_class(cls, command_name: str) -> Optional[Type]:
        """Returns the verb class associated with a command name or alias."""
        primary_name = cls._aliases.get(command_name.lower())
        if primary_name:
            return cls._verbs.get(primary_name)
        return None

    @classmethod
    def get_all_commands(cls) -> List[str]:
        return list(cls._verbs.keys())