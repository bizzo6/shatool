import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import openai
from .config import Config
from .data_store import DataStore

class MessageProcessor:
    """Processes WhatsApp messages using GPT to extract structured information."""
    
    def __init__(self, data_store: DataStore):
        self.data_store = data_store
        self.logger = logging.getLogger(__name__)
        
        # Initialize OpenAI client with API key
        if not Config.API_KEY:
            raise ValueError("OpenAI API key not found. Please set OPENAI_API_KEY in .env file")
        openai.api_key = Config.API_KEY
        
        # Load prompts and metadata
        Config.load_prompts()
        Config.load_metadata()
    
    async def process_messages(self, messages: List[Dict[str, Any]], prompt_type: str = "general") -> Dict[str, Any]:
        """
        Process a list of messages using GPT to extract structured information.
        
        Args:
            messages: List of message dictionaries with 'text' and 'timestamp' keys
            prompt_type: Type of prompt to use (todo, calendar, general)
            
        Returns:
            Dictionary containing the processed results and metadata
        """
        print("\n=== Starting process_messages ===")
        print(f"Prompt type: {prompt_type}")
        print(f"Number of messages: {len(messages)}")
        print("First message preview:", messages[0] if messages else "No messages")
        
        try:
            # Get the prompt template
            template = Config.get_prompt_template(prompt_type)
            if not template:
                raise ValueError(f"Invalid prompt type: {prompt_type}")
            
            # Format messages for the prompt
            formatted_messages = self._format_messages(messages)
            
            # Get active items for context
            active_items = await self.data_store.get_active_items_for_context(prompt_type)
            context_items = self._format_context_items(active_items)
            
            # Prepare metadata
            metadata = self._prepare_metadata()
            
            # Format the prompt with context items
            try:
                # First, prepare the metadata for formatting
                format_kwargs = {
                    'messages': formatted_messages,
                    'context_items': context_items,
                    'metadata': metadata
                }
                
                # Debug print the format arguments
                print("\nFormat arguments:")
                print(json.dumps(format_kwargs, indent=2, ensure_ascii=False))
                
                # Escape the JSON example in the template
                template = template.replace("{", "{{").replace("}", "}}")
                # Then restore the actual format placeholders
                template = template.replace("{{metadata[", "{metadata[").replace("]}}", "]}")
                template = template.replace("{{context_items}}", "{context_items}")
                template = template.replace("{{messages}}", "{messages}")
                
                # Format the template
                prompt = template.format(**format_kwargs)
                
                # Debug print the formatted prompt
                print("\nFormatted Prompt:")
                print("=" * 80)
                print(prompt)
                print("=" * 80)
                
            except KeyError as e:
                print(f"\nTemplate Format Error: Missing key {e}")
                print("Available keys in metadata:", list(metadata.keys()))
                raise
            except Exception as e:
                print(f"\nTemplate Format Error: {str(e)}")
                print("Template:", template)
                raise
            
            print("\nSending request to GPT API...")
            print("Model:", Config.MODEL)
            print("Temperature:", Config.TEMPERATURE)
            print("Max tokens:", Config.MAX_TOKENS)
            
            try:
                # Call GPT API
                response = openai.chat.completions.create(
                    model=Config.MODEL,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that extracts structured information from WhatsApp messages. Always return valid JSON by the set format. And use Hebrew for your responses."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=Config.TEMPERATURE,
                    max_tokens=Config.MAX_TOKENS,
                    response_format={"type": "json_object"}
                )
                print("Successfully received response from GPT API")
            except Exception as api_error:
                print(f"\nError calling GPT API: {str(api_error)}")
                print("API Error Type:", type(api_error).__name__)
                raise
            
            # Get the raw response content
            raw_content = response.choices[0].message.content
            print("\nRaw GPT Response:")
            print("=" * 80)
            print(raw_content)
            print("=" * 80)
            
            try:
                # Clean the response content - remove any leading/trailing whitespace and newlines
                cleaned_content = raw_content.strip()
                
                # Try to parse the response as JSON
                result = json.loads(cleaned_content)
                print("\nParsed JSON structure:")
                print(json.dumps(result, indent=2, ensure_ascii=False))
                
                # Validate that the result has the expected structure
                if prompt_type == "todo":
                    if not isinstance(result, dict):
                        raise ValueError(f"Expected JSON object, got {type(result)}")
                    if "todos" not in result:
                        print("\nResponse is missing 'todos' field. Available fields:", list(result.keys()))
                        raise ValueError("Response missing 'todos' field")
                    if not isinstance(result["todos"], list):
                        raise ValueError(f"Expected 'todos' to be a list, got {type(result['todos'])}")
                elif prompt_type == "calendar" and "events" not in result:
                    raise ValueError("Response missing 'events' field")
                elif prompt_type == "general" and "items" not in result:
                    raise ValueError("Response missing 'items' field")
                
            except json.JSONDecodeError as e:
                print(f"\nError parsing JSON response: {str(e)}")
                print("Raw response content:")
                print(raw_content)
                print("\nResponse type:", type(raw_content))
                print("Response length:", len(raw_content))
                raise ValueError(f"Invalid JSON response from GPT: {str(e)}")
            
            # Save the processed data
            saved_ids = await self.data_store.save(result)
            
            # Add metadata to the result
            result['metadata'] = {
                'processing_time': datetime.now().isoformat(),
                'prompt_type': prompt_type,
                'message_count': len(messages),
                'context_items_count': len(active_items),
                'saved_ids': saved_ids
            }
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            print(f"\nError processing messages: {error_msg}")
            print("Error Type:", type(e).__name__)
            if "todos" in error_msg:
                print("\nThis error suggests the GPT response was malformed.")
                print("The response should be a valid JSON object with a 'todos' array.")
                print("Example format:")
                print('''
{
    "todos": [
        {
            "title": "כותרת המשימה",
            "description": "תיאור מפורט",
            "due_date": "YYYY-MM-DD או null",
            "priority": "high|medium|low",
            "assigned_to": "child|parent|both",
            "context": "הקשר נוסף",
            "source_message": "טקסט ההודעה המקורית"
        }
    ]
}
                ''')
            return {
                'error': error_msg,
                'metadata': {
                    'processing_time': datetime.now().isoformat(),
                    'prompt_type': prompt_type,
                    'message_count': len(messages)
                }
            }
    
    def _format_messages(self, messages: List[Dict[str, Any]]) -> str:
        """Format messages for the prompt."""
        formatted = []
        for msg in messages:
            timestamp = datetime.fromtimestamp(msg['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            formatted.append(f"[{timestamp}] {msg['text']}")
        return "\n".join(formatted)
    
    def _format_context_items(self, items: List[Dict[str, Any]]) -> str:
        """Format active items for context in the prompt."""
        if not items:
            return "No active items found."
            
        formatted = ["Active items for context:"]
        for item in items:
            if "title" in item:
                formatted.append(f"- {item['title']}")
                if "description" in item:
                    formatted.append(f"  Description: {item['description']}")
                if "due_date" in item:
                    formatted.append(f"  Due: {item['due_date']}")
                if "priority" in item:
                    formatted.append(f"  Priority: {item['priority']}")
                formatted.append("")  # Add blank line between items
                
        return "\n".join(formatted)
    
    def _prepare_metadata(self) -> Dict[str, Any]:
        """Prepare metadata for the prompt."""
        metadata = Config.load_metadata()
        
        # Always use current date instead of metadata's today
        metadata['today'] = datetime.now().strftime('%Y-%m-%d')
        
        # Ensure all required fields exist
        if 'class_info' not in metadata:
            metadata['class_info'] = {
                'name': '',
                'teachers': []
            }
        if 'child_info' not in metadata:
            metadata['child_info'] = {
                'name': '',
                'gender': ''
            }
        if 'parent_info' not in metadata:
            metadata['parent_info'] = {
                'names': []
            }
        
        return metadata

    async def process_batch(
        self,
        message_batches: List[List[Dict[str, Any]]],
        metadata: Optional[Dict[str, Any]] = None,
        prompt_type: str = 'general'
    ) -> List[Dict[str, Any]]:
        """
        Process multiple batches of messages.
        
        Args:
            message_batches: List of message batches to process
            metadata: Optional metadata about the messages
            prompt_type: Type of processing to perform
            
        Returns:
            List of results for each batch
        """
        results = []
        for batch in message_batches:
            try:
                batch_result = await self.process_messages(batch, prompt_type)
                results.append(batch_result)
            except Exception as e:
                self.logger.error(f"Error processing batch: {e}")
                results.append({"error": str(e)})
        return results 