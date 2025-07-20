from flask import Flask, render_template, jsonify, request
from flask_talisman import Talisman
from flask_basicauth import BasicAuth
import requests
from lib.tasks_manager import TasksManager
import json
from ai_processor.message_processor import MessageProcessor
from ai_processor.data_store import DataStore
from pathlib import Path
import time
import os
from dotenv import load_dotenv
from lib.prompt_manager import PromptManager
from models.prompt import Prompt
from functools import wraps
import psutil
import gc
import logging
from datetime import datetime
import atexit
import signal
from ai_processor.config import Config
from lib.automation_manager import AutomationManager

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure Basic Auth
app.config['BASIC_AUTH_USERNAME'] = os.getenv('BASIC_AUTH_USERNAME')
app.config['BASIC_AUTH_PASSWORD'] = os.getenv('BASIC_AUTH_PASSWORD')
app.config['BASIC_AUTH_ENABLED'] = os.getenv('BASIC_AUTH_ENABLED', 'true').lower() == 'true'
basic_auth = BasicAuth(app)

# List of paths that should be accessible without authentication
PUBLIC_PATHS = [
    '/static/manifest.json',
    '/static/sw.js',
    '/static/icon-144x144.png',
    '/static/icon-192x192.png',
    '/static/icon-512x512.png',
    '/static/manifest.json',
    '/manifest.json',  # Root path for manifest
    '/sw.js',         # Root path for service worker
    '/offline.html'   # Offline page
]

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if app.config['BASIC_AUTH_ENABLED']:
            # Check if the current path should be public
            if not any(request.path.startswith(path) for path in PUBLIC_PATHS):
                return basic_auth.required(f)(*args, **kwargs)
        return f(*args, **kwargs)
    return decorated

# Get environment variables
API_TOKEN = os.getenv('API_TOKEN')
AGENT_HOST = os.getenv('AGENT_HOST', 'https://agent.shatool.dad')

SELF = "'self'"
TAILWIND = "https://cdn.tailwindcss.com"
talisman_csp = {
    'default-src': [SELF],
    'script-src': [SELF, TAILWIND, "'unsafe-inline'"],
    'style-src': [SELF, TAILWIND, "'unsafe-inline'"],
    'img-src': [SELF, "data:"],
    'connect-src': [SELF, TAILWIND]  # Allow connections to Tailwind CDN
}
Talisman(app, content_security_policy=talisman_csp)

# Initialize tasks manager
tasks_manager = TasksManager()
app.tasks_manager = tasks_manager  # Store reference in app for cleanup

# Initialize AI processor
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
ai_processor = MessageProcessor(DataStore(storage_dir=str(DATA_DIR)))

# Initialize prompt manager
prompt_manager = PromptManager(Config.PROMPTS_DIR)

# Initialize automation manager
automation_manager = AutomationManager(PROJECT_ROOT / "data" / "automation", AGENT_HOST)

# Configure Flask to handle Hebrew text properly
app.json.ensure_ascii = False

# Color palette for Tailwind (for reference in templates):
# FCF3EA - background
# 104F6A - text
# DF7833 - accent
# 30A8A5 - secondary
# FDC399 - highlight

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_memory_usage():
    """Log current memory usage"""
    process = psutil.Process()
    memory_info = process.memory_info()
    logger.info(f"Memory Usage - RSS: {memory_info.rss / 1024 / 1024:.2f}MB, "
                f"Percent: {process.memory_percent():.2f}%, "
                f"Time: {datetime.now().isoformat()}")

@app.before_request
def before_request():
    """Log memory usage before each request"""
    log_memory_usage()

@app.route('/')
@require_auth
def home():
    # Get WhatsApp client status from agent host
    try:
        resp = requests.get(f'{AGENT_HOST}/status', timeout=2)
        status = resp.json()
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    
    # Get all tasks
    tasks = tasks_manager.get_tasks()
    return render_template('home.html', status=status, tasks=tasks, active_page='home')

@app.route('/settings')
@require_auth
def settings():
    try:
        resp = requests.get('http://localhost:3000/status', timeout=2)
        status = resp.json()
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    return render_template('settings.html', status=status, active_page='settings')

@app.route('/prompts')
@require_auth
def prompts():
    return render_template('prompts.html', active_page='prompts')

@app.route('/todo')
@require_auth
def todo():
    return render_template('todo.html', active_page='todo')

@app.route('/calendar')
@require_auth
def calendar():
    return render_template('calendar.html', active_page='calendar')

@app.route('/automation')
@require_auth
def automation():
    return render_template('automation.html', active_page='automation')

