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
        self.tasks_dir = self.storage_dir / "tasks"
        self._ensure_storage_dirs()
        
    def _ensure_storage_dirs(self):
        """Create necessary storage directories if they don't exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_storage_path(self, item_id: str) -> Path:
        """Get the storage path for an item in the tasks folder."""
        return self.tasks_dir / f"{item_id}.json"
    
    def _generate_id(self) -> str:
        """Generate a unique ID for an item."""
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    async def save(self, data: Dict[str, Any], prompt_type: str) -> Dict[str, Any]:
        """
        Save processed data to storage using unified structure.
        
        Args:
            data: Dictionary containing processed data
            prompt_type: Type of prompt used to generate the data
            
        Returns:
            Dictionary with saved item IDs
        """
        saved_ids = []
        
        try:
            # Handle todos
            if "todos" in data:
                for todo in data["todos"]:
                    item_id = self._generate_id()
                    # Add unified fields
                    todo["id"] = item_id
                    todo["type"] = prompt_type
                    todo["created_at"] = datetime.now().isoformat()
                    todo["status"] = "active"  # Set default status
                    self._save_item(item_id, todo)
                    saved_ids.append(item_id)
            
            # Handle calendar events - convert to unified structure
            if "events" in data:
                for event in data["events"]:
                    item_id = self._generate_id()
                    # Convert event to unified structure
                    unified_item = {
                        "id": item_id,
                        "type": prompt_type,
                        "title": event.get("title", ""),
                        "description": event.get("description", ""),
                        "start_time": event.get("start_time"),
                        "end_time": event.get("end_time"),
                        "location": event.get("location"),
                        "event_type": event.get("event_type"),
                        "requires_child_attendance": event.get("requires_child_attendance", False),
                        "requires_parent_attendance": event.get("requires_parent_attendance", False),
                        "source_message": event.get("source_message", ""),
                        "created_at": datetime.now().isoformat(),
                        "status": "active"
                    }
                    self._save_item(item_id, unified_item)
                    saved_ids.append(item_id)
            
            # Handle general items - convert to unified structure
            if "items" in data:
                for item in data["items"]:
                    item_id = self._generate_id()
                    # Convert item to unified structure
                    unified_item = {
                        "id": item_id,
                        "type": prompt_type,
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                        "category": item.get("category"),
                        "importance": item.get("importance"),
                        "requires_action": item.get("requires_action", False),
                        "action_required": item.get("action_required"),
                        "source_message": item.get("source_message", ""),
                        "created_at": datetime.now().isoformat(),
                        "status": "active"
                    }
                    self._save_item(item_id, unified_item)
                    saved_ids.append(item_id)
            
            return {"items": saved_ids}
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            raise
    
    def _save_item(self, item_id: str, item_data: Dict[str, Any]):
        """Save a single item to storage in the tasks folder."""
        file_path = self._get_storage_path(item_id)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(item_data, f, indent=2, ensure_ascii=False)
    
    async def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single item from storage."""
        try:
            file_path = self._get_storage_path(item_id)
            if not file_path.exists():
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error retrieving item {item_id}: {e}")
            return None
    
    async def list_items(
        self,
        item_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List items with optional filtering by type and status.
        
        Args:
            item_type: Optional type filter ("todo", "calendar", "general", etc.)
            status: Optional status filter ("active", "completed", "dismissed")
            limit: Maximum number of items to return
            offset: Number of items to skip
            
        Returns:
            List of items matching the criteria
        """
        try:
            items = []
            
            if not self.tasks_dir.exists():
                return []
            
            # Get all JSON files in the tasks directory
            files = sorted(self.tasks_dir.glob("*.json"), reverse=True)
            
            for file_path in files:
                with open(file_path, 'r', encoding='utf-8') as f:
                    item = json.load(f)
                    
                    # Apply filters
                    if item_type and item.get("type") != item_type:
                        continue
                    if status and item.get("status") != status:
                        continue
                    
                    items.append(item)
            
            # Apply pagination
            start = offset
            end = offset + limit
            return items[start:end]
            
        except Exception as e:
            logger.error(f"Error listing items: {e}")
            return []
    
    async def update_status(self, item_id: str, new_status: str) -> bool:
        """
        Update the status of an item.
        
        Args:
            item_id: ID of the item to update
            new_status: New status ("active", "completed", or "dismissed")
            
        Returns:
            True if update was successful, False otherwise
        """
        try:
            item = await self.get(item_id)
            if not item:
                return False
            
            item["status"] = new_status
            item["updated_at"] = datetime.now().isoformat()
            
            # Save updated item
            self._save_item(item_id, item)
            return True
            
        except Exception as e:
            logger.error(f"Error updating item {item_id}: {e}")
            return False
    
    async def delete(self, item_id: str) -> bool:
        """
        Delete an item from storage.
        
        Args:
            item_id: ID of the item to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            file_path = self._get_storage_path(item_id)
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting item {item_id}: {e}")
            return False
    
    async def get_active_items_for_context(self, prompt_type: str) -> List[Dict[str, Any]]:
        """
        Get active items formatted for GPT context.
        Only returns items that are:
        - Have status "active" AND
        - Have a due_date/start_time that is today or in the future (if relevant)
        Args:
            prompt_type: Type of items to get ("todo", "calendar", "general", etc.)
        Returns:
            List of relevant active items formatted for context
        """
        try:
            today = datetime.now().date()
            relevant_items = []
            # Get all active items of the specified type
            active_items = await self.list_items(item_type=prompt_type, status="active")
            for item in active_items:
                # For todos, check due_date
                if prompt_type == "todo":
                    if "due_date" in item and item["due_date"]:
                        try:
                            due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
                            if due_date >= today:
                                relevant_items.append(item)
                        except ValueError as e:
                            continue
                    else:
                        relevant_items.append(item)
                # For calendar, check start_time
                elif prompt_type == "calendar":
                    if "start_time" in item and item["start_time"]:
                        try:
                            start_time = datetime.strptime(item["start_time"], "%Y-%m-%d %H:%M")
                            if start_time.date() >= today:
                                relevant_items.append(item)
                        except ValueError as e:
                            continue
                    else:
                        relevant_items.append(item)
                # For all other types, include all active items
                else:
                    relevant_items.append(item)
            return relevant_items
        except Exception as e:
            logger.error(f"Error getting active items for context: {e}")
            return [] 