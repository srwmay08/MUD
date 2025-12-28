import json
import random
import os

class ForagingSystem:
    """
    Handles the discovery and collection of flora from the game world.
    Strictly handles 'World -> Inventory' logic.
    """
    
    # Path to the JSON file
    PLANT_DATA_FILE = "items_plants.json"
    
    # Cache for loaded plant data
    _plants_data = None

    @classmethod
    def load_plants(cls):
        """
        Loads the plant definitions from the JSON file if not already loaded.
        """
        if cls._plants_data is not None:
            return

        if not os.path.exists(cls.PLANT_DATA_FILE):
            print(f"Error: {cls.PLANT_DATA_FILE} not found.")
            cls._plants_data = {}
            return

        try:
            with open(cls.PLANT_DATA_FILE, 'r') as f:
                cls._plants_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding plant JSON: {e}")
            cls._plants_data = {}

    @classmethod
    def get_plant_by_id(cls, plant_id):
        """
        Retrieves a copy of the plant data by ID.
        """
        cls.load_plants()
        plant = cls._plants_data.get(plant_id)
        if plant:
            # Return a copy so we don't mutate the source template
            return plant.copy()
        return None

    @staticmethod
    def attempt_forage(player, current_biome):
        """
        Executes a foraging attempt based on player stats and current location.
        
        Args:
            player: The player object (requires .stats, .inventory, .send_message).
            current_biome: String representing the current area (e.g., "forest", "desert").
        """
        # 1. Base Skill Check (Example: Perception + Survival)
        # You can adjust these stat references to match your specific player system
        perception = player.stats.get("perception", 10)
        survival = player.stats.get("survival", 0)
        
        # Simple d20 roll logic
        roll = random.randint(1, 20) + (perception // 2) + survival
        difficulty = ForagingSystem._get_biome_difficulty(current_biome)

        if roll < difficulty:
            ForagingSystem._handle_failure(player)
            return

        # 2. Determine Loot Table
        loot_table = ForagingSystem._get_biome_loot(current_biome)
        if not loot_table:
            player.send_message("You search the area but find nothing of interest here.")
            return

        # 3. Select Item
        found_item_id = random.choice(loot_table)
        item_data = ForagingSystem.get_plant_by_id(found_item_id)

        if not item_data:
            player.send_message("You found something, but it crumbled to dust (Data Error).")
            return

        # 4. Add to Inventory (The final step of Foraging)
        player.inventory.append(item_data)
        
        # 5. Success Message
        player.send_message(f"You forage around and manage to find {item_data['name']}!")

    @staticmethod
    def _get_biome_difficulty(biome):
        """
        Returns the DC (Difficulty Class) for foraging in a specific biome.
        """
        difficulty_map = {
            "forest": 10,
            "plains": 8,
            "desert": 15,
            "swamp": 14,
            "mountain": 16,
            "dungeon": 18
        }
        return difficulty_map.get(biome.lower(), 12)

    @staticmethod
    def _get_biome_loot(biome):
        """
        Returns a list of item_ids valid for the given biome.
        This allows specific herbs to only spawn in specific areas.
        """
        # In a real scenario, this might also be loaded from a json file
        # or derived from tags in items_plants.json
        loot_map = {
            "forest": ["sweetfern_leaf", "basal_moss", "rosemarrow_potion", "pennyroyal_stem"],
            "plains": ["knitbone_flower", "snapdragon_tea", "gingko_nut"],
            "desert": ["withered_root", "numb_needle", "barrel_cactus", "crimson_aloe"],
            "swamp": ["hydra_tongue", "troll_moss", "glow_lichen", "tormented_root"],
            "mountain": ["ambrosia_stalk", "ironwood_bark", "kingsfoil_leaf"],
            "dungeon": ["basal_moss", "starfruit_berry"]
        }
        return loot_map.get(biome.lower(), [])

    @staticmethod
    def _handle_failure(player):
        """
        Flavor text for failed attempts.
        """
        messages = [
            "You scrounge around in the dirt but find nothing useful.",
            "You see some plants, but they look withered and useless.",
            "You search the area, but only find rocks and debris.",
            "You fail to find any herbs of value."
        ]
        player.send_message(random.choice(messages))