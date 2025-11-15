import os
import json
from flask import Flask, render_template, request, jsonify

# Initialize the Flask app
# We set template_folder and static_folder to '.' 
# to tell Flask to look for the HTML file in the same directory.
app = Flask(__name__, template_folder='.', static_folder='.')

# Define the main route ('/') to serve the HTML page
@app.route('/')
def index():
    """
    Serves the main room_builder.html page.
    """
    return render_template('room_builder.html')

# Define the '/save' route to handle saving the room data
@app.route('/save', methods=['POST'])
def save_room():
    """
    Receives room data as JSON, saves it to a file in the 'rooms' directory.
    The file is named after the room_id.
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data received"}), 400

    # Get the room_id to use as a filename
    room_id = data.get('room_id', 'untitled_room')
    if not room_id:  # Handle empty string
        room_id = 'untitled_room'
        
    filename = f"{room_id}.json"
    
    # Create a 'rooms' directory if it doesn't exist
    output_dir = 'rooms'
    os.makedirs(output_dir, exist_ok=True)
    
    filepath = os.path.join(output_dir, filename)
    
    # Save the data to the JSON file
    # We save it inside a list, just like your template
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump([data], f, indent=2) # Save as list, matching template
            
        return jsonify({
            "message": "Room saved successfully!",
            "filename": filename,
            "path": filepath
        }), 200
        
    except Exception as e:
        print(f"Error saving file: {e}")
        return jsonify({"error": f"Failed to save file: {str(e)}"}), 500

# Run the app
if __name__ == '__main__':
    print("\nStarting MUD Room Builder... 🎉")
    print("---------------------------------")
    print(f"To use, open your web browser and go to: http://127.0.0.1:5000")
    print("Your saved room JSON files will appear in a 'rooms' directory.")
    print("Press CTRL+C to stop the server.\n")
    app.run(debug=True, port=5000)