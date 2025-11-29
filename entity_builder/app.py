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

@app.route('/')
def index():
    return render_template('entity_builder.html')

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

    # 1. GLOBAL DATA (In /data/global/)
    # We just list everything in global as editable files
    scan(GLOBAL_DIR, "*.json", "global")

    # 2. ASSETS (In /data/assets/)
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
    """
    Returns lists of IDs for autocomplete.
    Scans the new directory structure to find them.
    """
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
                # Handle list of dicts
                if isinstance(data, list):
                    refs["skills"] = [s.get("skill_id") for s in data if "skill_id" in s]
                # Handle dict of dicts
                elif isinstance(data, dict):
                     refs["skills"] = list(data.keys())
        except: pass

    # 2. Factions (Global)
    faction_path = os.path.join(GLOBAL_DIR, "faction.json")
    if os.path.exists(faction_path):
        try:
            with open(faction_path, 'r') as f:
                data = json.load(f)
                # Structure: { "factions": { "Name": ... } }
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
    
    # Sort for UI
    for k in refs: 
        if k != "slots": refs[k].sort()

    return jsonify(refs)

@app.route('/api/load', methods=['GET'])
def load_file():
    filename = request.args.get('file')
    if not filename: return jsonify({"error": "No filename"}), 400
    
    # filename comes in relative to DATA_DIR (e.g. "global/skills.json")
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
        # Create backup
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