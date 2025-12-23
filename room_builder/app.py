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
            # DIRECT OVERWRITE
            with open(safe_path, 'w', encoding='utf-8') as f:
                json.dump(rooms, f, indent=4)
            results.append(f"Saved {filename}")
        except Exception as e:
            results.append(f"Error saving {filename}: {str(e)}")

    return jsonify({"results": results})

@app.route('/api/rename_room', methods=['POST'])
def rename_room():
    """
    Globally renames a room ID across ALL files with DEBUG LOGGING.
    """
    data = request.json
    old_id = data.get('old_id')
    new_id = data.get('new_id')
    
    print(f"\n[DEBUG] --- START RENAME REQUEST ---")
    print(f"[DEBUG] Request to rename '{old_id}' -> '{new_id}'")
    
    if not old_id or not new_id:
        print("[DEBUG] ERROR: Missing parameters")
        return jsonify({"error": "Missing parameters"}), 400

    if old_id == new_id:
        print("[DEBUG] WARNING: old_id and new_id are the same. Nothing to do.")
        return jsonify({"results": [], "count": 0, "message": "Ids are identical"})

    results = []
    
    # Scan ALL files recursively
    print(f"[DEBUG] Scanning directory: {DATA_DIR}")
    all_json_files = glob.glob(os.path.join(DATA_DIR, '**', '*.json'), recursive=True)
    print(f"[DEBUG] Found {len(all_json_files)} files to scan.")
    
    total_refs_found = 0

    for filepath in all_json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = json.load(f)
        except Exception as e:
            print(f"[DEBUG] Could not read {filepath}: {e}")
            continue

        if not isinstance(content, list): 
            # Skip non-room files (like items.json which are dicts)
            continue
        
        file_changed = False
        file_refs = 0
        
        for room in content:
            if not isinstance(room, dict): continue
            
            # 1. Update Definition (if this is the room being renamed)
            if room.get('room_id') == old_id:
                print(f"[DEBUG] MATCH FOUND (Definition): In {os.path.basename(filepath)}")
                room['room_id'] = new_id
                file_changed = True
                file_refs += 1
            
            # 2. Update Exits (searching for the old ID in values)
            if 'exits' in room:
                for direction, target in room['exits'].items():
                    if target == old_id:
                        print(f"[DEBUG] MATCH FOUND (Exit): In {os.path.basename(filepath)}, Room '{room.get('room_id')}' -> {direction}")
                        room['exits'][direction] = new_id
                        file_changed = True
                        file_refs += 1
                        
            # 3. Update Object Targets (Doors/Portals)
            if 'objects' in room:
                for obj in room['objects']:
                    if obj.get('target_room') == old_id:
                        print(f"[DEBUG] MATCH FOUND (Object Target): In {os.path.basename(filepath)}, Object '{obj.get('name')}'")
                        obj['target_room'] = new_id
                        file_changed = True
                        file_refs += 1
                    
                    # Check interactions (e.g. { "enter": { "type": "move", "value": "old_id" } })
                    if 'interactions' in obj:
                        for verb, action in obj['interactions'].items():
                            if action.get('type') == 'move' and action.get('value') == old_id:
                                print(f"[DEBUG] MATCH FOUND (Interaction): In {os.path.basename(filepath)}, Object '{obj.get('name')}' verb '{verb}'")
                                action['value'] = new_id
                                file_changed = True
                                file_refs += 1

        if file_changed:
            try:
                print(f"[DEBUG] SAVING FILE: {filepath}")
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(content, f, indent=4)
                rel = os.path.relpath(filepath, DATA_DIR)
                results.append(f"Updated {rel} ({file_refs} refs)")
                total_refs_found += file_refs
            except Exception as e:
                print(f"[DEBUG] ERROR SAVING {filepath}: {e}")
                results.append(f"Error updating {filepath}: {e}")

    print(f"[DEBUG] --- END RENAME REQUEST (Total changes: {total_refs_found}) ---")
    return jsonify({"results": results, "count": len(results)})

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