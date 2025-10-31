# main.py
from core.command_executor import execute_command

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