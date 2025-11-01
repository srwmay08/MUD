const output = document.getElementById('output');
const input = document.getElementById('command-input');
const contextMenu = document.getElementById('context-menu');

let activeKeyword = null;
let playerName = null;
let currentGameState = "login"; 
let commandHistory = [];
let historyIndex = -1;

// --- NEW: Game Loop Timer ---
let gameLoopInterval = null;

// --- Helper: Send Command to Backend ---
async function sendCommand(command, name) {
    // --- NEW: Add a "silent" flag for our ping ---
    const isSilent = (command === "ping");
    
    try {
        const response = await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                player_name: name,
                command: command
            })
        });
        
        const data = await response.json();
        
        if (data.game_state) {
            currentGameState = data.game_state;
        }
        
        if (data.messages) {
            data.messages.forEach(msg => addMessage(msg));
        }

    } catch (error) {
        // Only show error if it wasn't a silent ping
        if (!isSilent) {
            addMessage(`Error: Could not connect to server. ${error}`);
        } else {
            console.error("Game tick ping failed:", error);
        }
    }
}

// --- Helper: Add Message to Output (Unchanged) ---
function addMessage(message, messageClass = null) {
    let formattedMessage = message;
    formattedMessage = formattedMessage.replace(
        /\*\*(.*?)\*\*/g, 
        '<span class="room-title">[$1]</span>'
    );
    if (messageClass) {
        formattedMessage = `<span class="${messageClass}">${formattedMessage}</span>`;
    }
    output.innerHTML += `\n${formattedMessage}`;
    output.scrollTop = output.scrollHeight;
}

// --- NEW: Game Loop Function ---
function startGameLoop() {
    if (gameLoopInterval) {
        clearInterval(gameLoopInterval); // Stop any old loops
    }
    
    // Run a tick every 10 seconds (10000 milliseconds)
    gameLoopInterval = setInterval(() => {
        if (playerName && currentGameState === "playing") {
            
            // 1. Show the ">" prompt to the user
            addMessage(">", "command-echo");
            
            // 2. Send the "ping" command to trigger the server tick
            // This will also retrieve any ambient messages (like weather)
            sendCommand("ping", playerName);
        }
    }, 10000); // 10 seconds
}

// --- Input: Listen for "Enter" key ---
input.addEventListener('keydown', async function(event) {
    if (event.key === 'Enter') {
        const commandOrName = input.value;
        if (!commandOrName) return;

        // --- NEW: Add to history ---
        // Add to history if it's not a duplicate of the last command
        if (playerName && commandOrName !== commandHistory[0]) {
            commandHistory.unshift(commandOrName); // Adds to the start of the array
        }
        historyIndex = -1; // Reset history position to the blank line
        // --- END NEW ---

        input.value = '';

        if (playerName === null) {
            // --- 1. This is the LOGIN/CREATE step ---
            playerName = commandOrName;
            addMessage(`> Welcome, ${playerName}. Loading character...`, 'command-echo');
            // Send an automatic 'look' command
            await sendCommand('look', playerName);
            
            // --- NEW: Start the game loop! ---
            startGameLoop();
            
        } else if (currentGameState === "chargen") {
            // --- 2. This is a CHARGEN answer ---
            await sendCommand(commandOrName, playerName);
            
        } else {
            // --- 3. This is a NORMAL game command ---
            addMessage(`> ${commandOrName}`, 'command-echo');
            await sendCommand(commandOrName, playerName);
        }
    }
    // --- NEW: Listen for ArrowUp ---
    else if (event.key === 'ArrowUp') {
        event.preventDefault(); // Stop cursor from moving in the input
        // Check if we have history and we aren't at the end of it
        if (commandHistory.length > 0 && historyIndex < commandHistory.length - 1) {
            historyIndex++;
            input.value = commandHistory[historyIndex];
        }
    }
    // --- NEW: Listen for ArrowDown (for convenience) ---
    else if (event.key === 'ArrowDown') {
        event.preventDefault();
        // Check if we are currently looking at history
        if (historyIndex > 0) {
            historyIndex--;
            input.value = commandHistory[historyIndex];
        } else if (historyIndex === 0) {
            // We were at the last command, go back to blank
            historyIndex = -1;
            input.value = "";
        }
    }
});

// --- NEW: Left-Click Menu ---
output.addEventListener('click', function(event) {
    const target = event.target;
    
    // Check if we are clicking a keyword
    if (target.classList.contains('keyword')) {
        event.preventDefault(); // Stop default link behavior
        event.stopPropagation(); // !IMPORTANT: Stop click from bubbling to document
        
        const keyword = target.dataset.name || target.innerText;

        if (currentGameState === "chargen") {
            // --- In chargen, clicking a keyword IS the command ---
            input.value = ''; // Clear input
            // We send the text of the keyword as the command
            sendCommand(target.innerText, playerName); 
            
        } else if (currentGameState === "playing") {
            // --- In game, clicking a keyword opens a verb menu ---
            activeKeyword = keyword;
            const verbs = (target.dataset.verbs || "look").split(',');
            
            contextMenu.innerHTML = ''; // Clear old items
            
            verbs.forEach(verb => {
                const item = document.createElement('div');
                item.innerText = `${verb} ${activeKeyword}`; // Show as "LOOK FOUNTAIN"
                item.dataset.command = `${verb} ${activeKeyword}`; // Store as "look fountain"
                contextMenu.appendChild(item);
            });

            // Position and show the menu
            contextMenu.style.left = `${event.pageX}px`;
            contextMenu.style.top = `${event.pageY}px`;
            contextMenu.style.display = 'block';
        }
    }
});

// --- Hide Menu on any other click ---
document.addEventListener('click', function(event) {
    // This now only fires if we didn't click a keyword (due to stopPropagation)
    if (contextMenu.style.display === 'block') {
        contextMenu.style.display = 'none';
    }
});

// --- Verb Menu: Handle Click on Menu Item ---
contextMenu.addEventListener('click', function(event) {
    const command = event.target.dataset.command;
    if (command && playerName) { 
        input.value = ''; 
        addMessage(`> ${command}`, 'command-echo'); // Echo the command
        sendCommand(command, playerName); 
    }
});