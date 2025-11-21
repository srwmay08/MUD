# mud_backend/core/registry.py
from typing import Callable, Dict, List, Type, Optional

class VerbRegistry:
    _verbs: Dict[str, Type] = {}
    _aliases: Dict[str, str] = {}

    @classmethod
    def register(cls, aliases: List[str]):
        """
        Decorator to register a verb class.
        Usage: @VerbRegistry.register(["look", "l", "examine"])
        """
        def decorator(verb_class):
            if not aliases:
                return verb_class
            
            # The first alias is considered the "primary" command name
            primary_name = aliases[0].lower()
            cls._verbs[primary_name] = verb_class
            
            for alias in aliases:
                cls._aliases[alias.lower()] = primary_name
            
            return verb_class
        return decorator

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