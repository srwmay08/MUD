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
    """
    Saves the provided files AND searches all other .json files on disk.
    If a room_id in the saved data matches a room_id in an unloaded file,
    the unloaded file is updated to match the new data.
    """
    payload = request.json
    incoming_files = payload.get('files', {}) 
    
    results = []
    
    # 1. Collect all updated room definitions into a map { room_id: room_object }
    updated_rooms_map = {}
    for filename, rooms in incoming_files.items():
        if isinstance(rooms, list):
            for room in rooms:
                if isinstance(room, dict) and 'room_id' in room:
                    updated_rooms_map[room['room_id']] = room

    # 2. Map normalized paths to incoming content
    incoming_abs_paths = {}
    for rel_path, content in incoming_files.items():
        if not rel_path.endswith('.json'): rel_path += '.json'
        abs_path = os.path.normpath(os.path.join(DATA_DIR, rel_path))
        incoming_abs_paths[abs_path] = content

    # 3. Iterate over EVERY .json file
    all_json_files = glob.glob(os.path.join(DATA_DIR, '**', '*.json'), recursive=True)
    
    for filepath in all_json_files:
        filepath = os.path.normpath(filepath)
        
        if filepath in incoming_abs_paths:
            file_content = incoming_abs_paths[filepath]
            is_explicit_save = True
        else:
            is_explicit_save = False
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_content = json.load(f)
            except:
                continue

        if not isinstance(file_content, list): continue

        changes_made = False
        
        # 4. Scan rooms in this file
        for i, room in enumerate(file_content):
            if not isinstance(room, dict): continue
            
            rid = room.get('room_id')
            
            # If this room exists in our update map...
            if rid and rid in updated_rooms_map:
                new_data = updated_rooms_map[rid]
                if room != new_data:
                    file_content[i] = new_data
                    changes_made = True
        
        # 5. Write to disk
        if is_explicit_save or changes_made:
            rel_name = os.path.relpath(filepath, DATA_DIR).replace('\\', '/')
            try:
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(file_content, f, indent=4)
                if is_explicit_save:
                    results.append(f"Saved {rel_name}")
                else:
                    results.append(f"Synced duplicate in {rel_name}")
            except Exception as e:
                results.append(f"Error saving {rel_name}: {str(e)}")

    return jsonify({"results": results})

@app.route('/api/rename_room', methods=['POST'])
def rename_room():
    """
    Globally renames a room ID across ALL files.
    Updates the definition AND all exits pointing to it.
    """
    data = request.json
    old_id = data.get('old_id')
    new_id = data.get('new_id')
    
    if not old_id or not new_id:
        return jsonify({"error": "Missing parameters"}), 400

    results = []
    
    # Scan ALL files
    all_json_files = glob.glob(os.path.join(DATA_DIR, '**', '*.json'), recursive=True)
    
    for filepath in all_json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = json.load(f)
        except:
            continue

        if not isinstance(content, list): continue
        
        changes = False
        
        for room in content:
            if not isinstance(room, dict): continue
            
            # 1. Update Definition
            if room.get('room_id') == old_id:
                room['room_id'] = new_id
                changes = True
            
            # 2. Update Exits
            if 'exits' in room:
                for dir, target in room['exits'].items():
                    if target == old_id:
                        room['exits'][dir] = new_id
                        changes = True
                        
            # 3. Update Object Targets (Doors/Portals)
            if 'objects' in room:
                for obj in room['objects']:
                    if obj.get('target_room') == old_id:
                        obj['target_room'] = new_id
                        changes = True
                    # Check interactions
                    if 'interactions' in obj:
                        for verb, action in obj['interactions'].items():
                            if action.get('type') == 'move' and action.get('value') == old_id:
                                action['value'] = new_id
                                changes = True

        if changes:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(content, f, indent=4)
                rel = os.path.relpath(filepath, DATA_DIR)
                results.append(f"Updated {rel}")
            except Exception as e:
                results.append(f"Error updating {filepath}: {e}")

    return jsonify({"results": results, "count": len(results)})

@app.route('/api/assets', methods=['GET'])
def get_assets():
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
    scan_assets('**/items*.json', 'items', 'id', 'name') 
    scan_assets('**/nodes.json', 'nodes', 'id', 'name')  
    scan_assets('**/loot*.json', 'loot_tables', 'id', 'name') 

    for k in assets: assets[k].sort(key=lambda x: x['name'])
    return jsonify(assets)

if __name__ == '__main__':
    print(f"[BUILDER] Serving at http://localhost:5000")
    app.run(port=5000, debug=True)