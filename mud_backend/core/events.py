# mud_backend/core/events.py
from collections import defaultdict
from typing import Callable, List, Dict, Any

class EventBus:
    """
    A simple event bus to decouple Game Logic from Persistence/IO.
    """
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable):
        """Registers a callback function for a specific event type."""
        self.subscribers[event_type].append(callback)

    def emit(self, event_type: str, **kwargs):
        """
        Trigger an event. All subscribers are called with the provided kwargs.
        """
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                try:
                    callback(**kwargs)
                except Exception as e:
                    print(f"[EVENT BUS ERROR] Error handling '{event_type}': {e}")
                    import traceback
                    traceback.print_exc()