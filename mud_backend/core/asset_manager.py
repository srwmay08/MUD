# mud_backend/core/asset_manager.py
from typing import Dict, List, Any, Optional
# REMOVED top-level db import to prevent circular loops

class AssetManager:
    """
    Manages static game data (Assets).
    This class is responsible for loading and caching templates, items, and rules.
    It separates immutable game design data from the mutable World state.
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
        
        # Room templates (Static definitions from DB)
        self.room_templates: Dict[str, Dict[str, Any]] = {}

    def load_all_assets(self):
        """
        Loads all static assets from the database.
        """
        from mud_backend.core import db  # <--- Lazy Import
        
        print("[ASSETS] Loading all room templates...")
        self.room_templates = db.fetch_all_rooms()
        
        print("[ASSETS] Loading all monster templates...")
        self.monster_templates = db.fetch_all_monsters()
        
        print("[ASSETS] Loading all loot tables...")
        self.loot_tables = db.fetch_all_loot_tables()
        
        print("[ASSETS] Loading all items...")
        self.items = db.fetch_all_items()
        
        print("[ASSETS] Loading level table...")
        self.level_table = db.fetch_all_levels()
        
        print("[ASSETS] Loading all skills...")
        self.skills = db.fetch_all_skills()
        
        print("[ASSETS] Loading all criticals...")
        self.criticals = db.fetch_all_criticals()
        
        print("[ASSETS] Loading all quests...")
        self.quests = db.fetch_all_quests()
        
        print("[ASSETS] Loading all nodes...")
        self.nodes = db.fetch_all_nodes()
        
        print("[ASSETS] Loading all factions...")
        self.factions = db.fetch_all_factions()
        
        print("[ASSETS] Loading all spells...")
        self.spells = db.fetch_all_spells()
        
        print("[ASSETS] Data loaded.")

    def get_room_template(self, room_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a room template, handling lazy loading from DB if missing.
        """
        if room_id in self.room_templates:
            return self.room_templates[room_id]
        
        # Fallback: Lazy Load from DB
        from mud_backend.core import db # <--- Lazy Import
        template = db.fetch_room_data(room_id)
        if template and template.get("room_id") != "void":
            self.room_templates[room_id] = template
            return template
            
        return None