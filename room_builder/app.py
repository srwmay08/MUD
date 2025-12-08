import os
import json
import glob
from flask import Flask, render_template, request, jsonify

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_backend', 'data'))
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_frontend', 'static'))

app = Flask(__name__, template_folder='.', static_folder=STATIC_DIR)

@app.route('/')
def index():
    return render_template('room_builder.html')

@app.route('/api/zones', methods=['GET'])
def list_zones():
    """Lists all zone files recursively."""
    json_files = []
    search_path = os.path.join(DATA_DIR, '**', 'rooms_*.json')
    for filepath in glob.glob(search_path, recursive=True):
        rel_path = os.path.relpath(filepath, DATA_DIR)
        json_files.append(rel_path.replace('\\', '/'))
    return jsonify(json_files)

@app.route('/api/load', methods=['GET'])
def load_zone():
    """Loads a single zone file."""
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

@app.route('/api/save_batch', methods=['POST'])
def save_batch():
    """Saves multiple zone files at once."""
    payload = request.json
    updates = payload.get('files', {}) # Dict of filename: room_list
    
    results = []
    
    for filename, rooms in updates.items():
        if not filename.endswith('.json'): 
            filename += '.json'
            
        safe_path = os.path.normpath(os.path.join(DATA_DIR, filename))
        if not safe_path.startswith(DATA_DIR): 
            results.append(f"Skipped {filename} (Invalid path)")
            continue
            
        # Ensure directory exists (for new interiors)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        
        try:
            # Create backup
            # if os.path.exists(safe_path):
            #    with open(safe_path + ".bak", 'w', encoding='utf-8') as f:
            #        json.dump(json.load(open(safe_path, 'r', encoding='utf-8')), f, indent=4)

        # DIRECT OVERWRITE - NO BACKUP
            with open(safe_path, 'w', encoding='utf-8') as f:
                json.dump(rooms, f, indent=4)
            results.append(f"Saved {filename}")
        except Exception as e:
            results.append(f"Error saving {filename}: {str(e)}")

            with open(safe_path, 'w', encoding='utf-8') as f:
                json.dump(rooms, f, indent=4)
            results.append(f"Saved {filename}")
        except Exception as e:
            results.append(f"Error saving {filename}: {str(e)}")

    return jsonify({"results": results})

@app.route('/api/assets', methods=['GET'])
def get_assets():
    """Aggregates assets for dropdowns."""
    assets = { "monsters": [], "items": [], "nodes": [], "loot_tables": [] }
    
    def scan_assets(pattern, type_key, id_key="id", name_key="name"):
        for f in glob.glob(os.path.join(DATA_DIR, pattern), recursive=True):
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    content = json.load(file)
                    if isinstance(content, list):
                        for item in content:
                            if id_key in item:
                                assets[type_key].append({"id": item[id_key], "name": item.get(name_key, item[id_key])})
                    elif isinstance(content, dict):
                        for k, v in content.items():
                             assets[type_key].append({"id": k, "name": v.get(name_key, k)})
            except: pass

    scan_assets('**/monsters*.json', 'monsters', 'monster_id')
    scan_assets('**/npcs*.json', 'monsters', 'monster_id')
    scan_assets('**/items*.json', 'items', 'id', 'name') # Dict based
    scan_assets('**/nodes.json', 'nodes', 'id', 'name')  # Dict based
    scan_assets('**/loot*.json', 'loot_tables', 'id', 'name') # Dict based

    for k in assets: assets[k].sort(key=lambda x: x['name'])
    return jsonify(assets)

if __name__ == '__main__':
    print(f"[BUILDER] Serving at http://localhost:5000")
    app.run(port=5000, debug=True)