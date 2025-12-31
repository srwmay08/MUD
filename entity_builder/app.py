import os
import sys
import json
import glob
from flask import Flask, render_template, request, jsonify

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Root data directory
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_backend', 'data'))
# Sub-directories
GLOBAL_DIR = os.path.join(DATA_DIR, 'global')
ASSETS_DIR = os.path.join(DATA_DIR, 'assets')
ZONES_DIR = os.path.join(DATA_DIR, 'zones')

STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_frontend', 'static'))
AVD_FILE = os.path.join(GLOBAL_DIR, 'avd.json')

# --- DYNAMIC IMPORT ---
project_root = os.path.abspath(os.path.join(BASE_DIR, '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from mud_backend import config
    EQUIPMENT_SLOTS = list(config.EQUIPMENT_SLOTS.keys())
    print(f"[ENTITY BUILDER] Loaded {len(EQUIPMENT_SLOTS)} slots from config.")
except ImportError:
    print("[ENTITY BUILDER] WARNING: Could not import config. Using fallback slots.")
    EQUIPMENT_SLOTS = ["mainhand", "offhand", "head", "torso", "legs", "feet", "hands", "back"]

app = Flask(__name__, template_folder='.', static_folder=STATIC_DIR)

print(f"[ENTITY BUILDER] Data Root: {DATA_DIR}")

# --- HELPER FUNCTIONS ---
def load_json_file(filepath, default=None):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return default or {}

def save_json_file(filepath, data):
    # Backup
    if os.path.exists(filepath):
        try:
            with open(filepath + ".bak", 'w', encoding='utf-8') as f:
                json.dump(load_json_file(filepath), f, indent=4)
        except: pass
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('entity_builder.html')

@app.route('/api/avd', methods=['GET', 'POST'])
def handle_avd():
    """Handles the AVD global configuration file."""
    if request.method == 'GET':
        data = load_json_file(AVD_FILE, default={
            "armor_types": {},
            "weapon_types": [],
            "avd_table": {},
            "df_table": {}
        })
        return jsonify(data)
    elif request.method == 'POST':
        save_json_file(AVD_FILE, request.json)
        return jsonify({"status": "success", "message": "AVD Tables Saved."})

@app.route('/api/save_entity', methods=['POST'])
def save_entity():
    """Specialized save for weapons vs generic items to structure them correctly."""
    data = request.json
    entity_type = data.get('entity_type')
    entity_data = data.get('data')
    
    if not entity_data or 'id' not in entity_data:
        return jsonify({"error": "Missing Entity Data or ID"}), 400

    # Select file based on type
    if entity_type == 'weapon':
        filepath = os.path.join(ASSETS_DIR, 'items', 'items_weapons.json')
    elif entity_type == 'armor':
        filepath = os.path.join(ASSETS_DIR, 'items', 'items_armor.json')
    else:
        # Default bucket
        filepath = os.path.join(ASSETS_DIR, 'items', 'items_aethels_crossing.json')
        
    current_data = load_json_file(filepath, default={})
    
    # Update logic
    item_id = entity_data.get('id')
    current_data[item_id] = entity_data
    
    save_json_file(filepath, current_data)
    return jsonify({"status": "success", "message": f"Saved {item_id} to {os.path.basename(filepath)}"})


@app.route('/api/files', methods=['GET'])
def list_files():
    """Lists JSON files grouped by category, scanning specific subfolders."""
    categories = {
        "global": [],    # Races, Skills, Factions, Rules
        "monsters": [],
        "items": [],
        "nodes": [],
        "loot": [],
        "spells": [],
        "quests": []
    }
    
    # Helper to scan a specific directory for patterns
    def scan(directory, pattern, category_key):
        if not os.path.exists(directory): return
        for f in glob.glob(os.path.join(directory, "**", pattern), recursive=True):
            # Store path relative to DATA_DIR so the frontend can request it easily
            rel = os.path.relpath(f, DATA_DIR).replace('\\', '/')
            categories[category_key].append(rel)

    # 1. GLOBAL DATA
    scan(GLOBAL_DIR, "*.json", "global")
    # 2. ASSETS
    scan(ASSETS_DIR, "monsters*.json", "monsters")
    scan(ASSETS_DIR, "npcs*.json", "monsters")
    scan(ASSETS_DIR, "items_*.json", "items")
    scan(ASSETS_DIR, "nodes*.json", "nodes")
    scan(ASSETS_DIR, "loot*.json", "loot")
    scan(ASSETS_DIR, "spells*.json", "spells")
    scan(ASSETS_DIR, "quest*.json", "quests")
        
    return jsonify(categories)

@app.route('/api/references', methods=['GET'])
def get_references():
    """Returns lists of IDs for autocomplete."""
    refs = {
        "skills": [],
        "items": [],
        "loot_tables": [],
        "spells": [],
        "factions": [],
        "slots": EQUIPMENT_SLOTS
    }

    # 1. Skills (Global)
    skills_path = os.path.join(GLOBAL_DIR, "skills.json")
    if os.path.exists(skills_path):
        try:
            with open(skills_path, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    refs["skills"] = [s.get("skill_id") for s in data if "skill_id" in s]
                elif isinstance(data, dict):
                     refs["skills"] = list(data.keys())
        except: pass

    # 2. Factions (Global)
    faction_path = os.path.join(GLOBAL_DIR, "faction.json")
    if os.path.exists(faction_path):
        try:
            with open(faction_path, 'r') as f:
                data = json.load(f)
                factions_data = data.get("factions", {})
                refs["factions"] = list(factions_data.keys())
        except: pass

    # 3. Items (Assets)
    for f in glob.glob(os.path.join(ASSETS_DIR, "**", "items_*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["items"].extend(data.keys())
        except: pass

    # 4. Loot Tables (Assets)
    for f in glob.glob(os.path.join(ASSETS_DIR, "**", "loot*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["loot_tables"].extend(data.keys())
        except: pass

    # 5. Spells (Assets)
    for f in glob.glob(os.path.join(ASSETS_DIR, "**", "spells*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["spells"].extend(data.keys())
        except: pass
    
    for k in refs: 
        if k != "slots": refs[k].sort()

    return jsonify(refs)

@app.route('/api/load', methods=['GET'])
def load_file():
    filename = request.args.get('file')
    if not filename: return jsonify({"error": "No filename"}), 400
    
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path): return jsonify({"error": "Not found"}), 404
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        is_dict = isinstance(data, dict)
        return jsonify({"data": data, "is_dict": is_dict})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/save', methods=['POST'])
def save_file():
    payload = request.json
    filename = payload.get('filename')
    data = payload.get('data')
    
    if not filename or data is None: return jsonify({"error": "Missing data"}), 400
    
    path = os.path.join(DATA_DIR, filename)
    
    try:
        if os.path.exists(path):
            with open(path + ".bak", 'w', encoding='utf-8') as f:
                json.dump(json.load(open(path)), f, indent=4)

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("[ENTITY BUILDER] Running on http://localhost:5001")
    app.run(port=5001, debug=True)