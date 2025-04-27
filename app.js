require('dotenv').config();
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const axios = require('axios');
const yargs = require('yargs');
const express = require('express');
const fs = require('fs');
const path = require('path');

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

// Initialize Express app
const app = express();
const PORT = process.env.PORT || 3000;

// Serve static files from public directory
app.use(express.static('public'));

// Print QR code to terminal so you can scan it with your phone
client.on('qr', (qr) => {
    console.log('QR RECEIVED, scan it with your phone:');
    qrcode.generate(qr, { small: true });
    qrData = qr;
    appState = 'waiting_for_qr';
});

// Notify when the client is ready
client.on('ready', async () => {
    console.log('Client is ready!');
    isClientReady = true;
    appState = 'authenticated';
    
    if (global.API_TOKEN) {
        console.log('API Token is set and ready for webhook authentication');
    }
    
    try {
        console.log('Waiting for client to be fully initialized...');
        await new Promise(resolve => setTimeout(resolve, 5000));
        await printUserStats();
        await printActiveContactsAndGroups(10);
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

// Listen for new messages
client.on('message', async msg => {
    if (!isClientReady) {
        console.log('Client not ready yet, ignoring message');
        return;
    }

    try {
        const chat = await msg.getChat();
        const sender = await msg.getContact();
        const messageType = getMessageType(msg);
        const chatType = getChatType(chat.id._serialized);

        // Enhanced message logging with all available metadata
        console.log('\n=== New Message ===');
        console.log(`Message ID: ${msg.id._serialized}`);
        console.log(`Timestamp: ${new Date(msg.timestamp * 1000).toISOString()}`);
        console.log(`Chat Type: ${chatType}`);
        console.log(`Chat ID: ${chat.id._serialized}`);
        console.log(`Chat Name: ${chat.name || 'Unknown'}`);
        console.log(`From: ${sender.name || sender.number}`);
        console.log(`From ID: ${msg.from}`);
        console.log(`To: ${msg.to}`);
        console.log(`Message Type: ${messageType}`);
        console.log(`Has Media: ${msg.hasMedia}`);
        console.log(`Media Type: ${msg.type || 'N/A'}`);
        console.log(`Is Forwarded: ${msg.isForwarded}`);
        console.log(`Is Status: ${msg.isStatus}`);
        console.log(`Is Starred: ${msg.isStarred}`);
        console.log(`Is From Me: ${msg.fromMe}`);
        console.log(`Has Quoted Message: ${msg.hasQuotedMsg}`);
        console.log(`Body Preview: ${msg.body ? msg.body.substring(0, 20) + (msg.body.length > 20 ? '...' : '') : 'N/A'}`);
        console.log(`VCard: ${msg.vCards.length > 0 ? 'Yes' : 'No'}`);
        console.log(`Mentions: ${msg.mentionedIds.length > 0 ? msg.mentionedIds.join(', ') : 'None'}`);
        console.log(`Links: ${msg.links.length > 0 ? msg.links.join(', ') : 'None'}`);
        console.log('==================\n');

        const targetGroupName = 'בדיקה';

        if (chatType === 'Group' && chat.name === targetGroupName) {
            const payload = {
                messageId: msg.id._serialized,
                timestamp: msg.timestamp,
                from: msg.from,
                to: msg.to,
                body: msg.body,
                chatId: chat.id._serialized,
                chatName: chat.name,
                isGroup: true,
                apiToken: global.API_TOKEN,
                messageType: messageType,
                metadata: {
                    hasMedia: msg.hasMedia,
                    mediaType: msg.type,
                    isForwarded: msg.isForwarded,
                    isStatus: msg.isStatus,
                    isStarred: msg.isStarred,
                    fromMe: msg.fromMe,
                    hasQuotedMsg: msg.hasQuotedMsg,
                    vCards: msg.vCards,
                    mentionedIds: msg.mentionedIds,
                    links: msg.links
                }
            };

            // Trigger the webhook POST request
            try {
                //const response = await axios.post('https://your-webhook-url.com', payload);
                console.log(payload.body);
                //console.log('Webhook triggered successfully:', response.status);
            } catch (error) {
                console.error('Error triggering webhook:', error);
            }
        }
    } catch (err) {
        console.error('Error processing message:', err);
        console.error('Error details:', err.stack);
    }
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

// API endpoints
app.get('/status', (req, res) => {
    res.json({ 
        state: appState,
        isReady: isClientReady,
        hasQr: !!qrData
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
            <h1>WhatsApp Web Monitor</h1>
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
                            statusText = 'WhatsApp client is ready!';
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
const WebSocket = require('ws');
const wss = new WebSocket.Server({ noServer: true });

wss.on('connection', function connection(ws) {
    console.log('New WebSocket connection');
});

// Modify the message event handler to broadcast messages
client.on('message', async msg => {
    if (!isClientReady) {
        console.log('Client not ready yet, ignoring message');
        return;
    }

    try {
        const chat = await msg.getChat();
        const sender = await msg.getContact();
        const messageType = getMessageType(msg);
        const chatType = getChatType(chat.id._serialized);

        // Broadcast message to all connected WebSocket clients
        wss.clients.forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
                client.send(JSON.stringify({
                    type: 'new_message',
                    from: sender.name || sender.number,
                    group: chatType === 'Group' ? chat.name : null
                }));
            }
        });

        // Enhanced message logging with all available metadata
        console.log('\n=== New Message ===');
        console.log(`Message ID: ${msg.id._serialized}`);
        console.log(`Timestamp: ${new Date(msg.timestamp * 1000).toISOString()}`);
        console.log(`Chat Type: ${chatType}`);
        console.log(`Chat ID: ${chat.id._serialized}`);
        console.log(`Chat Name: ${chat.name || 'Unknown'}`);
        console.log(`From: ${sender.name || sender.number}`);
        console.log(`From ID: ${msg.from}`);
        console.log(`To: ${msg.to}`);
        console.log(`Message Type: ${messageType}`);
        console.log(`Has Media: ${msg.hasMedia}`);
        console.log(`Media Type: ${msg.type || 'N/A'}`);
        console.log(`Is Forwarded: ${msg.isForwarded}`);
        console.log(`Is Status: ${msg.isStatus}`);
        console.log(`Is Starred: ${msg.isStarred}`);
        console.log(`Is From Me: ${msg.fromMe}`);
        console.log(`Has Quoted Message: ${msg.hasQuotedMsg}`);
        console.log(`Body Preview: ${msg.body ? msg.body.substring(0, 20) + (msg.body.length > 20 ? '...' : '') : 'N/A'}`);
        console.log(`VCard: ${msg.vCards.length > 0 ? 'Yes' : 'No'}`);
        console.log(`Mentions: ${msg.mentionedIds.length > 0 ? msg.mentionedIds.join(', ') : 'None'}`);
        console.log(`Links: ${msg.links.length > 0 ? msg.links.join(', ') : 'None'}`);
        console.log('==================\n');

        const targetGroupName = 'בדיקה';

        if (chatType === 'Group' && chat.name === targetGroupName) {
            const payload = {
                messageId: msg.id._serialized,
                timestamp: msg.timestamp,
                from: msg.from,
                to: msg.to,
                body: msg.body,
                chatId: chat.id._serialized,
                chatName: chat.name,
                isGroup: true,
                apiToken: global.API_TOKEN,
                messageType: messageType,
                metadata: {
                    hasMedia: msg.hasMedia,
                    mediaType: msg.type,
                    isForwarded: msg.isForwarded,
                    isStatus: msg.isStatus,
                    isStarred: msg.isStarred,
                    fromMe: msg.fromMe,
                    hasQuotedMsg: msg.hasQuotedMsg,
                    vCards: msg.vCards,
                    mentionedIds: msg.mentionedIds,
                    links: msg.links
                }
            };

            // Trigger the webhook POST request
            try {
                //const response = await axios.post('https://your-webhook-url.com', payload);
                console.log(payload.body);
                //console.log('Webhook triggered successfully:', response.status);
            } catch (error) {
                console.error('Error triggering webhook:', error);
            }
        }
    } catch (err) {
        console.error('Error processing message:', err);
        console.error('Error details:', err.stack);
    }
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
console.log('Initializing WhatsApp client...');
client.initialize().catch(err => {
    console.error('Failed to initialize client:', err);
    console.error('Error details:', err.stack);
});