# mud_backend/app.py
import sys
import os
from flask import Flask, request, jsonify, render_template

# --- CRITICAL FIX: Add the PROJECT ROOT to the Python path ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# -----------------------------------------------------------

# Now we can import using the absolute package path
from mud_backend.core.command_executor import execute_command

# --- FIX 2: Tell Flask where the 'templates' folder is ---
# It's one level up ('..') from app.py and inside 'mud_frontend'
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mud_frontend'))
app = Flask(__name__, template_folder=template_dir)
# ---------------------------------------------------------


# --- Route 1: Serve the HTML page ---
# This serves the 'index.html' file to the user's browser
@app.route("/")
def index():
    # This will now correctly find 'index.html' in the 'mud_frontend' folder
    return render_template("index.html")

# --- Route 2: Handle Game Commands ---
# This is the API endpoint our browser will send commands to
@app.route("/api/command", methods=["POST"])
def handle_command():
    try:
        data = request.json
        
        # Get data from the frontend's request
        player_name = data.get("player_name", "Alice") # Default to "Alice"
        command_line = data.get("command", "")
        
        if not command_line:
            return jsonify({"messages": ["What?"]})

        # --- This is the key part ---
        # We call your existing backend function with the command
        output_messages = execute_command(player_name, command_line)
        # ---------------------------

        # Send the game's response back to the frontend
        return jsonify({"messages": output_messages})
        
    except Exception as e:
        # Send any errors back to the frontend
        return jsonify({"messages": [f"Server Error: {str(e)}"]}), 500

if __name__ == "__main__":
    # Run the web server on http://localhost:8000
    app.run(port=8000, debug=True)