# mud_backend/app.py
import sys
import os
from flask import Flask, request, jsonify, render_template

# --- CRITICAL FIX 1: Add the PROJECT ROOT to the Python path ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# -----------------------------------------------------------

# --- UPDATED IMPORTS ---
from mud_backend.core.command_executor import execute_command
from mud_backend.core import game_state
from mud_backend.core import db
# ---

# --- CRITICAL FIX 2: Define file paths ---
# Path to the 'templates' folder
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))

# --- NEW: Path to the 'static' folder ---
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'static'))
# --- END NEW ---

# --- UPDATED: Tell Flask about both folders ---
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
# ---------------------------------------------------------


# --- Route 1: Serve the HTML page ---
@app.route("/")
def index():
    return render_template("index.html")

# --- Route 2: Handle Game Commands ---
@app.route("/api/command", methods=["POST"])
def handle_command():
    try:
        data = request.json
        
        player_name = data.get("player_name")
        command_line = data.get("command", "")
        
        if not player_name:
            return jsonify({"messages": ["Error: No player name received from client."]}), 400
        
        result_data = execute_command(player_name, command_line)

        return jsonify({
            "messages": result_data["messages"],
            "game_state": result_data["game_state"]
        })
        
    except Exception as e:
        return jsonify({"messages": [f"Server Error: {str(e)}"]}), 500

if __name__ == "__main__":
    print("[SERVER START] Initializing database...")
    database = db.get_db()
    
    if database is not None:
        print("[SERVER START] Loading all rooms into game state cache...")
        game_state.GAME_ROOMS = db.fetch_all_rooms()
        print(f"[SERVER START] Successfully cached {len(game_state.GAME_ROOMS)} rooms.")
    else:
        print("[SERVER START] ERROR: Could not connect to database. Server may not function.")
    
    app.run(port=8000, debug=True, use_reloader=False)