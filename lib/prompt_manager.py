from pathlib import Path
import json
from typing import Dict, List, Optional
from models.prompt import Prompt

class PromptManager:
    def __init__(self, prompts_dir: Path):
        self.prompts_dir = prompts_dir
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
    
    def get_all_prompts(self) -> List[Prompt]:
        prompts = []
        for prompt_file in self.prompts_dir.glob("[!_]*.json"):
            try:
                with open(prompt_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    prompts.append(Prompt.from_dict(data))
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Warning: Skipping invalid prompt file {prompt_file.name}: {str(e)}")
                continue
        return prompts
    
    def get_prompt(self, name: str) -> Optional[Prompt]:
        if name.startswith('_'):
            return None
            
        prompt_file = self.prompts_dir / f"{name}.json"
        if not prompt_file.exists():
            return None
            
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return Prompt.from_dict(data)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Invalid prompt file {prompt_file.name}: {str(e)}")
            return None
    
    def save_prompt(self, prompt: Prompt) -> bool:
        if prompt.name.startswith('_'):
            return False
            
        try:
            prompt_file = self.prompts_dir / f"{prompt.name}.json"
            with open(prompt_file, 'w', encoding='utf-8') as f:
                json.dump(prompt.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False
    
    def delete_prompt(self, name: str) -> bool:
        if name.startswith('_'):
            return False
            
        prompt_file = self.prompts_dir / f"{name}.json"
        if prompt_file.exists():
            prompt_file.unlink()
            return True
        return False 