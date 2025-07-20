import json
import uuid
import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import requests
from ai_processor.message_processor import MessageProcessor
from ai_processor.data_store import DataStore
from ai_processor.config import Config

@dataclass
class AutomationConfig:
    """Configuration for an automation job."""
    automation_id: str
    owner: str
    customer_id: str
    active: bool
    agent_group: str
    agent_peek_only: bool
    prompts: List[str]
    get_msg_minutes: int
    min_msg_count: int
    process_max_time: int

@dataclass
class AutomationLog:
    """Log entry for automation activities."""
    timestamp: str
    automation_id: str
    action: str
    message: str
    details: Optional[Dict[str, Any]] = None

@dataclass
class AutomationStatus:
    """Status information for an automation job."""
    automation_id: str
    active: bool
    last_check: Optional[str]
    last_process: Optional[str]
    messages_checked: int
    messages_processed: int
    errors_count: int
    is_running: bool
    logs: List[AutomationLog]

class AutomationManager:
    """Manages automated message processing based on configuration files."""
    
    def __init__(self, automation_dir: Path, agent_host: str = None):
        self.automation_dir = automation_dir
        self.automation_dir.mkdir(parents=True, exist_ok=True)
        
        # Use provided agent_host or get from environment variable
        if agent_host is None:
            self.agent_host = os.getenv('AGENT_HOST', 'https://agent.shatool.dad')
        else:
            self.agent_host = agent_host
        
        # Initialize AI processor
        project_root = Path(__file__).parent.parent
        data_dir = project_root / "data"
        self.ai_processor = MessageProcessor(DataStore(storage_dir=str(data_dir)))
        
        # Active automation threads
        self.active_threads: Dict[str, threading.Thread] = {}
        self.stop_events: Dict[str, threading.Event] = {}
        self.automation_configs: Dict[str, AutomationConfig] = {}
        self.automation_logs: Dict[str, List[AutomationLog]] = {}
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
    def load_configurations(self) -> Dict[str, AutomationConfig]:
        """Load all automation configurations from JSON files."""
        configs = {}
        
        for config_file in self.automation_dir.glob("*.json"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    config = AutomationConfig(**data)
                    configs[config.automation_id] = config
                    self.logger.info(f"Loaded automation config: {config.automation_id}")
            except Exception as e:
                self.logger.error(f"Failed to load config {config_file.name}: {e}")
                
        self.automation_configs = configs
        return configs
    
    def save_configuration(self, config: AutomationConfig) -> bool:
        """Save an automation configuration to a JSON file."""
        try:
            config_file = self.automation_dir / f"{config.automation_id}.json"
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(config), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self.logger.error(f"Failed to save config {config.automation_id}: {e}")
            return False
    
    def create_configuration(self, owner: str, customer_id: str, agent_group: str, 
                           prompts: List[str], **kwargs) -> AutomationConfig:
        """Create a new automation configuration."""
        config = AutomationConfig(
            automation_id=str(uuid.uuid4()),
            owner=owner,
            customer_id=customer_id,
            active=kwargs.get('active', True),
            agent_group=agent_group,
            agent_peek_only=kwargs.get('agent_peek_only', False),
            prompts=prompts,
            get_msg_minutes=kwargs.get('get_msg_minutes', 5),
            min_msg_count=kwargs.get('min_msg_count', 1),
            process_max_time=kwargs.get('process_max_time', 30)
        )
        
        if self.save_configuration(config):
            self.automation_configs[config.automation_id] = config
            self.log_activity(config.automation_id, "created", "Configuration created")
            
        return config
    
    def delete_configuration(self, automation_id: str) -> bool:
        """Delete an automation configuration."""
        if automation_id in self.active_threads:
            self.stop_automation(automation_id)
            
        config_file = self.automation_dir / f"{automation_id}.json"
        if config_file.exists():
            config_file.unlink()
            
        if automation_id in self.automation_configs:
            del self.automation_configs[automation_id]
            
        if automation_id in self.automation_logs:
            del self.automation_logs[automation_id]
            
        self.log_activity(automation_id, "deleted", "Configuration deleted")
        return True
    
    def log_activity(self, automation_id: str, action: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Log an activity for an automation job."""
        if automation_id not in self.automation_logs:
            self.automation_logs[automation_id] = []
        log_entry = AutomationLog(
            timestamp=datetime.now().isoformat(),
            automation_id=automation_id,
            action=action,
            message=message,
            details=details
        )
        self.automation_logs[automation_id].append(log_entry)
        # Keep only last 2 hours of logs
        cutoff_time = datetime.now() - timedelta(hours=2)
        self.automation_logs[automation_id] = [
            log for log in self.automation_logs[automation_id]
            if datetime.fromisoformat(log.timestamp) > cutoff_time
        ]
        # Verbose log to Flask output
        self.logger.info(f"[AUTOMATION] {automation_id} | {action} | {message} | {details}")

    async def check_messages_count(self, agent_group: str) -> int:
        """Check the number of messages waiting in the agent queue."""
        url = f"{self.agent_host}/api/peekMessages/{agent_group}"
        payload = {'token': os.getenv('API_TOKEN')}
        self.logger.info(f"[AUTOMATION] [REQUEST] POST {url}")
        self.logger.info(f"[AUTOMATION] [REQUEST] Payload: {payload}")
        try:
            response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
            self.logger.info(f"[AUTOMATION] [RESPONSE] Status: {response.status_code}")
            self.logger.info(f"[AUTOMATION] [RESPONSE] Body: {response.text}")
            if response.status_code == 200:
                data = response.json()
                count = len(data.get('messages', []))
                self.logger.info(f"[AUTOMATION] Message count for group {agent_group}: {count}")
                return count
            else:
                self.logger.error(f"[AUTOMATION] Failed to check messages count: {response.status_code} {response.text}")
                return 0
        except Exception as e:
            self.logger.error(f"[AUTOMATION] Error checking messages count: {e}")
            return 0

    async def get_messages(self, agent_group: str, peek_only: bool = False) -> List[Dict]:
        """Get messages from the agent."""
        if peek_only:
            # Use peek endpoint - messages stay in queue
            url = f"{self.agent_host}/api/peekMessages/{agent_group}"
            self.logger.info(f"[AUTOMATION] [REQUEST] GET messages (peek) - POST {url}")
        else:
            # Use get endpoint - messages are removed from queue
            url = f"{self.agent_host}/api/getMessages/{agent_group}"
            self.logger.info(f"[AUTOMATION] [REQUEST] GET messages (remove) - POST {url}")
        
        payload = {'token': os.getenv('API_TOKEN')}
        self.logger.info(f"[AUTOMATION] [REQUEST] Payload: {payload}")
        try:
            response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
            self.logger.info(f"[AUTOMATION] [RESPONSE] Status: {response.status_code}")
            self.logger.info(f"[AUTOMATION] [RESPONSE] Body: {response.text}")
            if response.status_code == 200:
                data = response.json()
                messages = data.get('messages', [])
                action = "peeked" if peek_only else "retrieved and removed"
                self.logger.info(f"[AUTOMATION] {action} {len(messages)} messages from group {agent_group}")
                return messages
            else:
                self.logger.error(f"[AUTOMATION] Failed to get messages: {response.status_code} {response.text}")
                return []
        except Exception as e:
            self.logger.error(f"[AUTOMATION] Error getting messages: {e}")
            return []

    def process_automation(self, config: AutomationConfig):
        """Process automation for a specific configuration."""
        automation_id = config.automation_id
        last_process_time = None
        consecutive_checks = 0
        self.logger.info(f"[AUTOMATION] Starting automation: {automation_id} | Config: {config}")
        self.log_activity(automation_id, "started", "Automation job started", {"config": asdict(config)})
        
        while automation_id in self.automation_configs and self.automation_configs[automation_id].active:
            try:
                # Always get the latest config from memory
                current_config = self.automation_configs[automation_id]
                self.logger.info(f"[AUTOMATION] {automation_id} | Using config: agent_peek_only={current_config.agent_peek_only}")
                
                if automation_id in self.stop_events and self.stop_events[automation_id].is_set():
                    self.logger.info(f"[AUTOMATION] Stop event set for {automation_id}, exiting loop.")
                    break
                
                # Check message count
                message_count = asyncio.run(self.check_messages_count(current_config.agent_group))
                consecutive_checks += 1
                self.logger.info(f"[AUTOMATION] {automation_id} | Message count: {message_count} | Min required: {current_config.min_msg_count}")
                self.log_activity(automation_id, "check", f"Found {message_count} messages", {"message_count": message_count, "min_required": current_config.min_msg_count})
                
                should_process = False
                if message_count >= current_config.min_msg_count:
                    should_process = True
                elif message_count > 0 and consecutive_checks * current_config.get_msg_minutes >= current_config.process_max_time:
                    should_process = True
                    self.logger.info(f"[AUTOMATION] {automation_id} | Processing due to timeout.")
                    self.log_activity(automation_id, "timeout", f"Processing due to timeout ({consecutive_checks * current_config.get_msg_minutes} minutes)")
                
                if should_process:
                    messages = asyncio.run(self.get_messages(current_config.agent_group, current_config.agent_peek_only))
                    self.logger.info(f"[AUTOMATION] {automation_id} | Fetched {len(messages)} messages for processing.")
                    if messages:
                        self.log_activity(automation_id, "process", f"Processing {len(messages)} messages", {"messages": messages})
                        for prompt_type in current_config.prompts:
                            try:
                                self.logger.info(f"[AUTOMATION] {automation_id} | Running prompt: {prompt_type} | Messages: {len(messages)}")
                                result = asyncio.run(self.ai_processor.process_messages(messages, prompt_type=prompt_type))
                                todos = result.get('todos', [])
                                self.logger.info(f"[AUTOMATION] {automation_id} | Prompt: {prompt_type} | Generated {len(todos)} items.")
                                self.log_activity(automation_id, "processed", f"Processed with {prompt_type}", {"prompt_type": prompt_type, "result_count": len(todos), "result": result})
                            except Exception as e:
                                self.logger.error(f"[AUTOMATION] {automation_id} | Error running prompt {prompt_type}: {e}")
                                self.log_activity(automation_id, "error", f"Failed to process with {prompt_type}: {str(e)}")
                        last_process_time = datetime.now().isoformat()
                        consecutive_checks = 0
                    else:
                        self.logger.warning(f"[AUTOMATION] {automation_id} | No messages retrieved despite count > 0")
                        self.log_activity(automation_id, "warning", "No messages retrieved despite count > 0")
                
                time.sleep(current_config.get_msg_minutes * 60)
            except Exception as e:
                self.logger.error(f"[AUTOMATION] {automation_id} | Automation error: {e}")
                self.log_activity(automation_id, "error", f"Automation error: {str(e)}")
                time.sleep(60)
        
        self.logger.info(f"[AUTOMATION] {automation_id} | Automation job stopped.")
        self.log_activity(automation_id, "stopped", "Automation job stopped")
    
    def start_automation(self, automation_id: str) -> bool:
        """Start a specific automation job."""
        if automation_id not in self.automation_configs:
            return False
            
        if automation_id in self.active_threads:
            return False  # Already running
            
        config = self.automation_configs[automation_id]
        if not config.active:
            return False
            
        stop_event = threading.Event()
        self.stop_events[automation_id] = stop_event
        thread = threading.Thread(target=self.process_automation, args=(config,), daemon=True)
        self.active_threads[automation_id] = thread
        thread.start()
        return True
    
    def stop_automation(self, automation_id: str) -> bool:
        """Stop a specific automation job."""
        if automation_id in self.active_threads:
            stop_event = self.stop_events[automation_id]
            stop_event.set()
            del self.active_threads[automation_id]
            del self.stop_events[automation_id]
            return True
        return False
    
    def start_all_automations(self) -> Dict[str, bool]:
        """Start all active automation jobs."""
        results = {}
        for automation_id in self.automation_configs:
            results[automation_id] = self.start_automation(automation_id)
        return results
    
    def stop_all_automations(self) -> Dict[str, bool]:
        """Stop all automation jobs."""
        results = {}
        for automation_id in list(self.active_threads.keys()):
            results[automation_id] = self.stop_automation(automation_id)
        return results
    
    def get_status(self) -> Dict[str, AutomationStatus]:
        """Get status of all automation jobs."""
        statuses = {}
        
        for automation_id, config in self.automation_configs.items():
            logs = self.automation_logs.get(automation_id, [])
            
            # Find last check and process times
            last_check = None
            last_process = None
            messages_checked = 0
            messages_processed = 0
            errors_count = 0
            
            for log in logs:
                if log.action == "check":
                    last_check = log.timestamp
                    if log.details and "message_count" in log.details:
                        messages_checked += log.details["message_count"]
                elif log.action == "processed":
                    last_process = log.timestamp
                    if log.details and "result_count" in log.details:
                        messages_processed += log.details["result_count"]
                elif log.action == "error":
                    errors_count += 1
            
            # Calculate next trigger time
            next_trigger = self._calculate_next_trigger(config, last_check)
            
            status = AutomationStatus(
                automation_id=automation_id,
                active=config.active,
                last_check=last_check,
                last_process=last_process,
                messages_checked=messages_checked,
                messages_processed=messages_processed,
                errors_count=errors_count,
                is_running=automation_id in self.active_threads,
                logs=logs
            )
            
            statuses[automation_id] = status
            
        return statuses
    
    def _calculate_next_trigger(self, config: AutomationConfig, last_check: Optional[str]) -> Optional[str]:
        """Calculate when the next trigger will happen based on last check time."""
        if not config.active or not last_check:
            return None
            
        try:
            last_check_time = datetime.fromisoformat(last_check)
            next_trigger_time = last_check_time + timedelta(minutes=config.get_msg_minutes)
            return next_trigger_time.isoformat()
        except Exception:
            return None
    
    def get_detailed_status(self, automation_id: str) -> Optional[Dict]:
        """Get detailed status for a specific automation job."""
        if automation_id not in self.automation_configs:
            return None
            
        config = self.automation_configs[automation_id]
        logs = self.automation_logs.get(automation_id, [])
        
        # Calculate statistics
        total_checks = sum(1 for log in logs if log.action == "check")
        total_processes = sum(1 for log in logs if log.action == "processed")
        total_errors = sum(1 for log in logs if log.action == "error")
        
        # Get recent activity (last 10 logs)
        recent_logs = logs[-10:] if logs else []
        
        # Calculate next trigger
        last_check = next((log.timestamp for log in reversed(logs) if log.action == "check"), None)
        next_trigger = self._calculate_next_trigger(config, last_check)
        
        return {
            "automation_id": automation_id,
            "config": {
                "owner": config.owner,
                "customer_id": config.customer_id,
                "agent_group": config.agent_group,
                "prompts": config.prompts,
                "get_msg_minutes": config.get_msg_minutes,
                "min_msg_count": config.min_msg_count,
                "process_max_time": config.process_max_time,
                "agent_peek_only": config.agent_peek_only
            },
            "status": {
                "active": config.active,
                "is_running": automation_id in self.active_threads,
                "last_check": last_check,
                "next_trigger": next_trigger,
                "last_process": next((log.timestamp for log in reversed(logs) if log.action == "processed"), None)
            },
            "statistics": {
                "total_checks": total_checks,
                "total_processes": total_processes,
                "total_errors": total_errors,
                "messages_checked": sum(log.details.get("message_count", 0) for log in logs if log.action == "check" and log.details),
                "messages_processed": sum(log.details.get("result_count", 0) for log in logs if log.action == "processed" and log.details)
            },
            "recent_logs": [
                {
                    "timestamp": log.timestamp,
                    "action": log.action,
                    "message": log.message,
                    "details": log.details
                }
                for log in recent_logs
            ]
        }
    
    def refresh_configurations(self) -> Dict[str, AutomationConfig]:
        """Reload all configurations from disk."""
        return self.load_configurations() 