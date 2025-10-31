# mud_backend/app.py
import sys
import os
from flask import Flask, request, jsonify, render_template

# --- CRITICAL FIX 1: Add the PROJECT ROOT to the Python path ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# -----------------------------------------------------------

# Now we can import using the absolute package path
from mud_backend.core.command_executor import execute_command

# --- CRITICAL FIX 2: Tell Flask where the 'templates' folder is ---
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend', 'templates'))

app = Flask(__name__, template_folder=template_dir)
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
        
        if not command_line:
            return jsonify({"messages": ["What?"]})

        # --- THIS IS THE CHANGE ---
        # execute_command now returns a dictionary
        result_data = execute_command(player_name, command_line)
        # ---------------------------

        # Send the game's response AND the player's current game state
        return jsonify({
            "messages": result_data["messages"],
            "game_state": result_data["game_state"]
        })
        
    except Exception as e:
        # Send any errors back to the frontend
        return jsonify({"messages": [f"Server Error: {str(e)}"]}), 500

if __name__ == "__main__":
    # Run the web server on http://localhost:8000
    app.run(port=8000, debug=True)
