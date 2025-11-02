// --- Get HTML elements ---
const output = document.getElementById('output');
const input = document.getElementById('command-input');
const contextMenu = document.getElementById('context-menu');

// --- NEW: Initialize Socket.IO connection ---
// This connects to the server that served the page.
const socket = io();

// --- Client-side state ---
let activeKeyword = null;
let playerName = null;
let currentGameState = "login"; 
let commandHistory = [];
let historyIndex = -1;

// --- Helper: Send Command to Backend (NOW USES WEBSOCKETS) ---
function sendCommand(command, name) {
    // No more 'fetch' or 'isSilent'
    // We emit a 'command' event to the server.
    socket.emit('command', {
        player_name: name,
        command: command
    });
}

// --- Helper: Add Message to Output (Unchanged) ---
function addMessage(message, messageClass = null) {
    let formattedMessage = message;
    // Format room titles
    formattedMessage = formattedMessage.replace(
        /\*\*(.*?)\*\*/g, 
        '<span class="room-title">[$1]</span>'
    );
    // Add CSS class if one was provided
    if (messageClass) {
        formattedMessage = `<span class="${messageClass}">${formattedMessage}</span>`;
    }
    // We use innerHTML to render the <table> tags
    output.innerHTML += `\n${formattedMessage}`;
    output.scrollTop = output.scrollHeight;
}

// --- REMOVED: startGameLoop() ---
// The 'ping' loop is no longer needed.

// ---
// NEW: WEBSOCKET EVENT LISTENERS
// ---

// 1. This handles the direct response to *your* command
// The server will 'emit("command_response", ...)'
socket.on('command_response', (data) => {
    if (data.game_state) {
        currentGameState = data.game_state;
    }
    
    if (data.messages) {
        data.messages.forEach(msg => addMessage(msg));
    }
});

// 2. This handles *broadcasts* from the server (e.g., "Sean arrives.")
// The server will 'emit("message", ...)'
socket.on('message', (message) => {
    addMessage(message);
});
// 3. This handles the global tick event
socket.on('tick', () => {
    // Only show the tick prompt if we are in the main game
    if (playerName && currentGameState === "playing") {
        addMessage(">", "command-echo");
    }
});

// 4. Handle connection/disconnection events (optional but good)
socket.on('connect', () => {
    console.log("Connected to server with ID:", socket.id);
});

socket.on('disconnect', () => {
    console.log("Disconnected from server.");
    addMessage("...Connection lost. Please refresh the page.", "command-echo");
});

// ---
// UPDATED: Input: Listen for "Enter" key
// ---
input.addEventListener('keydown', async function(event) {
    if (event.key === 'Enter') {
        const commandOrName = input.value;
        if (!commandOrName) return;

        if (playerName && commandOrName !== commandHistory[0]) {
            commandHistory.unshift(commandOrName);
        }
        historyIndex = -1;
        input.value = '';

        if (playerName === null) {
            // --- 1. This is the LOGIN/CREATE step ---
            playerName = commandOrName;
            addMessage(`> ${playerName}`, 'command-echo'); // Echo the name
            // Send the first 'look' command
            sendCommand('look', playerName);
            
        } else if (currentGameState === "chargen") {
            // --- 2. This is a CHARGEN answer ---
            // We don't add the > echo, chargen_handler does it
            sendCommand(commandOrName, playerName);
            
        } else {
            // --- 3. This is a NORMAL game command (or training) ---
            addMessage(`> ${commandOrName}`, 'command-echo');
            sendCommand(commandOrName, playerName);
        }
    }
    // ... (ArrowUp/ArrowDown history logic is unchanged) ...
    else if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (commandHistory.length > 0 && historyIndex < commandHistory.length - 1) {
            historyIndex++;
            input.value = commandHistory[historyIndex];
        }
    }
    else if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (historyIndex > 0) {
            historyIndex--;
            input.value = commandHistory[historyIndex];
        } else if (historyIndex === 0) {
            historyIndex = -1;
            input.value = "";
        }
    }
});

// --- UPDATED: Left-Click Menu Logic ---
output.addEventListener('click', function(event) {
    const target = event.target;
    
    // Check if the clicked element is a 'keyword'
    if (target.classList.contains('keyword')) {
        event.preventDefault();
        event.stopPropagation();
        
        // --- THIS IS THE PRIMARY FIX ---
        // First, check if the keyword has a direct 'data-command'
        const command = target.dataset.command;
        
        if (command) {
            // This is a clickable skill or menu option (like in training)
            input.value = ''; 
            addMessage(`> ${command}`, 'command-echo');
            sendCommand(command, playerName);
            return; // We are done
        }
        // --- END FIX ---

        // If no data-command, proceed with old logic
        const keyword = target.dataset.name || target.innerText;

        if (currentGameState === "chargen") {
            // This handles clicking chargen options
            input.value = '';
            sendCommand(target.innerText, playerName); 
            
        } else if (currentGameState === "playing") {
            // This opens the right-click context menu
            activeKeyword = keyword;
            const verbs = (target.dataset.verbs || "look").split(',');
            
            contextMenu.innerHTML = '';
            
            verbs.forEach(verb => {
                const item = document.createElement('div');
                item.innerText = `${verb} ${activeKeyword}`;
                item.dataset.command = `${verb} ${activeKeyword}`;
                contextMenu.appendChild(item);
            });

            contextMenu.style.left = `${event.pageX}px`;
            contextMenu.style.top = `${event.pageY}px`;
            contextMenu.style.display = 'block';
        }
    }
});

document.addEventListener('click', function(event) {
    if (contextMenu.style.display === 'block') {
        contextMenu.style.display = 'none';
    }
});

contextMenu.addEventListener('click', function(event) {
    const command = event.target.dataset.command;
    if (command && playerName) { 
        input.value = ''; 
        addMessage(`> ${command}`, 'command-echo');
        sendCommand(command, playerName); 
    }
});