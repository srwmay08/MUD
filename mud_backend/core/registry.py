# mud_backend/core/registry.py
from typing import Callable, Dict, List, Type, Optional, Tuple

class VerbRegistry:
    # Stores tuples: (VerbClass, is_admin_only)
    _verbs: Dict[str, Tuple[Type, bool]] = {}
    _aliases: Dict[str, str] = {}

    @classmethod
    def register(cls, aliases: List[str], admin_only: bool = False):
        """
        Decorator to register a verb class.
        Usage: @VerbRegistry.register(["look", "l", "examine"])
        Usage: @VerbRegistry.register(["teleport"], admin_only=True)
        """
        def decorator(verb_class):
            if not aliases:
                return verb_class
            
            # The first alias is considered the "primary" command name
            primary_name = aliases[0].lower()
            
            # Store the class AND the restriction flag
            cls._verbs[primary_name] = (verb_class, admin_only)
            
            for alias in aliases:
                cls._aliases[alias.lower()] = primary_name
            
            return verb_class
        return decorator

    @classmethod
    def get_verb_info(cls, command_name: str) -> Optional[Tuple[Type, bool]]:
        """
        Returns the verb class and its admin_only flag.
        Returns: (VerbClass, is_admin_only) or None
        """
        primary_name = cls._aliases.get(command_name.lower())
        if primary_name:
            return cls._verbs.get(primary_name)
        return None

    @classmethod
    def get_verb_class(cls, command_name: str) -> Optional[Type]:
        """
        Backward compatibility: Returns just the class.
        """
        info = cls.get_verb_info(command_name)
        if info:
            return info[0]
        return None

    @classmethod
    def get_all_commands(cls) -> List[str]:
        return list(cls._verbs.keys())