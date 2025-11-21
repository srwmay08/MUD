# mud_backend/core/entities.py
from typing import Dict, Any, Optional, List

class GameEntity:
    """
    Base class for all game entities (Players, Mobs, Items, Rooms).
    Standardizes ID handling and property access.
    """
    def __init__(self, uid: str, name: str, template_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        self.uid = uid
        self.name = name
        self.template_id = template_id
        
        # The raw data dictionary (for persistence/properties)
        self.data = data if data is not None else {}
        
        # Common flags
        self.is_player = False
        self.is_npc = False
        self.is_item = False
        self.is_room = False

    @property
    def description(self) -> str:
        return self.data.get("description", "")

    @property
    def keywords(self) -> List[str]:
        return self.data.get("keywords", [])

    def get(self, key: str, default: Any = None) -> Any:
        """Safe access to the underlying data dictionary."""
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access (entity['key']) for backward compatibility."""
        return self.data[key]

    def __setitem__(self, key: str, value: Any):
        """Allow dict-like assignment."""
        self.data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.data
    
    def update(self, other: Dict):
        """Dict-like update."""
        self.data.update(other)

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name} ({self.uid})>"