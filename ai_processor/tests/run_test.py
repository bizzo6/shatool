#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
sys.path.append(project_root)

# Load environment variables from .env file if it exists
env_path = Path(project_root) / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Check for required environment variables
if not os.getenv('GPT_API_KEY'):
    print("Error: GPT_API_KEY environment variable is not set")
    print("Please set it in your .env file or environment variables")
    sys.exit(1)

# Import the main test function
from ai_processor.tests.test_processor import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 