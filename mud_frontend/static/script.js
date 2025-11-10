// --- Get HTML elements ---
const output = document.getElementById('output');
const input = document.getElementById('command-input');
const contextMenu = document.getElementById('context-menu');

// --- NEW: Get GUI elements ---
const rtContainer = document.getElementById('rt-container'); // Get the container
const postureStatusEl = document.getElementById('posture-container');
const gaugeFills = {
    health: document.getElementById('health-fill'),
    mana: document.getElementById('mana-fill'),
    stamina: document.getElementById('stamina-fill'),
    spirit: document.getElementById('spirit-fill')
};
const gaugeTexts = {
    health: document.getElementById('health-text'),
    mana: document.getElementById('mana-text'),
    stamina: document.getElementById('stamina-text'),
    spirit: document.getElementById('spirit-text')
};
// --- END NEW ---

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

// --- NEW: Roundtime Timer State ---
let rtEndTime = 0;
let rtTimer = null;
// --- END NEW ---


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
// --- NEW: GUI Update Functions
// ---

function updateRtDisplay() {
    const now = Date.now();
    const timeLeft = rtEndTime - now;

    if (timeLeft <= 0) {
        // --- Roundtime is over ---
        if (rtTimer) {
            clearInterval(rtTimer);
            rtTimer = null;
        }
        rtEndTime = 0;
        rtContainer.innerHTML = ''; // Clear all boxes
        
        // Add prompt only if we are in the game
        if (currentClientState === "in_game" && currentGameState === "playing") {
            addMessage(">", "command-echo");
            input.focus(); // Focus input when RT clears
        }
    } else {
        // --- Roundtime is active ---
        const secondsLeft = Math.ceil(timeLeft / 1000); // How many seconds are left
        const currentBoxes = rtContainer.querySelectorAll('.rt-box');
        
        // Count down by removing 'active' class
        currentBoxes.forEach((box, index) => {
            if (index < secondsLeft) {
                box.classList.add('active');
            } else {
                box.classList.remove('active');
            }
        });
    }
}

// ---
// --- MODIFIED: Add rt_type parameter
// ---
function startRtTimer(duration_ms, end_time_ms, rt_type = "hard") {
    rtEndTime = end_time_ms;

    // Clear any existing timer just in case
    if (rtTimer) {
        clearInterval(rtTimer);
    }
    
    // --- NEW: Dynamically create boxes ---
    rtContainer.innerHTML = ''; // Clear old boxes
    const totalSeconds = Math.ceil(duration_ms / 1000);
    
    // Don't create boxes for tiny RTs
    if (totalSeconds < 1) {
        updateRtDisplay();
        return;
    }

    let boxesHtml = '';
    for (let i = 0; i < totalSeconds; i++) {
        // --- THIS IS THE FIX: Add rt_type (e.g., "hard" or "soft") as a class
        boxesHtml += `<div class="rt-box active ${rt_type}"></div>`;
    }
    rtContainer.innerHTML = boxesHtml;
    // --- END NEW ---
    
    // Start a new timer
    rtTimer = setInterval(updateRtDisplay, 100); // Check 10x per second
    updateRtDisplay(); // Run once immediately
}
// --- END MODIFIED ---

function updateVitals(vitals) {
    if (!vitals) return;

    // 1. Update Gauges
    const gauges = ['health', 'mana', 'stamina', 'spirit'];
    gauges.forEach(type => {
        const current = vitals[type] || 0;
        // --- THIS IS THE FIX: Default to 0, not 100 ---
        const max = vitals[`max_${type}`] || 0;
        // --- END FIX ---
        let percent = 0;
        if (max > 0) {
            percent = (current / max) * 100;
        }
        
        if (gaugeFills[type]) {
            gaugeFills[type].style.width = `${percent}%`;
        }
        if (gaugeTexts[type]) {
            gaugeTexts[type].innerText = `${type.charAt(0).toUpperCase() + type.slice(1)}: ${current}/${max}`;
        }
    });

    // 2. Update Posture & Status
    let statusText = vitals.posture || "Unknown";
    if (vitals.status_effects && vitals.status_effects.length > 0) {
        statusText += ` (${vitals.status_effects.join(', ')})`;
    }
    postureStatusEl.innerText = statusText;

    // 3. Update Roundtime
    // ---
    // --- MODIFIED: Pass rt_type to startRtTimer
    // ---
    if (vitals.rt_end_time_ms > Date.now()) {
        startRtTimer(vitals.rt_duration_ms, vitals.rt_end_time_ms, vitals.rt_type || 'hard');
    }
    // --- END MODIFIED ---
}

