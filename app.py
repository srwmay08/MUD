import sys
import os
from flask import Flask, request, jsonify, render_template

# --- CRITICAL: Add the 'mud_backend' to the Python path ---
# This allows us to import your existing game logic
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'mud_backend')))
# -----------------------------------------------------------

# Now we can import your execute_command function
from core.command_executor import execute_command

app = Flask(__name__)

# --- Route 1: Serve the HTML page ---
# This serves the 'index.html' file to the user's browser
@app.route("/")
def index():
    # We will create this 'index.html' file next
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