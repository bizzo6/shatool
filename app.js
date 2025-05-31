require('dotenv').config();
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const axios = require('axios');
const yargs = require('yargs');
const express = require('express');
const fs = require('fs');
const path = require('path');
const WebSocket = require('ws');

// Parse command line arguments
const argv = yargs
    .option('api-token', {
        alias: 't',
        description: 'API token for webhook authentication',
        type: 'string'
    })
    .option('reset', {
        alias: 'r',
        description: 'Reset authentication and start fresh',
        type: 'boolean'
    })
    .help()
    .alias('help', 'h')
    .argv;

// Handle reset option
if (argv.reset) {
    const authPath = path.join(__dirname, '.wwebjs_auth');
    if (fs.existsSync(authPath)) {
        fs.rmSync(authPath, { recursive: true, force: true });
        console.log('Authentication data cleared. Please restart the app.');
        process.exit(0);
    }
}

// Store API token globally (from env or command line)
global.API_TOKEN = process.env.API_TOKEN || argv.apiToken;

// Configure the WhatsApp client using LocalAuth to keep your session between restarts
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: { 
        headless: true,
        args: ['--no-sandbox']
    }
});

let isClientReady = false;
let qrData = null;
let appState = 'starting'; // 'starting', 'waiting_for_qr', 'authenticated'
let lastApiCallTime = 0;
const messageStore = [];
let activeChatIds = new Set();
const ACTIVE_CHATS_FILE = path.join(__dirname, 'active_chats.json');
let cachedChats = null;
let lastChatsUpdate = null;
let messageStoreByGroup = new Map(); // Store messages by group ID

// Initialize Express app
const app = express();
const PORT = process.env.PORT || 3000;

// Add JSON body parser middleware
app.use(express.json());

// Serve static files from public directory
app.use(express.static('public'));

// Print QR code to terminal so you can scan it with your phone
client.on('qr', (qr) => {
    console.log('QR RECEIVED, scan it with your phone:');
    qrcode.generate(qr, { small: true });
    qrData = qr;
    appState = 'waiting_for_qr';
});

// Function to wait for client to be fully initialized
async function waitForClientReady() {
    return new Promise((resolve) => {
        const checkReady = () => {
            if (isClientReady && client.pupPage) {
                resolve();
            } else {
                setTimeout(checkReady, 1000);
            }
        };
        checkReady();
    });
}

// Modify the ready event handler
client.on('ready', async () => {
    console.log('Client is ready!');
    isClientReady = true;
    appState = 'authenticated';
    
    if (global.API_TOKEN) {
        console.log('API Token is set and ready for webhook authentication');
    }
    
    try {
        console.log('Waiting for client to be fully initialized...');
        await waitForClientReady();
        console.log('Client fully initialized, proceeding with setup...');
        
        await printUserStats();
        await printActiveContactsAndGroups(10);
        // Cache chats on startup
        await updateCachedChats();
    } catch (error) {
        console.error('Error in ready handler:', error);
        console.error('Error details:', error.stack);
    }
});

// Function to get chat type based on ID
function getChatType(chatId) {
    if (chatId.endsWith('@g.us')) return 'Group';
    if (chatId.endsWith('@c.us')) return 'Private';
    return 'Unknown';
}

// Helper to check if a timestamp is within the last N days
function isActiveWithinDays(timestamp, days = 10) {
    const now = Date.now();
    return (now - timestamp * 1000) <= days * 24 * 60 * 60 * 1000;
}

// Function to print active contacts and groups
async function printActiveContactsAndGroups(days = 10) {
    if (!isClientReady) {
        console.log('Client not ready yet, waiting...');
        return;
    }
    try {
        const chats = await client.getChats();
        console.log(`\n=== Active Contacts and Groups in the Last ${days} Days ===`);
        
        for (const chat of chats) {
            const lastTimestamp = chat.timestamp || (chat.lastMessage && chat.lastMessage.timestamp);
            if (!lastTimestamp || !isActiveWithinDays(lastTimestamp, days)) continue;

            const chatType = getChatType(chat.id._serialized);
            
            if (chatType === 'Group') {
                const groupName = chat.name || 'Unknown Group';
                const groupId = chat.id._serialized;
                let participantCount = 'N/A';
                
                if (chat.groupMetadata && chat.groupMetadata.participants) {
                    participantCount = chat.groupMetadata.participants.length;
                } else if (chat.participants) {
                    participantCount = chat.participants.length;
                }
                
                console.log(`Group: ${groupName} | ID: ${groupId} | Participants: ${participantCount}`);
            } else if (chatType === 'Private') {
                const contact = await chat.getContact();
                const name = contact.name || contact.pushname || contact.number;
                const number = contact.number;
                console.log(`Contact: ${name} | Number: ${number}`);
            }
        }
        console.log('========================================================\n');
    } catch (error) {
        console.error('Error scanning active contacts and groups:', error);
    }
}

