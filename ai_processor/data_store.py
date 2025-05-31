import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class DataStore:
    def __init__(self, storage_dir: str = "data"):
        self.storage_dir = Path(storage_dir)
        # Map item types to their storage folder names
        self.type_to_folder = {
            "todo": "todo",
            "calendar": "calendar",
            "general": "general"
        }
        self._ensure_storage_dirs()
        
    def _ensure_storage_dirs(self):
        """Create necessary storage directories if they don't exist."""
        dirs = [
            self.storage_dir,
            self.storage_dir / "todo",
            self.storage_dir / "calendar",
            self.storage_dir / "general"
        ]
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def _get_storage_path(self, item_type: str, item_id: str) -> Path:
        """Get the storage path for an item."""
        folder_name = self.type_to_folder.get(item_type, item_type)
        return self.storage_dir / folder_name / f"{item_id}.json"
    
    def _generate_id(self) -> str:
        """Generate a unique ID for an item."""
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    async def save(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save processed data to storage.
        
        Args:
            data: Dictionary containing processed data
            
        Returns:
            Dictionary with saved item IDs
        """
        saved_ids = {}
        
        try:
            # Handle todos
            if "todos" in data:
                for todo in data["todos"]:
                    todo_id = self._generate_id()
                    todo["id"] = todo_id
                    todo["created_at"] = datetime.now().isoformat()
                    todo["status"] = "active"  # Set default status
                    self._save_item("todo", todo_id, todo)
                saved_ids["todos"] = [todo["id"] for todo in data["todos"]]
            
            # Handle calendar events
            if "events" in data:
                for event in data["events"]:
                    event_id = self._generate_id()
                    event["id"] = event_id
                    event["created_at"] = datetime.now().isoformat()
                    event["status"] = "active"  # Set default status
                    self._save_item("calendar", event_id, event)
                saved_ids["events"] = [event["id"] for event in data["events"]]
            
            # Handle general items
            if "items" in data:
                for item in data["items"]:
                    item_id = self._generate_id()
                    item["id"] = item_id
                    item["created_at"] = datetime.now().isoformat()
                    item["status"] = "active"  # Set default status
                    self._save_item("general", item_id, item)
                saved_ids["items"] = [item["id"] for item in data["items"]]
            
            return saved_ids
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            raise
    
    def _save_item(self, item_type: str, item_id: str, item_data: Dict[str, Any]):
        """Save a single item to storage."""
        file_path = self._get_storage_path(item_type, item_id)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(item_data, f, indent=2, ensure_ascii=False)
    
    async def get(self, item_type: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single item from storage."""
        try:
            file_path = self._get_storage_path(item_type, item_id)
            if not file_path.exists():
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error retrieving item {item_id}: {e}")
            return None
    
    async def list_items(
        self,
        item_type: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List items of a specific type with pagination and optional status filter.
        
        Args:
            item_type: Type of items to list ("todo", "calendar", or "general")
            status: Optional status filter ("active", "completed", "dismissed")
            limit: Maximum number of items to return
            offset: Number of items to skip
            
        Returns:
            List of items matching the criteria
        """
        try:
            items = []
            type_dir = self.storage_dir / item_type
            
            if not type_dir.exists():
                return []
            
            # Get all JSON files in the directory
            files = sorted(type_dir.glob("*.json"), reverse=True)
            
            for file_path in files:
                with open(file_path, 'r', encoding='utf-8') as f:
                    item = json.load(f)
                    if status is None or item.get("status") == status:
                        items.append(item)
            
            # Apply pagination
            start = offset
            end = offset + limit
            return items[start:end]
            
        except Exception as e:
            logger.error(f"Error listing {item_type} items: {e}")
            return []
    
    async def update_status(
        self,
        item_type: str,
        item_id: str,
        new_status: str
    ) -> bool:
        """
        Update the status of an item.
        
        Args:
            item_type: Type of item ("todo", "calendar", or "general")
            item_id: ID of the item to update
            new_status: New status ("active", "completed", or "dismissed")
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            item = await self.get(item_type, item_id)
            if not item:
                return False
            
            item["status"] = new_status
            item["updated_at"] = datetime.now().isoformat()
            
            # Save updated item
            self._save_item(item_type, item_id, item)
            return True
            
        except Exception as e:
            logger.error(f"Error updating item {item_id}: {e}")
            return False
    
    async def delete(self, item_type: str, item_id: str) -> bool:
        """
        Delete an item from storage.
        
        Args:
            item_type: Type of item ("todo", "calendar", or "general")
            item_id: ID of the item to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            file_path = self._get_storage_path(item_type, item_id)
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting item {item_id}: {e}")
            return False
    
    async def get_active_items_for_context(self, item_type: str) -> List[Dict[str, Any]]:
        """
        Get active items formatted for GPT context.
        Only returns items that are:
        - Have status "active" AND
        - Have a due_date/start_time that is today or in the future
        
        Args:
            item_type: Type of items to get ("todo", "calendar", or "general")
            
        Returns:
            List of relevant active items formatted for context
        """
        try:
            today = datetime.now().date()
            relevant_items = []
            
            # Get all active items
            active_items = await self.list_items(item_type, status="active")
            logger.info(f"Found {len(active_items)} active items of type {item_type}")
            
            for item in active_items:
                # For todos, check due_date
                if item_type == "todo":
                    if "due_date" in item and item["due_date"]:
                        try:
                            due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
                            if due_date >= today:
                                relevant_items.append(item)
                        except ValueError as e:
                            logger.warning(f"Invalid due_date format in item {item.get('id')}: {e}")
                    else:
                        # Include todos without due date
                        relevant_items.append(item)
                
                # For calendar events, check start_time
                elif item_type == "calendar" and "start_time" in item:
                    try:
                        start_time = datetime.strptime(item["start_time"], "%Y-%m-%d %H:%M").date()
                        if start_time >= today:
                            relevant_items.append(item)
                    except ValueError as e:
                        logger.warning(f"Invalid start_time format in item {item.get('id')}: {e}")
                
                # For general items, include if they have no date or future date
                elif item_type == "general":
                    if "due_date" in item and item["due_date"]:
                        try:
                            due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
                            if due_date >= today:
                                relevant_items.append(item)
                        except ValueError as e:
                            logger.warning(f"Invalid due_date format in item {item.get('id')}: {e}")
                    else:
                        # Include general items without due date
                        relevant_items.append(item)
            
            logger.info(f"Returning {len(relevant_items)} relevant items for context")
            return relevant_items
            
        except Exception as e:
            logger.error(f"Error getting active items for context: {e}")
            return [] 