import os
import asyncio
import json
from datetime import datetime
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add the parent directory to the Python path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Load environment variables from .env file if it exists
env_path = Path(__file__).parent.parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

from ai_processor.config import Config
from ai_processor.message_processor import MessageProcessor
from ai_processor.data_store import DataStore

# Test configuration - only default values, actual values will come from env
TEST_CONFIG = {
    'GPT_MODEL': os.getenv('GPT_MODEL', 'gpt-4'),
    'GPT_TEMPERATURE': os.getenv('GPT_TEMPERATURE', '0.7'),
    'GPT_MAX_TOKENS': os.getenv('GPT_MAX_TOKENS', '1000'),
    'MAX_CONTEXT_MESSAGES': os.getenv('MAX_CONTEXT_MESSAGES', '50'),
    'PROCESSING_INTERVAL': os.getenv('PROCESSING_INTERVAL', '300'),
    'MAX_RETRIES': os.getenv('MAX_RETRIES', '3'),
    'RETRY_DELAY': os.getenv('RETRY_DELAY', '5')
}

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

def create_test_config():
    """Create a test configuration."""
    return Config()

def create_test_processor(test_mode: bool = False):
    """
    Create a test processor with config and data store.
    
    Args:
        test_mode: If True, only print results without saving to data store
    """
    if test_mode:
        # In test mode, use a temporary directory that will be cleaned up
        data_store = DataStore(storage_dir=str(DATA_DIR / "test_temp"))
    else:
        # In normal mode, use the main data directory
        data_store = DataStore(storage_dir=str(DATA_DIR))
    return MessageProcessor(data_store)

def create_test_message(text: str, sender: str, timestamp: int = None) -> dict:
    """Create a test message in the required format."""
    if timestamp is None:
        timestamp = int(datetime.now().timestamp())
    return {
        "timestamp": timestamp,
        "from": sender,
        "text": text
    }

