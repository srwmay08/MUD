# mud_backend/core/events.py
from collections import defaultdict
from typing import Callable, List, Dict, Any

class EventBus:
    """
    A simple, synchronous event bus to decouple Game Logic from Quest/Scripting triggers.
    """
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable):
        """
        Registers a callback function for a specific event type.
        Callback must accept **kwargs.
        """
        self.subscribers[event_type].append(callback)

    def emit(self, event_type: str, **kwargs):
        """
        Trigger an event. All subscribers are called with the provided kwargs.
        """
        # Debug log for critical events could go here
        # if event_type not in ["tick"]: print(f"[EVENT] {event_type} triggered: {kwargs}")
        
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                try:
                    callback(**kwargs)
                except Exception as e:
                    print(f"[EVENT BUS ERROR] Error handling '{event_type}': {e}")
                    import traceback
                    traceback.print_exc()