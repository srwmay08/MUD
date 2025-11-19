import os
import json
import glob
from flask import Flask, render_template, request, jsonify

# --- CONFIGURATION ---
# Calculate paths relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Path to your game data (e.g., mud_backend/data)
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_backend', 'data'))
# Path to frontend statics (css/js)
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'mud_frontend', 'static'))

app = Flask(__name__, template_folder='.', static_folder=STATIC_DIR)

print(f"[BUILDER] Data Directory: {DATA_DIR}")
print(f"[BUILDER] Static Directory: {STATIC_DIR}")

@app.route('/')
def index():
    """Serves the Room Builder Interface."""
    return render_template('room_builder.html')

@app.route('/api/zones', methods=['GET'])
def list_zones():
    """Lists all JSON zone files found in mud_backend/data."""
    json_files = []
    # Recursive search for .json files
    search_path = os.path.join(DATA_DIR, '**', '*.json')
    
    for filepath in glob.glob(search_path, recursive=True):
        # Create a relative path for display (e.g., "aethels_crossing/rooms.json")
        rel_path = os.path.relpath(filepath, DATA_DIR)
        # Normalize slashes for Windows/Linux compatibility
        rel_path = rel_path.replace('\\', '/')
        json_files.append(rel_path)
        
    return jsonify(json_files)

@app.route('/api/load', methods=['GET'])
def load_zone():
    """Loads a specific zone file by relative path."""
    filename = request.args.get('file')
    if not filename:
        return jsonify({"error": "No filename provided"}), 400
        
    # Security check: prevent directory traversal
    safe_path = os.path.normpath(os.path.join(DATA_DIR, filename))
    if not safe_path.startswith(DATA_DIR):
        return jsonify({"error": "Invalid file path"}), 403
        
    if not os.path.exists(safe_path):
        return jsonify({"error": "File not found"}), 404
        
    try:
        with open(safe_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Ensure we always return a list (Zone format)
        if isinstance(data, dict):
            data = [data]
            
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/save', methods=['POST'])
def save_zone():
    """Saves the current zone data to a file."""
    payload = request.json
    filename = payload.get('filename')
    rooms = payload.get('rooms')
    
    if not filename or not rooms:
        return jsonify({"error": "Missing filename or room data"}), 400

    # Security check
    safe_path = os.path.normpath(os.path.join(DATA_DIR, filename))
    if not safe_path.startswith(DATA_DIR):
        return jsonify({"error": "Invalid file path"}), 403
        
    # Ensure the directory exists (in case it's a new subfolder)
    os.makedirs(os.path.dirname(safe_path), exist_ok=True)
    
    try:
        with open(safe_path, 'w', encoding='utf-8') as f:
            json.dump(rooms, f, indent=4)
        print(f"[BUILDER] Saved {len(rooms)} rooms to {filename}")
        return jsonify({"success": True, "path": safe_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run on a different port than the game server to allow running both
    print("[BUILDER] Server running at http://localhost:5000")
    app.run(port=5000, debug=True)