async def test_todo_processing(test_mode: bool = False):
    """Test processing of todo messages."""
    processor = create_test_processor(test_mode)
    
    # Test messages in Hebrew with timestamps and senders
    messages = [
        # Teacher messages about homework
        create_test_message(
            "שלום לכולם, מחר צריך להביא מחברת חשבון",
            "מורה שרה",
            int(datetime.now().timestamp()) - 3600  # 1 hour ago
        ),
        create_test_message(
            "אל תשכחו להכין שיעורי בית למתמטיקה עד יום ראשון",
            "מורה דוד",
            int(datetime.now().timestamp()) - 1800  # 30 minutes ago
        ),
        
        # Parent conversation about the same homework (should not create duplicate)
        create_test_message(
            "מישהו יכול להסביר מה צריך להכין במתמטיקה?",
            "בני",
            int(datetime.now().timestamp()) - 1700
        ),
        create_test_message(
            "צריך להכין את התרגילים מעמוד 45",
            "דליה",
            int(datetime.now().timestamp()) - 1600
        ),
        
        # New todo item from teacher
        create_test_message(
            "הורים יקרים, נדרשת חתימה על טופס הסכמה לטיול",
            "מנהלת בית הספר",
            int(datetime.now().timestamp()) - 1500
        ),
        
        # Parent conversation about the form (should not create duplicate)
        create_test_message(
            "איפה אפשר למצוא את הטופס?",
            "בני",
            int(datetime.now().timestamp()) - 1400
        ),
        create_test_message(
            "הוא נמצא באתר בית הספר",
            "דליה",
            int(datetime.now().timestamp()) - 1300
        ),
        
        # Calendar event that should NOT be processed as todo
        create_test_message(
            "נזכיר שיש פגישת הורים בעוד שבועיים",
            "מנהלת בית הספר",
            int(datetime.now().timestamp()) - 1200
        ),
        
        # New todo with specific deadline
        create_test_message(
            "חשוב: צריך להביא תמונת פספורט עד סוף השבוע",
            "מורה שרה",
            int(datetime.now().timestamp()) - 1100
        ),
        
        # Parent conversation about the photo (should not create duplicate)
        create_test_message(
            "איזה גודל תמונה צריך?",
            "בני",
            int(datetime.now().timestamp()) - 1000
        ),
        create_test_message(
            "3x4 כמו תמיד",
            "דליה",
            int(datetime.now().timestamp()) - 900
        )
    ]
    
    try:
        print("\nCalling process_messages...")
        result = await processor.process_messages(messages, prompt_type="todo")
        print("\nTodo Processing Result:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        # Verify that items were saved (only if not in test mode)
        if not test_mode and "saved_ids" in result:
            print("\nSaved Todo Items:")
            for todo_id in result["saved_ids"]["todos"]:
                todo = await processor.data_store.get("todos", todo_id)
                print(json.dumps(todo, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"\nError in test_todo_processing: {str(e)}")
        print("Error Type:", type(e).__name__)
        import traceback
        print("\nTraceback:")
        print(traceback.format_exc())

async def test_calendar_processing(test_mode: bool = False):
    """Test processing of calendar messages."""
    processor = create_test_processor(test_mode)
    
    # Test messages in Hebrew with timestamps and senders
    messages = [
        create_test_message(
            "טיול שנתי יתקיים ביום שלישי הבא",
            "מורה שרה",
            int(datetime.now().timestamp()) - 3600
        ),
        create_test_message(
            "יש להגיע בשעה 8:00 בבוקר",
            "מורה דוד",
            int(datetime.now().timestamp()) - 1800
        ),
        create_test_message(
            "נחזור בשעה 16:00",
            "מנהלת בית הספר",
            int(datetime.now().timestamp()) - 900
        )
    ]
    
    result = await processor.process_messages(messages, prompt_type="calendar")
    print("\nCalendar Processing Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Verify that items were saved (only if not in test mode)
    if not test_mode and "saved_ids" in result:
        print("\nSaved Calendar Events:")
        for event_id in result["saved_ids"]["events"]:
            event = await processor.data_store.get("calendar", event_id)
            print(json.dumps(event, indent=2, ensure_ascii=False))

async def test_general_processing(test_mode: bool = False):
    """Test processing of general messages."""
    processor = create_test_processor(test_mode)
    
    # Test messages in Hebrew with timestamps and senders
    messages = [
        create_test_message(
            "הודעה חשובה: מחר אין לימודים",
            "מנהלת בית הספר",
            int(datetime.now().timestamp()) - 3600
        ),
        create_test_message(
            "נא להביא חולצה לבנה לאירוע",
            "מורה שרה",
            int(datetime.now().timestamp()) - 1800
        ),
        create_test_message(
            "יש להירשם לאתר בית הספר",
            "מורה דוד",
            int(datetime.now().timestamp()) - 900
        )
    ]
    
    result = await processor.process_messages(messages, prompt_type="general")
    print("\nGeneral Processing Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Verify that items were saved (only if not in test mode)
    if not test_mode and "saved_ids" in result:
        print("\nSaved General Items:")
        for item_id in result["saved_ids"]["items"]:
            item = await processor.data_store.get("general", item_id)
            print(json.dumps(item, indent=2, ensure_ascii=False))

async def test_error_handling(test_mode: bool = False):
    """Test error handling in message processing."""
    processor = create_test_processor(test_mode)
    
    # Test with empty messages
    result = await processor.process_messages([], prompt_type="todo")
    print("\nEmpty Messages Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Test with invalid metadata
    result = await processor.process_messages(
        [create_test_message("Test message", "Test Sender")],
        prompt_type="todo",
        metadata={}  # Missing required metadata
    )
    print("\nInvalid Metadata Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Test with invalid message format
    result = await processor.process_messages(
        [{"invalid": "format"}],  # Invalid message format
        prompt_type="todo"
    )
    print("\nInvalid Message Format Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

async def main(test_mode: bool = False):
    """Run all tests."""
    print(f"Running tests in {'test' if test_mode else 'normal'} mode")
    print(f"Data will be stored in: {DATA_DIR}")
    
    await test_todo_processing(test_mode)
    # await test_calendar_processing(test_mode)
    # await test_general_processing(test_mode)
    # await test_error_handling(test_mode)

if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Run AI processor tests')
    parser.add_argument('--test-mode', action='store_true', help='Run in test mode (no data storage)')
    args = parser.parse_args()
    
    # Run tests
    asyncio.run(main(args.test_mode)) 