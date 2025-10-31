def execute(self):
        # The 'look' verb logic
        if not self.args:
            # Player is looking at the current room
            self.player.send_message(f"**{self.room.name}**")
            self.player.send_message(self.room.description)
            self.player.send_message("You see a few other people standing around.")
            
            # NEW: List objects as HTML spans
            if self.room.objects:
                html_objects = []
                for obj in self.room.objects:
                    obj_name = obj['name']
                    # Get verbs, default to just 'look' if none are specified
                    verbs = obj.get('verbs', ['look'])
                    # Join verbs with a comma for the data-attribute
                    verb_str = ','.join(verbs).lower()
                    
                    # Create an HTML span with data attributes
                    # The JS will read 'data-name' and 'data-verbs'
                    html_objects.append(
                        f'<span class="keyword" data-name="{obj_name}" data-verbs="{verb_str}">{obj_name}</span>'
                    )
                    
                self.player.send_message(f"\nObvious objects here: {', '.join(html_objects)}.")
                
        else:
            # Player is trying to look at something specific (e.g., 'look well')
            target = self.args[0].lower()
            
            # Check room objects for the target
            found_object = next((obj for obj in self.room.objects if obj['name'] == target), None)

            if found_object:
                self.player.send_message(f"You examine the **{found_object['name']}**.")
                self.player.send_message(found_object.get('description', 'It is a nondescript object.'))
                
                # List available actions
                if 'verbs' in found_object:
                    # NEW: Also send verbs as styled spans (optional, but cool)
                    verb_list = ", ".join([f'<span class="keyword">{v}</span>' for v in found_object['verbs']])
                    self.player.send_message(f"You could try: {verb_list}")
            else:
                self.player.send_message(f"You do not see a **{target}** here.")