# main.py
import sys
import os

# --- CRITICAL FIX: Add the project root to the system path ---
# This ensures that 'core' and 'verbs' are found when running the package.
# It calculates the path one level up from the directory containing main.py (mud_backend)
# and prepends it to Python's search list.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# -------------------------------------------------------------

from mud_backend.core.command_executor import execute_command
# NOTE: The import must now be absolute, referencing the package name.


# --- Simulation of a command coming from the web client ---

def simulate_web_request(player_name: str, command: str):
    print(f"\n>>> COMMAND: {command}")
    output = execute_command(player_name, command)
    print("<<< OUTPUT TO CLIENT:")
    for line in output:
        print(f"    {line}")
    print("-" * 20)


# Test Cases
simulate_web_request("Alice", "look")
simulate_web_request("Alice", "look fountain")
simulate_web_request("Alice", "say Hello world, what a great day!")
simulate_web_request("Alice", "teleport town_square") # Unknown verb
simulate_web_request("Bob", "look") # Unknown player