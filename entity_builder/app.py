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
        "loot": []  # Added loot category
    }
    
    # Scan for Monsters/NPCs
    for f in glob.glob(os.path.join(DATA_DIR, "**", "monsters*.json"), recursive=True):
        rel = os.path.relpath(f, DATA_DIR).replace('\\', '/')
        categories["monsters"].append(rel)

    # Scan for Items
    for f in glob.glob(os.path.join(DATA_DIR, "**", "items_*.json"), recursive=True):
        rel = os.path.relpath(f, DATA_DIR).replace('\\', '/')
        categories["items"].append(rel)

    # Scan for Nodes
    for f in glob.glob(os.path.join(DATA_DIR, "**", "nodes*.json"), recursive=True):
        rel = os.path.relpath(f, DATA_DIR).replace('\\', '/')
        categories["nodes"].append(rel)

    # Scan for Loot
    for f in glob.glob(os.path.join(DATA_DIR, "**", "loot*.json"), recursive=True):
        rel = os.path.relpath(f, DATA_DIR).replace('\\', '/')
        categories["loot"].append(rel)
        
    return jsonify(categories)

@app.route('/api/references', methods=['GET'])
def get_references():
    """Returns lists of IDs for skills, items, and loot tables for autocomplete."""
    refs = {
        "skills": [],
        "items": [],
        "loot_tables": []
    }

    # 1. Skills
    skills_path = os.path.join(DATA_DIR, "skills.json")
    if os.path.exists(skills_path):
        try:
            with open(skills_path, 'r') as f:
                data = json.load(f)
                # skills.json is a list of objects
                refs["skills"] = [s.get("skill_id") for s in data if "skill_id" in s]
        except: pass

    # 2. Items (scan all items_*.json)
    for f in glob.glob(os.path.join(DATA_DIR, "**", "items_*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["items"].extend(data.keys())
        except: pass

    # 3. Loot Tables (scan all loot*.json)
    for f in glob.glob(os.path.join(DATA_DIR, "**", "loot*.json"), recursive=True):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, dict):
                    refs["loot_tables"].extend(data.keys())
        except: pass
    
    # Sort for UI
    refs["skills"].sort()
    refs["items"].sort()
    refs["loot_tables"].sort()

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