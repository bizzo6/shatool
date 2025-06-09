import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from lib.prompt_manager import PromptManager

class Config:
    """Configuration management for the AI processor."""
    
    # Load environment variables from .env file in project root
    PROJECT_ROOT = Path(__file__).parent.parent
    ENV_PATH = PROJECT_ROOT / '.env'
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    
    # API configuration
    API_KEY = os.getenv("OPENAI_API_KEY")
    MODEL = os.getenv("GPT_MODEL", "gpt-4.1-mini")
    MAX_TOKENS = int(os.getenv("GPT_MAX_TOKENS", "5000"))
    TEMPERATURE = float(os.getenv("GPT_TEMPERATURE", "0.7"))
    
    # Processing configuration
    MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "50"))
    PROCESSING_INTERVAL = int(os.getenv("PROCESSING_INTERVAL", "300"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))
    
    # File paths
    PROMPTS_DIR = PROJECT_ROOT / "prompts"
    METADATA_FILE = PROJECT_ROOT / "config" / "metadata.json"
    
    # Initialize prompt manager
    _prompt_manager = PromptManager(PROMPTS_DIR)
    
    # Loaded data
    _prompts = {}
    _metadata = None
    
    @classmethod
    def load_prompts(cls) -> None:
        """Load all prompt templates from the prompts directory."""
        cls._prompts = {
            prompt.name: prompt.to_dict()
            for prompt in cls._prompt_manager.get_all_prompts()
        }
    
    @classmethod
    def get_prompt_template(cls, prompt_type: str) -> str:
        """Get the template for a specific prompt type."""
        cls.load_prompts()  # Always reload from disk
        return cls._prompts.get(prompt_type, {}).get('template')
    
    @classmethod
    def get_prompt_output_format(cls, prompt_type: str) -> dict:
        cls.load_prompts()  # Always reload from disk
        return cls._prompts.get(prompt_type, {}).get('output_format')
    
    @classmethod
    def load_metadata(cls) -> dict:
        """Load metadata from the metadata file."""
        if cls._metadata is None:
            with open(cls.METADATA_FILE, 'r', encoding='utf-8') as f:
                cls._metadata = json.load(f)
        return cls._metadata
    
    @classmethod
    def get_prompt_description(cls, prompt_type: str) -> Optional[str]:
        """Get the description for a specific prompt type."""
        cls.load_prompts()  # Always reload from disk
        prompt_config = cls._prompts.get(prompt_type)
        if not prompt_config:
            return None
        return prompt_config.get('description')
    
    @classmethod
    def list_available_prompts(cls) -> Dict[str, str]:
        """List all available prompt types and their descriptions."""
        cls.load_prompts()  # Always reload from disk
        return {
            name: config.get('description', '')
            for name, config in cls._prompts.items()
        } 