from flask import Flask, render_template, jsonify, request
from flask_talisman import Talisman
import requests
from lib.tasks_manager import TasksManager
import json
from ai_processor.message_processor import MessageProcessor
from ai_processor.data_store import DataStore
from pathlib import Path
import time

app = Flask(__name__)

SELF = "'self'"
TAILWIND = "https://cdn.tailwindcss.com"
talisman_csp = {
    'default-src': [SELF],
    'script-src': [SELF, TAILWIND, "'unsafe-inline'"],
    'style-src': [SELF, "'unsafe-inline'"],
    'img-src': [SELF, "data:"]
}
Talisman(app, content_security_policy=talisman_csp)

# Initialize tasks manager
tasks_manager = TasksManager()

# Initialize AI processor
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
ai_processor = MessageProcessor(DataStore(storage_dir=str(DATA_DIR)))

# Configure Flask to handle Hebrew text properly
app.json.ensure_ascii = False

# Color palette for Tailwind (for reference in templates):
# FCF3EA - background
# 104F6A - text
# DF7833 - accent
# 30A8A5 - secondary
# FDC399 - highlight

@app.route('/')
def home():
    # Get WhatsApp client status from Node.js app
    try:
        resp = requests.get('http://localhost:3000/status', timeout=2)
        status = resp.json()
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    
    # Get all tasks
    tasks = tasks_manager.get_tasks()
    return render_template('home.html', status=status, tasks=tasks, active_page='home')

@app.route('/settings')
def settings():
    try:
        resp = requests.get('http://localhost:3000/status', timeout=2)
        status = resp.json()
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    return render_template('settings.html', status=status, active_page='settings')

@app.route('/todo')
def todo():
    return render_template('todo.html', active_page='todo')

@app.route('/debug')
def debug():
    return render_template('debug.html', active_page='debug')

@app.route('/api/tasks')
def get_tasks():
    """API endpoint to get all tasks"""
    task_type = request.args.get('type')
    tasks = tasks_manager.get_tasks(task_type)
    return jsonify({
        'tasks': tasks,
        'last_update': tasks_manager.get_last_update()
    })

@app.route('/api/tasks/refresh', methods=['POST'])
def refresh_tasks():
    """API endpoint to manually refresh tasks"""
    tasks_manager.refresh()
    return jsonify({
        'success': True,
        'last_update': tasks_manager.get_last_update()
    })

@app.route('/api/tasks/set/<task_id>', methods=['POST'])
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

@app.route('/api/process/<template>', methods=['POST'])
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

if __name__ == '__main__':
    app.run(port=3002, debug=True) 