@app.route('/debug')
@require_auth
def debug():
    return render_template('debug.html', active_page='debug')

@app.route('/api/tasks')
@require_auth
def get_tasks():
    """API endpoint to get all tasks"""
    task_type = request.args.get('type')
    tasks = tasks_manager.get_tasks(task_type)
    return jsonify({
        'tasks': tasks,
        'last_update': tasks_manager.get_last_update()
    })

@app.route('/api/tasks/refresh', methods=['POST'])
@require_auth
def refresh_tasks():
    """API endpoint to manually refresh tasks"""
    tasks_manager.refresh()
    return jsonify({
        'success': True,
        'last_update': tasks_manager.get_last_update()
    })

@app.route('/api/tasks/set/<task_id>', methods=['POST'])
@require_auth
def update_task(task_id):
    """API endpoint to update task properties"""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400

    updates = request.get_json()
    if not updates:
        return jsonify({'error': 'No update data provided'}), 400

    success = tasks_manager.update_task(task_id, updates)
    if success:
        return jsonify({
            'success': True,
            'message': 'Task updated successfully',
            'last_update': tasks_manager.get_last_update()
        })
    else:
        return jsonify({'error': 'Task not found or update failed'}), 404

@app.route('/api/tasks/remove/<task_id>', methods=['DELETE'])
@require_auth
def delete_task(task_id):
    """API endpoint to delete a task"""
    success = tasks_manager.delete_task(task_id)
    if success:
        return jsonify({
            'success': True,
            'message': 'Task deleted successfully',
            'last_update': tasks_manager.get_last_update()
        })
    else:
        return jsonify({'error': 'Task not found or deletion failed'}), 404

@app.route('/api/process/<template>', methods=['POST'])
@require_auth
def process_messages(template):
    """
    Process messages using AI processor with specified template.
    
    Args:
        template: Type of processing to perform ('todo', 'calendar', or 'general')
    
    Request body:
        {
            "messages": [
                {
                    "from": "sender name",
                    "time": timestamp or "now",
                    "text": "message content"
                },
                ...
            ]
        }
    """
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.get_json()
    if not data or 'messages' not in data:
        return jsonify({'error': 'No messages provided'}), 400
    
    # Validate template type
    available_prompts = Config.list_available_prompts()
    if template not in available_prompts:
        return jsonify({'error': f'Invalid template. Must be one of: {", ".join(available_prompts.keys())}'}), 400
    
    try:
        # Process messages, replacing "now" with current timestamp and mapping time to timestamp
        messages = data['messages']
        for message in messages:
            if message.get('time') == 'now':
                message['time'] = int(time.time())
            # Map 'time' to 'timestamp' for AI processor compatibility
            message['timestamp'] = message.pop('time')
        
        # Process messages using AI processor
        import asyncio
        result = asyncio.run(ai_processor.process_messages(messages, prompt_type=template))
        
        # Return the full processing result
        return jsonify({
            'success': True,
            'result': result,
            'template': template
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'type': type(e).__name__
        }), 500

@app.route('/api/messages/get/<groupid>', methods=['GET'])
@require_auth
def get_messages(groupid):
    """
    Proxy endpoint to get messages from a specific group using the agent interface.
    
    Args:
        groupid: The ID of the group to get messages from
    
    Returns:
        The response from the agent interface
    """
    if not API_TOKEN:
        return jsonify({'error': 'API token not configured'}), 500
    
    try:
        # Construct the full URL for the agent endpoint
        agent_url = f"{AGENT_HOST}/api/getMessages/{groupid}"
        
        # Make the request to the agent interface
        response = requests.post(
            agent_url,
            json={'token': API_TOKEN},
            headers={'Content-Type': 'application/json'}
        )
        
        # Forward the response status code and content
        return response.content, response.status_code, {'Content-Type': 'application/json'}
        
    except requests.RequestException as e:
        return jsonify({
            'error': f'Failed to communicate with agent interface: {str(e)}',
            'type': type(e).__name__
        }), 500

@app.route('/api/messages/peek/<groupid>', methods=['GET'])
@require_auth
def peek_messages(groupid):
    """
    Proxy endpoint to peek messages from a specific group using the agent interface.
    
    Args:
        groupid: The ID of the group to peek messages from
    
    Returns:
        The response from the agent interface
    """
    if not API_TOKEN:
        return jsonify({'error': 'API token not configured'}), 500
    
    try:
        # Construct the full URL for the agent endpoint
        agent_url = f"{AGENT_HOST}/api/peekMessages/{groupid}"
        
        # Make the request to the agent interface
        response = requests.post(
            agent_url,
            json={'token': API_TOKEN},
            headers={'Content-Type': 'application/json'}
        )
        
        # Forward the response status code and content
        return response.content, response.status_code, {'Content-Type': 'application/json'}
        
    except requests.RequestException as e:
        return jsonify({
            'error': f'Failed to communicate with agent interface: {str(e)}',
            'type': type(e).__name__
        }), 500