// Function to print user statistics
async function printUserStats() {
    if (!isClientReady) {
        console.log('Client not ready yet, waiting...');
        return;
    }

    try {
        console.log('Fetching chats...');
        const chats = await client.getChats();
        console.log(`Found ${chats.length} chats`);
        
        console.log('Fetching contacts...');
        const contacts = await client.getContacts();
        console.log(`Found ${contacts.length} contacts`);
        
        let unreadCount = 0;
        let groupCount = 0;
        let privateChatCount = 0;
        
        for (const chat of chats) {
            if (chat.unreadCount > 0) {
                unreadCount += chat.unreadCount;
            }
            if (chat.isGroup) {
                groupCount++;
            } else {
                privateChatCount++;
            }
        }

        console.log('\n=== WhatsApp Statistics ===');
        console.log(`Total Contacts: ${contacts.length}`);
        console.log(`Total Chats: ${chats.length}`);
        console.log(`Groups: ${groupCount}`);
        console.log(`Private Chats: ${privateChatCount}`);
        console.log(`Unread Messages: ${unreadCount}`);
        console.log('========================\n');
    } catch (error) {
        console.error('Error getting statistics:', error);
        console.error('Error details:', error.stack);
    }
}

// Function to get message type
function getMessageType(msg) {
    if (msg.hasMedia) {
        if (msg.type === 'image') return 'image';
        if (msg.type === 'video') return 'video';
        if (msg.type === 'document') return 'file';
        if (msg.type === 'audio') return 'audio';
        if (msg.type === 'sticker') return 'sticker';
        return 'media';
    }
    return 'text';
}

// Function to load active chats from file
function loadActiveChats() {
    try {
        if (fs.existsSync(ACTIVE_CHATS_FILE)) {
            const data = fs.readFileSync(ACTIVE_CHATS_FILE, 'utf8');
            const loadedData = JSON.parse(data);
            
            // Convert old format to new format if needed
            if (Array.isArray(loadedData)) {
                const newData = {
                    "default": {
                        "name": "Default Group",
                        "chatIds": loadedData
                    }
                };
                fs.writeFileSync(ACTIVE_CHATS_FILE, JSON.stringify(newData, null, 2));
                return newData;
            }
            
            return loadedData;
        }
        return {};
    } catch (error) {
        console.error('Error loading active chats:', error);
        return {};
    }
}

// Function to save active chats to file
function saveActiveChats(data) {
    try {
        fs.writeFileSync(ACTIVE_CHATS_FILE, JSON.stringify(data, null, 2));
        console.log('Saved active chats configuration to file');
    } catch (error) {
        console.error('Error saving active chats:', error);
    }
}

// Function to get messages for a specific group
function getMessagesForGroup(groupId) {
    return messageStoreByGroup.get(groupId) || [];
}

// Function to add message to group store
function addMessageToGroup(groupId, message) {
    if (!messageStoreByGroup.has(groupId)) {
        messageStoreByGroup.set(groupId, []);
    }
    messageStoreByGroup.get(groupId).push(message);
}

// Load active chats on startup
const activeChatsConfig = loadActiveChats();

