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
        # Create the data directory and its subdirectories if they don't exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for subdir in ['todo', 'general', 'calendar']:
            (self.data_dir / subdir).mkdir(parents=True, exist_ok=True)
            
        self.tasks: Dict[str, List[dict]] = {
            "todo": [],
            "general": [],
            "calendar": []
        }
        self.last_update = 0
        self._setup_file_watcher()
        self.refresh()

    def _setup_file_watcher(self):
        """Setup file system watcher to detect changes in data directory"""
        class TasksEventHandler(FileSystemEventHandler):
            def __init__(self, manager):
                self.manager = manager

            def on_any_event(self, event):
                if not event.is_directory and event.src_path.endswith('.json'):
                    self.manager.refresh()

        self.observer = Observer()
        self.observer.schedule(
            TasksEventHandler(self),
            str(self.data_dir),
            recursive=True
        )
        self.observer.start()

    def _load_tasks_from_folder(self, task_type: str) -> List[dict]:
        """Load all tasks from a specific type folder"""
        tasks = []
        type_dir = self.data_dir / task_type
        
        if not type_dir.exists():
            return tasks

        for file_path in type_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    task = json.load(f)
                    tasks.append(task)
            except Exception as e:
                print(f"Error loading task from {file_path}: {e}")
        
        return tasks

    def _find_task_file(self, task_id: str) -> Optional[Path]:
        """Find the file path for a given task ID"""
        for task_type in self.tasks.keys():
            type_dir = self.data_dir / task_type
            if not type_dir.exists():
                continue
            for file_path in type_dir.glob("*.json"):
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
        for task_type in self.tasks.keys():
            self.tasks[task_type] = self._load_tasks_from_folder(task_type)
        self.last_update = time.time()

    def get_tasks(self, task_type: Optional[str] = None) -> Dict[str, List[dict]]:
        """Get all tasks or tasks of a specific type"""
        if task_type:
            return {task_type: self.tasks.get(task_type, [])}
        return self.tasks

    def get_last_update(self) -> float:
        """Get timestamp of last update"""
        return self.last_update

    def __del__(self):
        """Cleanup observer when object is destroyed"""
        if hasattr(self, 'observer'):
            self.observer.stop()
            self.observer.join() 