@app.route('/api/prompts', methods=['GET'])
@require_auth
def list_prompts():
    """Get all available prompts"""
    prompts = prompt_manager.get_all_prompts()
    return jsonify({
        'prompts': [p.to_dict() for p in prompts]
    })

@app.route('/api/prompts/<name>', methods=['GET'])
@require_auth
def get_prompt(name):
    """Get a specific prompt by name"""
    prompt = prompt_manager.get_prompt(name)
    if not prompt:
        return jsonify({'error': 'Prompt not found'}), 404
    return jsonify(prompt.to_dict())

@app.route('/api/prompts', methods=['POST'])
@require_auth
def create_prompt():
    """Create a new prompt"""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
        
    data = request.get_json()
    try:
        prompt = Prompt.from_dict(data)
        if prompt_manager.save_prompt(prompt):
            return jsonify(prompt.to_dict()), 201
        return jsonify({'error': 'Failed to save prompt'}), 500
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

@app.route('/api/prompts/<name>', methods=['PUT'])
@require_auth
def update_prompt(name):
    """Update an existing prompt"""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
        
    data = request.get_json()
    data['name'] = name  # Ensure name matches URL parameter
    
    try:
        prompt = Prompt.from_dict(data)
        if prompt_manager.save_prompt(prompt):
            return jsonify(prompt.to_dict())
        return jsonify({'error': 'Failed to update prompt'}), 500
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

@app.route('/api/prompts/<name>', methods=['DELETE'])
@require_auth
def delete_prompt(name):
    """Delete a prompt"""
    if prompt_manager.delete_prompt(name):
        return jsonify({'success': True})
    return jsonify({'error': 'Prompt not found'}), 404

@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js')

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/offline.html')
def offline():
    return app.send_static_file('offline.html')

