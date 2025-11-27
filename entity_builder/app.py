import os
import json
import glob
from flask import Flask, render_template, request, jsonify

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_backend', 'data'))
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_frontend', 'static'))

app = Flask(__name__, template_folder='.', static_folder=STATIC_DIR)

print(f"[ENTITY BUILDER] Data Directory: {DATA_DIR}")

@app.route('/')
def index():
    return render_template('entity_builder.html')

@app.route('/api/files', methods=['GET'])
def list_files():
    """Lists relevant JSON files grouped by category."""
    categories = {
        "monsters": [],
        "items": [],
        "nodes": [],
        "loot": [],
        "spells": [],
        "quests": [] # Added quests category
    }
    
    def scan(pattern, cat):
        for f in glob.glob(os.path.join(DATA_DIR, "**", pattern), recursive=True):
            rel = os.path.relpath(f, DATA_DIR).replace('\\', '/')
            categories[cat].append(rel)

    scan("monsters*.json", "monsters")
    scan("npcs*.json", "monsters") # Also scan NPCs into monsters category
    scan("items_*.json", "items")
    scan("nodes*.json", "nodes")
    scan("loot*.json", "loot")
    scan("spells*.json", "spells")
    scan("quests*.json", "quests") # Now scanning quests
        
    return jsonify(categories)

@app.route('/api/references', methods=['GET'])
def get_references():
    """Returns lists of IDs for skills, items, loot tables, and spells for autocomplete."""
    refs = {
        "skills": [],
        "items": [],
        "loot_tables": [],
        "spells": []
    }

    # 1. Skills (List of Dicts)
    skills_path = os.path.join(DATA_DIR, "skills.json")
    if os.path.exists(skills_path):
        try:
            with open(skills_path, 'r') as f:
                data = json.load(f)
                refs["skills"] = [s.get("skill_id") for s in data if "skill_id" in s]
        except: pass

    # 2. Items (Dict of Dicts)
    for f in glob.glob(os.path.join(DATA_DIR, "**", "items_*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["items"].extend(data.keys())
        except: pass

    # 3. Loot Tables (Dict of Lists/Dicts)
    for f in glob.glob(os.path.join(DATA_DIR, "**", "loot*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["loot_tables"].extend(data.keys())
        except: pass

    # 4. Spells (Dict of Dicts)
    for f in glob.glob(os.path.join(DATA_DIR, "**", "spells*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["spells"].extend(data.keys())
        except: pass
    
    # Sort for UI
    for k in refs: refs[k].sort()

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