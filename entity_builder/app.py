import os
import json
import glob
from flask import Flask, render_template, request, jsonify

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Path to game data
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
        "quests": []
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
        
    return jsonify(categories)

@app.route('/api/load', methods=['GET'])
def load_file():
    filename = request.args.get('file')
    if not filename: return jsonify({"error": "No filename"}), 400
    
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path): return jsonify({"error": "Not found"}), 404
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Determine structure type
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