@app.route('/api/debug/memory')
@require_auth
def memory_debug():
    """API endpoint to get memory usage information"""
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        return jsonify({
            'rss_mb': memory_info.rss / 1024 / 1024,
            'percent': process.memory_percent(),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Automation Management API Endpoints
@app.route('/api/automation')
@require_auth
def list_automations():
    """API endpoint to list all automation configurations"""
    try:
        configs = automation_manager.load_configurations()
        return jsonify({
            'automations': {
                automation_id: {
                    'automation_id': config.automation_id,
                    'owner': config.owner,
                    'customer_id': config.customer_id,
                    'active': config.active,
                    'agent_group': config.agent_group,
                    'agent_peek_only': config.agent_peek_only,
                    'prompts': config.prompts,
                    'get_msg_minutes': config.get_msg_minutes,
                    'min_msg_count': config.min_msg_count,
                    'process_max_time': config.process_max_time
                }
                for automation_id, config in configs.items()
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/<automation_id>', methods=['GET'])
@require_auth
def get_automation(automation_id):
    """API endpoint to get a specific automation configuration"""
    try:
        configs = automation_manager.load_configurations()
        if automation_id not in configs:
            return jsonify({'error': 'Automation not found'}), 404
            
        config = configs[automation_id]
        return jsonify({
            'automation_id': config.automation_id,
            'owner': config.owner,
            'customer_id': config.customer_id,
            'active': config.active,
            'agent_group': config.agent_group,
            'agent_peek_only': config.agent_peek_only,
            'prompts': config.prompts,
            'get_msg_minutes': config.get_msg_minutes,
            'min_msg_count': config.min_msg_count,
            'process_max_time': config.process_max_time
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation', methods=['POST'])
@require_auth
def create_automation():
    """API endpoint to create a new automation configuration"""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
        
    try:
        data = request.get_json()
        required_fields = ['owner', 'customer_id', 'agent_group', 'prompts']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        config = automation_manager.create_configuration(
            owner=data['owner'],
            customer_id=data['customer_id'],
            agent_group=data['agent_group'],
            prompts=data['prompts'],
            active=data.get('active', True),
            agent_peek_only=data.get('agent_peek_only', False),
            get_msg_minutes=data.get('get_msg_minutes', 5),
            min_msg_count=data.get('min_msg_count', 1),
            process_max_time=data.get('process_max_time', 30)
        )
        
        return jsonify({
            'success': True,
            'automation_id': config.automation_id,
            'message': 'Automation created successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/<automation_id>', methods=['PUT'])
@require_auth
def update_automation(automation_id):
    """API endpoint to update an automation configuration"""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
        
    try:
        data = request.get_json()
        configs = automation_manager.load_configurations()
        
        if automation_id not in configs:
            return jsonify({'error': 'Automation not found'}), 404
            
        # Update the configuration
        config = configs[automation_id]
        for field, value in data.items():
            if hasattr(config, field):
                setattr(config, field, value)
        
        if automation_manager.save_configuration(config):
            # Refresh the in-memory configurations to ensure the running automation uses the updated config
            automation_manager.refresh_configurations()
            return jsonify({
                'success': True,
                'message': 'Automation updated successfully'
            })
        else:
            return jsonify({'error': 'Failed to save automation'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/<automation_id>', methods=['DELETE'])
@require_auth
def delete_automation(automation_id):
    """API endpoint to delete an automation configuration"""
    try:
        if automation_manager.delete_configuration(automation_id):
            return jsonify({
                'success': True,
                'message': 'Automation deleted successfully'
            })
        else:
            return jsonify({'error': 'Automation not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/status')
@require_auth
def get_automation_status():
    """API endpoint to get status of all automation jobs"""
    try:
        statuses = automation_manager.get_status()
        return jsonify({
            'statuses': {
                automation_id: {
                    'automation_id': status.automation_id,
                    'active': status.active,
                    'last_check': status.last_check,
                    'last_process': status.last_process,
                    'messages_checked': status.messages_checked,
                    'messages_processed': status.messages_processed,
                    'errors_count': status.errors_count,
                    'is_running': status.is_running,
                    'next_trigger': automation_manager._calculate_next_trigger(
                        automation_manager.automation_configs[automation_id], 
                        status.last_check
                    ),
                    'logs': [
                        {
                            'timestamp': log.timestamp,
                            'action': log.action,
                            'message': log.message,
                            'details': log.details
                        }
                        for log in status.logs
                    ]
                }
                for automation_id, status in statuses.items()
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/<automation_id>/status')
@require_auth
def get_automation_detailed_status(automation_id):
    """API endpoint to get detailed status for a specific automation job"""
    try:
        detailed_status = automation_manager.get_detailed_status(automation_id)
        if detailed_status:
            return jsonify(detailed_status)
        else:
            return jsonify({'error': 'Automation not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/<automation_id>/start', methods=['POST'])
@require_auth
def start_automation(automation_id):
    """API endpoint to start a specific automation job"""
    try:
        if automation_manager.start_automation(automation_id):
            return jsonify({
                'success': True,
                'message': 'Automation started successfully'
            })
        else:
            return jsonify({'error': 'Failed to start automation'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/<automation_id>/stop', methods=['POST'])
@require_auth
def stop_automation(automation_id):
    """API endpoint to stop a specific automation job"""
    try:
        if automation_manager.stop_automation(automation_id):
            return jsonify({
                'success': True,
                'message': 'Automation stopped successfully'
            })
        else:
            return jsonify({'error': 'Failed to stop automation'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/start-all', methods=['POST'])
@require_auth
def start_all_automations():
    """API endpoint to start all automation jobs"""
    try:
        results = automation_manager.start_all_automations()
        started_count = sum(1 for success in results.values() if success)
        return jsonify({
            'success': True,
            'message': f'Started {started_count} out of {len(results)} automations',
            'results': results
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/automation/stop-all', methods=['POST'])
@require_auth
def stop_all_automations():
    """API endpoint to stop all automation jobs"""
    try:
        results = automation_manager.stop_all_automations()
        stopped_count = sum(1 for success in results.values() if success)
        return jsonify({
            'success': True,
            'message': f'Stopped {stopped_count} automations',
            'results': results
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def cleanup_resources():
    """Cleanup all resources when the application exits"""
    if hasattr(app, 'tasks_manager'):
        app.tasks_manager.cleanup()
    # Force garbage collection
    gc.collect()

# Register cleanup handlers
atexit.register(cleanup_resources)
signal.signal(signal.SIGTERM, lambda s, f: cleanup_resources())

@app.teardown_appcontext
def cleanup_context(exception=None):
    """Cleanup resources when the application context is torn down"""
    if hasattr(app, 'tasks_manager'):
        app.tasks_manager.cleanup()
    # Force garbage collection after each request
    gc.collect()

if __name__ == '__main__':
    port = int(os.getenv('WEBAPP_PORT', 3002))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_ENV') == 'development')