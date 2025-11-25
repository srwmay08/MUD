import os
import json
import glob
from flask import Flask, render_template, request, jsonify

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_backend', 'data'))
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_frontend', 'static'))

app = Flask(__name__, template_folder='.', static_folder=STATIC_DIR)

def load_json_files(pattern):
    """Helper to recursively find and load JSON files."""
    results = []
    files = glob.glob(os.path.join(DATA_DIR, pattern), recursive=True)
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                data = json.load(file)
                results.append(data)
        except Exception as e:
            print(f"[ERROR] Failed to load {f}: {e}")
    return results

@app.route('/')
def index():
    return render_template('room_builder.html')

@app.route('/api/zones', methods=['GET'])
def list_zones():
    json_files = []
    search_path = os.path.join(DATA_DIR, '**', 'rooms_*.json') # Scan specifically for rooms_*.json
    for filepath in glob.glob(search_path, recursive=True):
        rel_path = os.path.relpath(filepath, DATA_DIR)
        json_files.append(rel_path.replace('\\', '/'))
    return jsonify(json_files)

@app.route('/api/load', methods=['GET'])
def load_zone():
    filename = request.args.get('file')
    if not filename: return jsonify({"error": "No filename"}), 400
    safe_path = os.path.normpath(os.path.join(DATA_DIR, filename))
    if not safe_path.startswith(DATA_DIR) or not os.path.exists(safe_path):
        return jsonify({"error": "Invalid file"}), 403
    try:
        with open(safe_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data if isinstance(data, list) else [data])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/save', methods=['POST'])
def save_zone():
    payload = request.json
    filename = payload.get('filename')
    rooms = payload.get('rooms')
    if not filename or not rooms: return jsonify({"error": "Missing data"}), 400
    safe_path = os.path.normpath(os.path.join(DATA_DIR, filename))
    if not safe_path.startswith(DATA_DIR): return jsonify({"error": "Invalid path"}), 403
    
    os.makedirs(os.path.dirname(safe_path), exist_ok=True)
    try:
        with open(safe_path, 'w', encoding='utf-8') as f:
            json.dump(rooms, f, indent=4)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/assets', methods=['GET'])
def get_assets():
    """
    Aggregates all game assets into simple lists for the frontend dropdowns.
    """
    assets = {
        "monsters": [],
        "items": [],
        "nodes": [],
        "loot_tables": []
    }

    # 1. Load Monsters (List of Dicts)
    monster_files = load_json_files('**/monsters*.json')
    for file_content in monster_files:
        if isinstance(file_content, list):
            for m in file_content:
                if "monster_id" in m:
                    assets["monsters"].append({"id": m["monster_id"], "name": m.get("name", "Unknown")})

    # 2. Load Items (Dict of Dicts)
    item_files = load_json_files('**/items*.json')
    for file_content in item_files:
        if isinstance(file_content, dict):
            for k, v in file_content.items():
                assets["items"].append({"id": k, "name": v.get("name", k)})

    # 3. Load Nodes (Dict of Dicts)
    node_files = load_json_files('**/nodes.json') # Usually just one, but generic is fine
    for file_content in node_files:
        if isinstance(file_content, dict):
            for k, v in file_content.items():
                # Add node_type so we can filter in UI if needed
                assets["nodes"].append({"id": k, "name": v.get("name", k), "type": v.get("node_type", "unknown")})

    # 4. Load Loot Tables (Dict of Dicts/Lists)
    loot_files = load_json_files('**/loot*.json')
    for file_content in loot_files:
        if isinstance(file_content, dict):
            for k, v in file_content.items():
                assets["loot_tables"].append({"id": k, "name": k}) # Loot tables usually don't have human names

    # Sort them for easier reading
    for key in assets:
        assets[key].sort(key=lambda x: x["name"])

    return jsonify(assets)

if __name__ == '__main__':
    print(f"[BUILDER] Serving at http://localhost:5000")
    app.run(port=5000, debug=True)