// Modify the message event handler to filter messages based on active groups
client.on('message', async msg => {
    if (!isClientReady) {
        console.log('Client not ready yet, ignoring message');
        return;
    }

    try {
        const chat = await msg.getChat();
        const chatId = chat.id._serialized;

        // Check if this chat belongs to any active group
        const activeGroups = Object.entries(activeChatsConfig)
            .filter(([_, config]) => config.chatIds.includes(chatId));

        if (activeGroups.length === 0) {
            return; // Skip if chat doesn't belong to any active group
        }

        const sender = await msg.getContact();
        const messageType = getMessageType(msg);
        const chatType = getChatType(chatId);

        // Create the message JSON
        const messageJson = {
            id: msg.id._serialized.split('us_')[1] || msg.id._serialized,
            timestamp: msg.timestamp,
            group: chatType === 'Group' ? chat.name : "",
            from: sender.name || sender.number,
            from_number: msg.from.split('@')[0],
            type: messageType,
            forwarded: msg.isForwarded,
            text: msg.body || "",
            links: msg.body ? msg.body.match(/(?:https?:\/\/)?(?:www\.)?[^\s]+\.[^\s]+/g) || [] : []
        };

        // Add message to each relevant group's store
        activeGroups.forEach(([groupId, _]) => {
            addMessageToGroup(groupId, messageJson);
        });

        // Broadcast message to all connected WebSocket clients
        wss.clients.forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
                client.send(JSON.stringify({
                    type: 'new_message',
                    from: sender.name || sender.number,
                    group: chatType === 'Group' ? chat.name : null,
                    message: messageJson
                }));
            }
        });

    } catch (err) {
        console.error('Error processing message:', err);
        console.error('Error details:', err.stack);
    }
});

// Add new group-based endpoints
app.post('/api/setActive/:groupId', (req, res) => {
    const timestamp = new Date().toISOString();
    console.log(`\n=== API Request [${timestamp}] ===`);
    console.log('Request Body:', JSON.stringify(req.body, null, 2));

    const { token, chatIds, group_name } = req.body;
    const groupId = req.params.groupId;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    // Validate required fields
    if (!chatIds || !Array.isArray(chatIds)) {
        return res.status(400).json({ error: 'chatIds array is required' });
    }

    if (!group_name) {
        return res.status(400).json({ error: 'group_name is required' });
    }

    try {
        // Update active chats configuration
        activeChatsConfig[groupId] = {
            name: group_name,
            chatIds: chatIds
        };

        // Save to file
        saveActiveChats(activeChatsConfig);

        res.json({
            success: true,
            message: `Group ${groupId} updated successfully`,
            group: activeChatsConfig[groupId]
        });
    } catch (error) {
        console.error('Error setting active group:', error);
        res.status(500).json({ error: 'Failed to set active group' });
    }
});

// Modify getActive endpoint to use POST
app.post('/api/getActive/:groupId', (req, res) => {
    const timestamp = new Date().toISOString();
    console.log(`\n=== API Request [${timestamp}] ===`);
    console.log('Request Body:', JSON.stringify(req.body, null, 2));

    const { token } = req.body;
    const groupId = req.params.groupId;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    try {
        if (groupId) {
            // Return specific group
            const group = activeChatsConfig[groupId];
            if (!group) {
                return res.status(404).json({ error: 'Group not found' });
            }
            res.json(group);
        } else {
            // Return all groups
            res.json(activeChatsConfig);
        }
    } catch (error) {
        console.error('Error getting active group:', error);
        res.status(500).json({ error: 'Failed to get active group' });
    }
});

app.post('/api/getMessages/:groupId', (req, res) => {
    const timestamp = new Date().toISOString();
    console.log(`\n=== API Request [${timestamp}] ===`);
    console.log('Request Body:', JSON.stringify(req.body, null, 2));

    const { token } = req.body;
    const groupId = req.params.groupId;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    // Validate group exists
    if (!activeChatsConfig[groupId]) {
        return res.status(404).json({ error: 'Group not found' });
    }

    try {
        const messages = getMessagesForGroup(groupId);
        res.json({
            groupId,
            groupName: activeChatsConfig[groupId].name,
            messages
        });
    } catch (error) {
        console.error('Error getting messages:', error);
        res.status(500).json({ error: 'Failed to get messages' });
    }
});

app.delete('/api/removeActive/:groupId', (req, res) => {
    const { token } = req.query;
    const groupId = req.params.groupId;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    try {
        // Check if group exists
        if (!activeChatsConfig[groupId]) {
            return res.status(404).json({ error: 'Group not found' });
        }

        // Remove group from configuration
        delete activeChatsConfig[groupId];
        saveActiveChats(activeChatsConfig);

        // Clear messages for this group
        messageStoreByGroup.delete(groupId);

        res.json({
            success: true,
            message: `Group ${groupId} removed successfully`
        });
    } catch (error) {
        console.error('Error removing group:', error);
        res.status(500).json({ error: 'Failed to remove group' });
    }
});

