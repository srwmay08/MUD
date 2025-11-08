// --- Get HTML elements ---
const output = document.getElementById('output');
const input = document.getElementById('command-input');
const contextMenu = document.getElementById('context-menu');

// --- NEW: Initialize Socket.IO connection ---
const socket = io();

// --- Client-side state ---
let activeKeyword = null;
// --- MODIFIED: These are now set by the server ---
let playerName = null; 
let currentGameState = "login"; // This is the MUD game state (e.g., chargen, playing)
// --- NEW: Client-side state for login flow ---
let currentClientState = "login_user"; // Tracks the *client's* state (login_user, login_pass, char_select, in_game)
// ---
let commandHistory = [];
let historyIndex = -1;

// --- Helper: Send Command to Backend (NOW USES WEBSOCKETS) ---
function sendCommand(command) {
    // --- MODIFIED: We no longer send player_name. ---
    // The server knows who we are based on our socket session.
    socket.emit('command', {
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

// ---
// NEW: WEBSOCKET EVENT LISTENERS
// ---

// 1. This handles the direct response to *your* command
socket.on('command_response', (data) => {
    // We are now officially in the game
    currentClientState = "in_game"; 
    
    if (data.game_state) {
        currentGameState = data.game_state;
    }
    
    if (data.messages) {
        data.messages.forEach(msg => addMessage(msg));
    }
});

// 2. This handles *broadcasts* from the server (e.g., "Sean arrives.")
socket.on('message', (message) => {
    addMessage(message);
});

// 3. This handles the global tick event
socket.on('tick', () => {
    // --- MODIFIED: Use client state to check ---
    if (currentClientState === "in_game" && currentGameState === "playing") {
        addMessage(">", "command-echo");
    }
});

// 4. Handle connection/disconnection events
socket.on('connect', () => {
    console.log("Connected to server with ID:", socket.id);
    // Server will send 'prompt_username' automatically
});

socket.on('disconnect', () => {
    console.log("Disconnected from server.");
    addMessage("...Connection lost. Please refresh the page.", "command-echo");
    currentClientState = "login_user";
    input.type = 'text';
});

// ---
// --- NEW: LOGIN FLOW EVENT LISTENERS
// ---

socket.on('prompt_username', () => {
    output.innerHTML = "Welcome. Please enter your Username.\n(This will create a new account if one does not exist)";
    currentClientState = "login_user";
    input.type = 'text';
    input.focus();
});

socket.on('prompt_password', () => {
    addMessage("Password:");
    currentClientState = "login_pass";
    input.type = 'password';
    input.focus();
});

socket.on('login_failed', (message) => {
    addMessage(message, "command-echo"); // Show error
    // Server will re-send 'prompt_username'
});

socket.on('show_char_list', (data) => {
    addMessage("--- Your Characters ---");
    data.chars.forEach(charName => {
        // Make character names clickable
        addMessage(`- <span class="keyword" data-command="${charName}">${charName}</span>`);
    });
    addMessage("\nType a character name to login, or type '<span class='keyword' data-command='create'>create</span>' to make a new one.");
    currentClientState = "char_select";
    input.type = 'text';
});

socket.on('prompt_create_character', () => {
    addMessage("No characters found on this account.");
    addMessage("Please enter a name for your new character:");
    currentClientState = "char_create_name";
    input.type = 'text';
});

socket.on('name_taken', () => {
    addMessage("That name is already taken. Please choose another:");
    currentClientState = "char_create_name"; // Stay in this state
});

socket.on('name_invalid', (message) => {
    addMessage(message);
    addMessage("Please enter a name for your new character:");
    currentClientState = "char_create_name"; // Stay in this state
});

socket.on('char_invalid', (message) => {
    addMessage(message);
    // Server will either re-send list or re-prompt for username
});


// ---
// UPDATED: Input: Listen for "Enter" key
// ---
input.addEventListener('keydown', async function(event) {
    if (event.key === 'Enter') {
        const commandText = input.value;
        if (!commandText && currentClientState !== 'login_pass') return; // Allow empty password

        // Add to history *only if* in game
        if (currentClientState === "in_game" && commandText !== commandHistory[0]) {
            commandHistory.unshift(commandText);
        }
        historyIndex = -1;
        input.value = '';

        // --- MODIFIED: Handle command echo based on state ---
        if (currentClientState === 'login_pass') {
            addMessage('> ********', 'command-echo');
        } else {
            addMessage(`> ${commandText}`, 'command-echo');
        }
        
        // --- MODIFIED: Always send command, server handles state ---
        sendCommand(commandText);
        
        // After sending, if it was a password, reset input type
        if (currentClientState === 'login_pass') {
            input.type = 'text';
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
        
        const command = target.dataset.command;
        
        if (command) {
            // This handles clickable skills, char list, 'create', etc.
            input.value = ''; 
            addMessage(`> ${command}`, 'command-echo');
            sendCommand(command);
            return; // We are done
        }
        // --- END FIX ---

        // If no data-command, proceed with old logic
        const keyword = target.dataset.name || target.innerText;

        if (currentGameState === "chargen") {
            // This handles clicking chargen options
            input.value = '';
            sendCommand(target.innerText); 
            
        } else if (currentClientState === "in_game") { // Check client state
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
    if (command && currentClientState === "in_game") { // Check client state
        input.value = ''; 
        addMessage(`> ${command}`, 'command-echo');
        sendCommand(command); 
    }
});