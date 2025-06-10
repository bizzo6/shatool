from flask import Flask, render_template, jsonify, request, send_from_directory, make_response, send_file
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

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure Basic Auth
app.config['BASIC_AUTH_USERNAME'] = os.getenv('BASIC_AUTH_USERNAME')
app.config['BASIC_AUTH_PASSWORD'] = os.getenv('BASIC_AUTH_PASSWORD')
app.config['BASIC_AUTH_FORCE'] = False  # Don't force authentication globally

# Create a list of paths that should be exempt from authentication
exempt_paths = [
    '/static/manifest.json',
    '/manifest.json',
    '/static/sw.js',
    '/sw.js',
    '/static/icon-192x192.png',
    '/static/icon-512x512.png',
    '/static/icon-144x144.png',
    '/favicon.ico'
]

# Initialize basic auth
basic_auth = BasicAuth(app)

# Add before_request handler to check paths
@app.before_request
def check_auth():
    if request.path not in exempt_paths:
        return basic_auth.required(lambda: None)()

# Custom static file handler
@app.route('/static/<path:filename>')
def custom_static(filename):
    if filename in ['manifest.json', 'sw.js', 'icon-192x192.png', 'icon-512x512.png', 'icon-144x144.png']:
        return send_from_directory('static', filename)
    return send_from_directory('static', filename)

# Add a direct route for manifest.json
@app.route('/manifest.json')
def serve_manifest():
    response = make_response(send_from_directory('static', 'manifest.json', 
                             mimetype='application/manifest+json'))
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# Add a direct route for service worker
@app.route('/sw.js')
def serve_service_worker():
    response = make_response(send_from_directory('static', 'sw.js',
                             mimetype='application/javascript'))
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# Get environment variables
API_TOKEN = os.getenv('API_TOKEN')
AGENT_HOST = os.getenv('AGENT_HOST', 'https://agent.shatool.dad')
IS_DEVELOPMENT = os.getenv('FLASK_ENV') == 'development'

SELF = "'self'"
TAILWIND = "https://cdn.tailwindcss.com"
talisman_csp = {
    'default-src': [SELF],
    'script-src': [SELF, TAILWIND, "'unsafe-inline'", "'unsafe-eval'"],
    'style-src': [SELF, "'unsafe-inline'"],
    'img-src': [SELF, "data:", "blob:"],
    'connect-src': [SELF, AGENT_HOST, TAILWIND],
    'manifest-src': [SELF],
    'worker-src': [SELF],
    'child-src': [SELF],
    'frame-src': [SELF]
}

# Configure Talisman based on environment
if IS_DEVELOPMENT:
    # In development, allow HTTP
    Talisman(app, 
             content_security_policy=talisman_csp,
             force_https=False)
else:
    # In production, enforce HTTPS
    Talisman(app, 
             content_security_policy=talisman_csp,
             force_https=True,
             strict_transport_security=True,
             session_cookie_secure=True)

# Initialize tasks manager
tasks_manager = TasksManager()

# Initialize AI processor
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
ai_processor = MessageProcessor(DataStore(storage_dir=str(DATA_DIR)))

# Initialize prompt manager
prompt_manager = PromptManager(Path(__file__).parent / "prompts")

# Configure Flask to handle Hebrew text properly
app.json.ensure_ascii = False

# Color palette for Tailwind (for reference in templates):
# FCF3EA - background
# 104F6A - text
# DF7833 - accent
# 30A8A5 - secondary
# FDC399 - highlight

@app.route('/')
@basic_auth.required
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
@basic_auth.required
def settings():
    try:
        resp = requests.get('http://localhost:3000/status', timeout=2)
        status = resp.json()
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    return render_template('settings.html', status=status, active_page='settings')

@app.route('/prompts')
@basic_auth.required
def prompts():
    return render_template('prompts.html', active_page='prompts')

@app.route('/todo')
@basic_auth.required
def todo():
    return render_template('todo.html', active_page='todo')

@app.route('/debug')
@basic_auth.required
def debug():
    return render_template('debug.html', active_page='debug')

@app.route('/api/tasks')
@basic_auth.required
def get_tasks():
    """API endpoint to get all tasks"""
    task_type = request.args.get('type')
    tasks = tasks_manager.get_tasks(task_type)
    return jsonify({
        'tasks': tasks,
        'last_update': tasks_manager.get_last_update()
    })

@app.route('/api/tasks/refresh', methods=['POST'])
@basic_auth.required
def refresh_tasks():
    """API endpoint to manually refresh tasks"""
    tasks_manager.refresh()
    return jsonify({
        'success': True,
        'last_update': tasks_manager.get_last_update()
    })

@app.route('/api/tasks/set/<task_id>', methods=['POST'])
@basic_auth.required
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
@basic_auth.required
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
@basic_auth.required
async def process_messages(template):
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
    valid_templates = ['todo', 'calendar', 'general']
    if template not in valid_templates:
        return jsonify({'error': f'Invalid template. Must be one of: {", ".join(valid_templates)}'}), 400
    
    try:
        # Process messages, replacing "now" with current timestamp and mapping time to timestamp
        messages = data['messages']
        for message in messages:
            if message.get('time') == 'now':
                message['time'] = int(time.time())
            # Map 'time' to 'timestamp' for AI processor compatibility
            message['timestamp'] = message.pop('time')
        
        # Process messages using AI processor
        result = await ai_processor.process_messages(messages, prompt_type=template)
        
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
@basic_auth.required
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
@basic_auth.required
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
@basic_auth.required
def list_prompts():
    """Get all available prompts"""
    prompts = prompt_manager.get_all_prompts()
    return jsonify({
        'prompts': [p.to_dict() for p in prompts]
    })

@app.route('/api/prompts/<name>', methods=['GET'])
@basic_auth.required
def get_prompt(name):
    """Get a specific prompt by name"""
    prompt = prompt_manager.get_prompt(name)
    if not prompt:
        return jsonify({'error': 'Prompt not found'}), 404
    return jsonify(prompt.to_dict())

@app.route('/api/prompts', methods=['POST'])
@basic_auth.required
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
@basic_auth.required
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
@basic_auth.required
def delete_prompt(name):
    """Delete a prompt"""
    if prompt_manager.delete_prompt(name):
        return jsonify({'success': True})
    return jsonify({'error': 'Prompt not found'}), 404

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico', mimetype='image/x-icon')

if __name__ == '__main__':
    port = int(os.getenv('WEBAPP_PORT', 3002))
    if IS_DEVELOPMENT:
        # In development, allow HTTP
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        # In production, you should use a proper SSL certificate
        # This is just an example - in production, you should use a proper SSL setup
        ssl_context = None
        if os.path.exists('cert.pem') and os.path.exists('key.pem'):
            ssl_context = ('cert.pem', 'key.pem')
        app.run(host='0.0.0.0', port=port, ssl_context=ssl_context)