// ---
// --- WEBSOCKET EVENT LISTENERS
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
    
    // --- NEW: Update GUI ---
    if (data.vitals) {
        updateVitals(data.vitals);
    }
    // --- END NEW ---
});

// 2. This handles *broadcasts* from the server (e.g., "Sean arrives.")
socket.on('message', (message) => {
    addMessage(message);
});

// 3. This handles the global tick event
socket.on('tick', () => {
    // --- THIS IS THE FIX: 'in_g' -> 'in_game' ---
    if (currentClientState === "in_game" && currentGameState === "playing" && !rtTimer) {
        addMessage(">", "command-echo");
    }
    // --- END FIX ---
});

// ---
// --- THIS IS THE FIX: Listen for the new 'update_vitals' event
// ---
socket.on('update_vitals', (data) => {
    if (data) {
        updateVitals(data);
    }
});
// --- END FIX ---

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
    input.disabled = true; // Disable input on disconnect
});

// ---
// --- NEW: LOGIN FLOW EVENT LISTENERS
// ---

socket.on('prompt_username', () => {
    output.innerHTML = "Welcome. Please enter your Username.\n(This will create a new account if one does not exist)";
    currentClientState = "login_user";
    input.type = 'text';
    input.disabled = false;
    input.focus();
});

socket.on('prompt_password', () => {
    addMessage("Password:");
    currentClientState = "login_pass";
    input.type = 'password';
    input.disabled = false;
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
    input.disabled = false;
});

socket.on('prompt_create_character', () => {
    addMessage("No characters found on this account.");
    addMessage("Please enter a name for your new character:");
    currentClientState = "char_create_name";
    input.type = 'text';
    input.disabled = false;
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
    // --- THIS IS THE FIX ---
    // REMOVED: if (event.key === 'Enter' && rtTimer)
    // We now allow sending commands even if the client *thinks* we have RT
    // --- END FIX ---

    if (event.key === 'Enter') {
        const commandText = input.value;
        if (!commandText && currentClientState !== 'login_pass') return; // Allow empty password

        // Add to history *only if* in game
        if (currentClientState === "in_game" && commandText && commandText !== commandHistory[0]) {
            commandHistory.unshift(commandText);
            if (commandHistory.length > 50) { // Limit history
                commandHistory.pop();
            }
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
    // --- MODIFIED: Arrow keys work even if "rtTimer" is active ---
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
    // --- NEW: Block clicks if RT is active ---
    // if (rtTimer) return; // <-- We remove this block to allow clicks
    // --- END NEW ---

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
            addMessage(`> ${target.innerText}`, 'command-echo'); // Echo the click
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
    // --- NEW: Block clicks if RT is active ---
    // if (rtTimer) return; // <-- We remove this block
    // --- END NEW ---

    const command = event.target.dataset.command;
    if (command && currentClientState === "in_game") { // Check client state
        input.value = ''; 
        addMessage(`> ${command}`, 'command-echo');
        sendCommand(command); 
    }
});

// --- NEW: Initialize GUI on load ---
// Set default values so it doesn't look broken before login
updateVitals({
    hp: 0, max_hp: 0,
    mana: 0, max_mana: 0,
    stamina: 0, max_stamina: 0,
    spirit: 0, max_spirit: 0,
    posture: "...",
    status_effects: [],
    rt_end_time_ms: 0,
    rt_type: "hard" // <-- NEW
});
// --- END NEW ---