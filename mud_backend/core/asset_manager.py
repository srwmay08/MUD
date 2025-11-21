# mud_backend/core/asset_manager.py
from typing import Dict, List, Any, Optional, Callable

class AssetManager:
    """
    Manages static game data (Assets).
    Refactored to use Dependency Injection for data loading.
    """
    def __init__(self):
        # --- Global Data Caches ---
        self.monster_templates: Dict[str, Dict] = {}
        self.loot_tables: Dict[str, List] = {}
        self.items: Dict[str, Dict] = {}
        self.level_table: List[int] = []
        self.skills: Dict[str, Dict] = {}
        self.criticals: Dict[str, Any] = {}
        self.quests: Dict[str, Any] = {}
        self.nodes: Dict[str, Any] = {} 
        self.factions: Dict[str, Any] = {}
        self.spells: Dict[str, Any] = {}
        self.combat_rules: Dict[str, Any] = {} # <--- NEW
        self.races: Dict[str, Any] = {} # <--- NEW
        
        # Room templates
        self.room_templates: Dict[str, Dict[str, Any]] = {}
        
        # Dependency Injection for lazy loading
        self.room_loader: Optional[Callable[[str], dict]] = None

    def set_room_loader(self, loader_func: Callable[[str], dict]):
        """Injects a function to fetch room data (e.g., db.fetch_room_data)."""
        self.room_loader = loader_func

    def load_all_assets(self, data_source):
        """
        Loads all static assets using the provided data_source interface.
        data_source: The db module or an object matching its interface.
        """
        print("[ASSETS] Loading all room templates...")
        self.room_templates = data_source.fetch_all_rooms()
        
        print("[ASSETS] Loading all monster templates...")
        self.monster_templates = data_source.fetch_all_monsters()
        
        print("[ASSETS] Loading all loot tables...")
        self.loot_tables = data_source.fetch_all_loot_tables()
        
        print("[ASSETS] Loading all items...")
        self.items = data_source.fetch_all_items()
        
        print("[ASSETS] Loading level table...")
        self.level_table = data_source.fetch_all_levels()
        
        print("[ASSETS] Loading all skills...")
        self.skills = data_source.fetch_all_skills()
        
        print("[ASSETS] Loading all criticals...")
        self.criticals = data_source.fetch_all_criticals()
        
        print("[ASSETS] Loading all quests...")
        self.quests = data_source.fetch_all_quests()
        
        print("[ASSETS] Loading all nodes...")
        self.nodes = data_source.fetch_all_nodes()
        
        print("[ASSETS] Loading all factions...")
        self.factions = data_source.fetch_all_factions()
        
        print("[ASSETS] Loading all spells...")
        self.spells = data_source.fetch_all_spells()

        print("[ASSETS] Loading combat rules...")
        self.combat_rules = data_source.fetch_combat_rules()

        print("[ASSETS] Loading all races...")
        self.races = data_source.fetch_all_races() # <--- NEW
        
        print("[ASSETS] Data loaded.")

    def get_room_template(self, room_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a room template, using the injected loader if necessary.
        """
        if room_id in self.room_templates:
            return self.room_templates[room_id]
        
        # Fallback: Use injected loader
        if self.room_loader:
            template = self.room_loader(room_id)
            if template and template.get("room_id") != "void":
                self.room_templates[room_id] = template
                return template
            
        return None