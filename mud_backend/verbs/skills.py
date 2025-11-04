# mud_backend/verbs/skills.py
from mud_backend.verbs.base_verb import BaseVerb
from mud_backend.core import game_state
from typing import List, Tuple, Dict, Any

class Skills(BaseVerb):
    """
    Handles the 'skills' command.
    Displays the player's trained skills and ranks.
    """
    
    def execute(self):
        player_skills = self.player.skills
        if not player_skills:
            self.player.send_message("You have no skills trained.")
            return

        skill_lines = []
        
        # We need the full skill list from game_state to get the names/categories
        all_skills = game_state.GAME_SKILLS
        
        # Filter for skills with rank > 0 and prepare for sorting
        active_skills: List[Tuple[str, int]] = [
            (skill_id, rank) for skill_id, rank in player_skills.items() if rank > 0
        ]
        
        # Sort skills by category and then by name
        sorted_skills = sorted(
            active_skills,
            key=lambda x: (
                all_skills.get(x[0], {}).get("category", "Z_Other"),
                all_skills.get(x[0], {}).get("name", "Z_Unknown")
            )
        )
        
        current_category = ""
        
        self.player.send_message("--- **Trained Skills** ---")

        for skill_id, rank in sorted_skills:
            skill_data = all_skills.get(skill_id, {})
            category = skill_data.get("category", "Other Skills")
            name = skill_data.get("name", skill_id.replace('_', ' ').title())
            
            if category != current_category:
                skill_lines.append(f"\n--- {category.upper()} ---")
                current_category = category
            
            skill_lines.append(f"- {name}: Rank {rank}")
            
        self.player.send_message("\n".join(skill_lines))