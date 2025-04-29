import json
import os

# if not have pos folder, create it
if not os.path.exists("pos"):
    os.makedirs("pos")

class PosPointer:
    def __init__(self, id):
        self.id = id
        self.pos = 0
        self.file_path = f"pos/{id}.json"
        
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump({"pos": 0}, f)
                
        self.load_cache()
    
    def set(self, pos: int):
        self.pos = pos
        self.save_cache()
        return self
    
    def save_cache(self):
        with open(self.file_path, "w") as f:
            json.dump({"pos": self.pos}, f)

    def load_cache(self):
        try:
            with open(self.file_path, "r") as f:
                self.pos = json.load(f)["pos"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            # If file doesn't exist or is invalid, use default value
            self.pos = 0
            # Create a new file with default value
            with open(self.file_path, "w") as f:
                json.dump({"pos": 0}, f)
    