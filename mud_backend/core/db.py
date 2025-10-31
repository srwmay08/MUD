# core/db.py

def fetch_player_data(player_name: str) -> dict:
    """Simulates fetching player data from MongoDB."""
    if player_name == "Alice":
        # Realistic data structure would be a Mongo document
        return {"name": "Alice", "current_room_id": "town_square", "level": 5}
    return {}

def fetch_room_data(room_id: str) -> dict:
    """Simulates fetching room data from MongoDB."""
    if room_id == "town_square":
        return {"id": "town_square", "name": "The Great Town Square", "description": "A bustling place with a fountain."}
    return {}

def save_game_state(player: 'Player'):
    """Simulates saving player state back to MongoDB."""
    print(f"\n[DB SAVE] Player {player.name} state saved.")
    # In a real MUD, you would update the MongoDB document here.