// Modify the updateCachedChats function to include ready check
async function updateCachedChats() {
    try {
        console.log('Checking client readiness...');
        await waitForClientReady();
        
        console.log('Updating cached chats...');
        const chats = await client.getChats();
        const activeChats = [];

        for (const chat of chats) {
            const chatId = chat.id._serialized;
            const chatType = getChatType(chatId);
            
            let chatInfo = {
                id: chatId,
                type: chatType,
                name: chat.name || 'Unknown',
                isActive: activeChatIds.size === 0 || activeChatIds.has(chatId)
            };

            if (chatType === 'Group') {
                chatInfo.participantCount = chat.participants ? chat.participants.length : 'N/A';
            } else {
                const contact = await chat.getContact();
                chatInfo.contactName = contact.name || contact.pushname || contact.number;
                chatInfo.contactNumber = contact.number;
            }

            activeChats.push(chatInfo);
        }

        cachedChats = activeChats;
        lastChatsUpdate = new Date();
        console.log(`Updated cached chats at ${lastChatsUpdate.toISOString()}`);
        return activeChats;
    } catch (error) {
        console.error('Error updating cached chats:', error);
        throw error;
    }
}

// Modify the getActiveChats endpoint to include ready check
app.post('/api/getActiveChats', async (req, res) => {
    const timestamp = new Date().toISOString();
    console.log(`\n=== API Request [${timestamp}] ===`);
    console.log('Request Body:', JSON.stringify(req.body, null, 2));

    const { token } = req.body;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    // Check if client is ready
    if (!isClientReady) {
        console.log('Error: WhatsApp client is not ready');
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    // Check if we have cached data
    if (!cachedChats || !lastChatsUpdate) {
        console.log('Error: Chat data not ready yet');
        return res.status(503).json({ error: 'Data not ready yet' });
    }

    try {
        // Return cached data
        console.log('Returning cached chats data');
        return res.json({
            chats: cachedChats,
            lastUpdate: lastChatsUpdate.toISOString()
        });
    } catch (error) {
        console.error('Error getting active chats:', error);
        res.status(500).json({ error: 'Failed to get active chats' });
    }
});

app.post('/api/setActive', (req, res) => {
    const timestamp = new Date().toISOString();
    console.log(`\n=== API Request [${timestamp}] ===`);
    console.log('Request Body:', JSON.stringify(req.body, null, 2));

    const { token, chatIds } = req.body;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    // Update active chat IDs
    if (Array.isArray(chatIds)) {
        activeChatIds = new Set(chatIds);
        console.log(`Set ${activeChatIds.size} active chat IDs`);
    } else {
        activeChatIds = new Set();
        console.log('Reset active chat IDs to empty (all chats will be monitored)');
    }

    // Save to file
    saveActiveChats();

    res.json({ 
        success: true, 
        message: activeChatIds.size === 0 ? 
            'All chats will be monitored' : 
            `Monitoring ${activeChatIds.size} active chats`,
        activeChatIds: Array.from(activeChatIds)
    });
});

// Add new async update endpoint
app.post('/api/updateChats', async (req, res) => {
    const timestamp = new Date().toISOString();
    console.log(`\n=== API Request [${timestamp}] ===`);
    console.log('Request Body:', JSON.stringify(req.body, null, 2));

    const { token } = req.body;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    // Check if client is ready
    if (!isClientReady) {
        console.log('Error: WhatsApp client is not ready');
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    // Start update process
    updateCachedChats()
        .then(() => {
            res.json({ 
                success: true, 
                message: 'Chat update initiated',
                lastUpdate: lastChatsUpdate.toISOString()
            });
        })
        .catch(error => {
            console.error('Error in update process:', error);
            res.status(500).json({ error: 'Failed to update chats' });
        });
});

// Handle authentication failure
client.on('auth_failure', msg => {
    console.error('Authentication failed:', msg);
    isClientReady = false;
    appState = 'auth_failed';
});

// Handle disconnection
client.on('disconnected', (reason) => {
    console.log('Client was disconnected:', reason);
    isClientReady = false;
    appState = 'disconnected';
});

// Modify the status endpoint to include last update time
app.get('/status', (req, res) => {
    res.json({ 
        state: appState,
        isReady: isClientReady,
        hasQr: !!qrData,
        lastChatsUpdate: lastChatsUpdate ? lastChatsUpdate.toISOString() : null
    });
});

app.get('/qr', async (req, res) => {
    if (!qrData) {
        return res.status(404).send('No QR code available');
    }
    try {
        const qrImage = await QRCode.toDataURL(qrData);
        res.send(`<img src="${qrImage}" alt="QR Code" style="max-width: 300px;" />`);
    } catch (err) {
        res.status(500).send('Error generating QR code');
    }
});

app.get('/', (req, res) => {
    res.send(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Shatool Dad Monitor</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                    text-align: center;
                    background-color: #f0f2f5;
                }
                .status {
                    margin: 20px 0;
                    padding: 10px;
                    border-radius: 5px;
                }
                .waiting { background-color: #fff3cd; color: #856404; }
                .ready { background-color: #d4edda; color: #155724; }
                .error { background-color: #f8d7da; color: #721c24; }
                #qr-container {
                    margin: 20px 0;
                }
                #qr-container img {
                    max-width: 300px;
                    margin: 0 auto;
                }
                #chat-container {
                    background-color: white;
                    border-radius: 10px;
                    padding: 20px;
                    margin: 20px 0;
                    min-height: 300px;
                    max-height: 500px;
                    overflow-y: auto;
                    text-align: left;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .message {
                    margin: 10px 0;
                    padding: 10px;
                    border-radius: 5px;
                    background-color: #f0f2f5;
                }
                .timestamp {
                    font-size: 0.8em;
                    color: #666;
                    margin-top: 5px;
                }
                .status-indicator {
                    display: inline-block;
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    margin-right: 5px;
                }
                .status-indicator.active {
                    background-color: #4CAF50;
                    animation: pulse 1.5s infinite;
                }
                .status-indicator.error {
                    background-color: #f44336;
                }
                @keyframes pulse {
                    0% { transform: scale(1); }
                    50% { transform: scale(1.2); }
                    100% { transform: scale(1); }
                }
                .server-status {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 10px 0;
                }
            </style>
        </head>
        <body>
            <h1>Shatool Dad Monitor</h1>
            <div class="server-status">
                <div id="status-indicator" class="status-indicator"></div>
                <div id="status" class="status"></div>
            </div>
            <div id="qr-container"></div>
            <div id="chat-container"></div>
            
            <script>
                let startTime = null;
                const chatContainer = document.getElementById('chat-container');
                const statusIndicator = document.getElementById('status-indicator');

                function addMessage(text, isSystem = false) {
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message';
                    if (isSystem) {
                        messageDiv.style.backgroundColor = '#e3f2fd';
                    }
                    
                    const messageText = document.createElement('div');
                    messageText.textContent = text;
                    
                    const timestamp = document.createElement('div');
                    timestamp.className = 'timestamp';
                    timestamp.textContent = new Date().toLocaleString();
                    
                    messageDiv.appendChild(messageText);
                    messageDiv.appendChild(timestamp);
                    chatContainer.appendChild(messageDiv);
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }

                async function updateStatus() {
                    const response = await fetch('/status');
                    const data = await response.json();
                    
                    const statusDiv = document.getElementById('status');
                    const qrContainer = document.getElementById('qr-container');
                    
                    // Update status indicator
                    if (data.state === 'authenticated') {
                        statusIndicator.className = 'status-indicator active';
                    } else if (data.state === 'auth_failed' || data.state === 'disconnected') {
                        statusIndicator.className = 'status-indicator error';
                    } else {
                        statusIndicator.className = 'status-indicator';
                    }
                    
                    // Update status text and styling
                    let statusText = '';
                    let statusClass = '';
                    
                    switch(data.state) {
                        case 'starting':
                            statusText = 'Starting WhatsApp client...';
                            statusClass = 'waiting';
                            break;
                        case 'waiting_for_qr':
                            statusText = 'Please scan the QR code with your phone';
                            statusClass = 'waiting';
                            if (data.hasQr) {
                                const qrResponse = await fetch('/qr');
                                const qrHtml = await qrResponse.text();
                                qrContainer.innerHTML = qrHtml;
                            }
                            break;
                        case 'authenticated':
                            statusText = 'Ready! Dad is now listening...';
                            statusClass = 'ready';
                            qrContainer.innerHTML = '';
                            if (!startTime) {
                                startTime = new Date();
                                addMessage('Started on ' + startTime.toLocaleString(), true);
                            }
                            break;
                        case 'auth_failed':
                            statusText = 'Authentication failed. Please try again.';
                            statusClass = 'error';
                            break;
                        case 'disconnected':
                            statusText = 'Client disconnected. Please refresh the page.';
                            statusClass = 'error';
                            break;
                        default:
                            statusText = 'Unknown status';
                            statusClass = 'waiting';
                    }
                    
                    statusDiv.textContent = statusText;
                    statusDiv.className = 'status ' + statusClass;
                }

                // WebSocket connection for real-time message updates
                const wsProtocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                const ws = new WebSocket(wsProtocol + window.location.host + '/ws');
                
                ws.onmessage = function(event) {
                    const message = JSON.parse(event.data);
                    if (message.type === 'new_message') {
                        let messageText = 'Received a message from ' + message.from;
                        if (message.group) {
                            messageText += ' in the group "' + message.group + '"';
                        }
                        addMessage(messageText);
                    }
                };
                
                // Update status every 2 seconds
                setInterval(updateStatus, 2000);
                updateStatus();
            </script>
        </body>
        </html>
    `);
});

// Add WebSocket support for real-time updates
const wss = new WebSocket.Server({ noServer: true });

wss.on('connection', function connection(ws) {
    console.log('New WebSocket connection');
});

// Add WebSocket upgrade handler to the HTTP server
const server = app.listen(PORT, () => {
    console.log('Web interface running on http://localhost:' + PORT);
});

server.on('upgrade', (request, socket, head) => {
    wss.handleUpgrade(request, socket, head, socket => {
        wss.emit('connection', socket, request);
    });
});

// Initialize the WhatsApp client
console.log('\n=== Server Startup Information ===');
console.log(`API Token: ${global.API_TOKEN ? 'Set' : 'Not set'}`);
if (global.API_TOKEN) {
    console.log(`Token value: ${global.API_TOKEN.substring(0, 4)}...${global.API_TOKEN.substring(global.API_TOKEN.length - 4)}`);
}

// Check if authentication data exists
const authPath = path.join(__dirname, '.wwebjs_auth');
if (fs.existsSync(authPath)) {
    console.log('Authentication: Found existing authentication data');
} else {
    console.log('Authentication: No existing authentication data found - will require new QR scan');
}

console.log('Initializing WhatsApp client...');
client.initialize().catch(err => {
    console.error('Failed to initialize client:', err);
    console.error('Error details:', err.stack);
});

// Add new endpoint to get active chat configuration
app.post('/api/getActive', (req, res) => {
    const timestamp = new Date().toISOString();
    console.log(`\n=== API Request [${timestamp}] ===`);
    console.log('Request Body:', JSON.stringify(req.body, null, 2));

    const { token } = req.body;

    // Validate token
    if (!token) {
        console.log('Error: No token provided');
        return res.status(401).json({ error: 'Token is required' });
    }

    if (token !== global.API_TOKEN) {
        console.log('Error: Invalid token provided');
        return res.status(401).json({ error: 'Invalid token' });
    }

    // Check if client is ready
    if (!isClientReady) {
        console.log('Error: WhatsApp client is not ready');
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    try {
        const activeChats = Array.from(activeChatIds);
        const isMonitoringAll = activeChatIds.size === 0;

        // If we have cached chats, enrich the response with chat names
        let enrichedResponse = {
            isMonitoringAll,
            activeChatIds: activeChats,
            lastUpdate: lastChatsUpdate ? lastChatsUpdate.toISOString() : null
        };

        if (cachedChats) {
            enrichedResponse.activeChats = cachedChats
                .filter(chat => isMonitoringAll || activeChatIds.has(chat.id))
                .map(chat => ({
                    id: chat.id,
                    name: chat.name,
                    type: chat.type,
                    isActive: true
                }));
        }

        console.log('Returning active chat configuration');
        res.json(enrichedResponse);
    } catch (error) {
        console.error('Error getting active configuration:', error);
        res.status(500).json({ error: 'Failed to get active configuration' });
    }
});