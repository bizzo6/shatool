import os
import json
import time
from pathlib import Path
from typing import Dict, List, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
PROJECT_ROOT = Path(__file__).parent.parent
ENV_PATH = PROJECT_ROOT / '.env'
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

class TasksManager:
    def __init__(self, data_dir: str = None):
        # Use STORAGE_DIR from environment if available, otherwise use default
        self.data_dir = Path(data_dir or os.getenv('STORAGE_DIR', 'data'))
        self.tasks_dir = self.data_dir / "tasks"
        # Create the data directory and tasks subdirectory if they don't exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
            
        # Initialize with supported task types
        self.supported_types = ["todo", "general", "calendar"]
        self.tasks: Dict[str, List[dict]] = {
            task_type: [] for task_type in self.supported_types
        }
        self.last_update = 0
        self.observer = None
        self._setup_file_watcher()
        self.refresh()

    def _setup_file_watcher(self):
        """Setup file system watcher to detect changes in data directory"""
        if self.observer is not None:
            self.cleanup()
            
        class TasksEventHandler(FileSystemEventHandler):
            def __init__(self, manager):
                self.manager = manager
                self.last_refresh = 0
                self.refresh_cooldown = 1  # Minimum seconds between refreshes

            def on_any_event(self, event):
                if not event.is_directory and event.src_path.endswith('.json'):
                    current_time = time.time()
                    if current_time - self.last_refresh >= self.refresh_cooldown:
                        self.manager.refresh()
                        self.last_refresh = current_time

        self.observer = Observer()
        self.observer.schedule(
            TasksEventHandler(self),
            str(self.tasks_dir),
            recursive=False  # Only watch the tasks directory, not subdirectories
        )
        self.observer.start()

    def _load_tasks_from_folder(self, task_type: str, limit: int = 100, offset: int = 0) -> List[dict]:
        """Load tasks of a specific type from the tasks folder with pagination"""
        tasks = []
        
        if not self.tasks_dir.exists():
            return tasks

        # Get all JSON files and sort by modification time (newest first)
        files = sorted(self.tasks_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        for file_path in files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    task = json.load(f)
                    # Only include tasks of the specified type
                    if task.get('type') == task_type:
                        tasks.append(task)
            except Exception as e:
                print(f"Error loading task from {file_path}: {e}")
        
        # Apply pagination
        start = offset
        end = offset + limit
        return tasks[start:end]

    def _find_task_file(self, task_id: str) -> Optional[Path]:
        """Find the file path for a given task ID in the tasks folder"""
        if not self.tasks_dir.exists():
            return None
            
        for file_path in self.tasks_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    task = json.load(f)
                    if task.get('id') == task_id:
                        return file_path
            except Exception as e:
                print(f"Error reading task file {file_path}: {e}")
        return None

    def update_task(self, task_id: str, updates: dict) -> bool:
        """Update task properties in the file"""
        file_path = self._find_task_file(task_id)
        if not file_path:
            return False

        try:
            # Read current task data
            with open(file_path, 'r', encoding='utf-8') as f:
                task = json.load(f)

            # Update task with new values
            for key, value in updates.items():
                if key != 'id':  # Don't allow updating the ID
                    task[key] = value

            # Add updated timestamp
            task['updated_at'] = time.time()

            # Write updated task back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(task, f, ensure_ascii=False, indent=2)

            # Refresh tasks after update
            self.refresh()
            return True
        except Exception as e:
            print(f"Error updating task {task_id}: {e}")
            return False

    def delete_task(self, task_id: str) -> bool:
        """Delete a task by removing its JSON file"""
        file_path = self._find_task_file(task_id)
        if not file_path:
            return False

        try:
            # Delete the task file
            file_path.unlink()
            # Refresh tasks after deletion
            self.refresh()
            return True
        except Exception as e:
            print(f"Error deleting task {task_id}: {e}")
            return False

    def refresh(self):
        """Refresh all tasks from the data directory"""
        for task_type in self.supported_types:
            self.tasks[task_type] = self._load_tasks_from_folder(task_type)
        self.last_update = time.time()

    def get_tasks(self, task_type: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, List[dict]]:
        """Get tasks with pagination"""
        if task_type:
            if task_type not in self.supported_types:
                return {task_type: []}
            return {task_type: self._load_tasks_from_folder(task_type, limit, offset)}
        
        result = {}
        for t_type in self.supported_types:
            result[t_type] = self._load_tasks_from_folder(t_type, limit, offset)
        return result

    def get_all_tasks(self, limit: int = 100, offset: int = 0) -> List[dict]:
        """Get all tasks regardless of type with pagination"""
        all_tasks = []
        
        if not self.tasks_dir.exists():
            return all_tasks

        # Get all JSON files and sort by modification time (newest first)
        files = sorted(self.tasks_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        # Apply pagination
        start = offset
        end = offset + limit
        paginated_files = files[start:end]

        for file_path in paginated_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    task = json.load(f)
                    all_tasks.append(task)
            except Exception as e:
                print(f"Error loading task from {file_path}: {e}")
        
        return all_tasks

    def get_tasks_by_type(self, task_type: str, limit: int = 100, offset: int = 0) -> List[dict]:
        """Get tasks of a specific type with pagination"""
        if task_type not in self.supported_types:
            return []
        return self._load_tasks_from_folder(task_type, limit, offset)

    def get_last_update(self) -> float:
        """Get timestamp of last update"""
        return self.last_update

    def cleanup(self):
        """Cleanup resources"""
        if self.observer is not None:
            try:
                self.observer.stop()
                self.observer.join(timeout=1)
            except Exception as e:
                print(f"Error stopping observer: {e}")
            finally:
                self.observer = None

    def __del__(self):
        """Cleanup observer when object is destroyed"""
        self.cleanup() 