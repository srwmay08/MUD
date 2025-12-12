// mud_frontend/static/script.js
// --- Get HTML elements ---
const output = document.getElementById('output');
const input = document.getElementById('command-input');
const contextMenu = document.getElementById('context-menu');

// --- NEW: Get GUI elements ---
const rtContainer = document.getElementById('rt-container');
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

const leftPanel = document.getElementById('left-panel');
const panelToggleButton = document.getElementById('panel-toggle-button'); 
const mapSvg = document.getElementById('map-svg');
const mapRoomName = document.getElementById('map-room-name');
const mapRoomExits = document.getElementById('map-room-exits');
const svgNS = "http://www.w3.org/2000/svg"; 

const stanceSelect = document.getElementById('stance-select');
const stowMainhandBtn = document.getElementById('stow-mainhand-btn');
const stowOffhandBtn = document.getElementById('stow-offhand-btn');
const expValue = document.getElementById('exp-value');
const expLabel = document.getElementById('exp-label');
const expFill = document.getElementById('exp-fill');
const injurySvg = document.getElementById('injury-svg');
const wornItemsList = document.getElementById('worn-items-list');

const socket = io();

// --- Client-side state ---
let activeKeyword = null;
let playerName = null; 
let currentGameState = "login"; 
let currentClientState = "login_user"; 
let currentVitals = null;
let commandHistory = [];
let historyIndex = -1;
let rtEndTime = 0;
let rtTimer = null;

const COMMON_COMMANDS = [
    "attack", "cast", "look", "inventory", "get", "take", "drop", "put", "stow",
    "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest",
    "up", "down", "out", "enter", "exit", "go",
    "say", "whisper", "shout", "yell", "group", "band",
    "health", "stats", "skills", "spells", "info", "score",
    "help", "quit", "save", "alias", "unalias", "stand", "sit", "kneel", "prone",
    "buy", "sell", "list", "order", "appraise",
    "forage", "harvest", "mine", "chop", "fish", "skin", "search", "tend", "diagnose",
    "hide", "unhide", "sneak", "stalk"
];

function sendCommand(command) {
    socket.emit('command', {
        command: command
    });
}

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

function updateRtDisplay() {
    const now = Date.now();
    const timeLeft = rtEndTime - now;

    if (timeLeft <= 0) {
        if (rtTimer) {
            clearInterval(rtTimer);
            rtTimer = null;
        }
        rtEndTime = 0;
        rtContainer.innerHTML = ''; 
        
        if (currentClientState === "in_game" && currentGameState === "playing") {
            addMessage(">", "command-echo");
            input.focus();
        }
    } else {
        const secondsLeft = Math.ceil(timeLeft / 1000);
        const currentBoxes = rtContainer.querySelectorAll('.rt-box');
        
        currentBoxes.forEach((box, index) => {
            if (index < secondsLeft) {
                box.classList.add('active');
            } else {
                box.classList.remove('active');
            }
        });
    }
}

function startRtTimer(duration_ms, end_time_ms, rt_type = "hard") {
    rtEndTime = end_time_ms;

    if (rtTimer) {
        clearInterval(rtTimer);
    }
    
    rtContainer.innerHTML = '';
    const totalSeconds = Math.ceil(duration_ms / 1000);
    
    if (totalSeconds < 1) {
        updateRtDisplay();
        return;
    }

    let boxesHtml = '';
    for (let i = 0; i < totalSeconds; i++) {
        boxesHtml += `<div class="rt-box active ${rt_type}"></div>`;
    }
    rtContainer.innerHTML = boxesHtml;
    
    rtTimer = setInterval(updateRtDisplay, 100);
    updateRtDisplay();
}

function updateVitals(vitals) {
    if (!vitals) return;
    
    currentVitals = vitals;

    const gauges = ['health', 'mana', 'stamina', 'spirit'];
    gauges.forEach(type => {
        const current = vitals[type] || 0;
        const max = vitals[`max_${type}`] || 0;
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

    let statusText = vitals.posture || "Unknown";
    if (vitals.status_effects && vitals.status_effects.length > 0) {
        statusText += ` (${vitals.status_effects.join(', ')})`;
    }
    postureStatusEl.innerText = statusText;

    // --- NEW: Hidden Status Indicator ---
    if (vitals.is_hidden) {
        postureStatusEl.innerText += " [HIDDEN]";
        postureStatusEl.style.color = "#aaddff"; // Light blue indicator
    } else {
        postureStatusEl.style.color = ""; // Reset
    }

    if (vitals.rt_end_time_ms > Date.now()) {
        startRtTimer(vitals.rt_duration_ms, vitals.rt_end_time_ms, vitals.rt_type || 'hard');
    }
    
    updateGuiPanels(vitals);
}

// FIX: Added 'lefteye', 'leftleg' etc to handle non-normalized backend keys
const WOUND_COORDS = {
    "head":       { x: 8, y: 1.5, r: 1.5 },
    "neck":       { x: 8, y: 3.5, r: 1 },
    "chest":      { x: 8, y: 6, r: 1.5 },
    "abdomen":    { x: 8, y: 9, r: 1.5 },
    "back":       { x: 8, y: 7, r: 1.5 }, 
    
    // Eyes
    "right_eye":  { x: 4, y: 1.75, r: 0.8 }, 
    "r_eye":      { x: 4, y: 1.75, r: 0.8 }, 
    "righteye":   { x: 4, y: 1.75, r: 0.8 }, // Added match
    
    "left_eye":   { x: 12, y: 1.75, r: 0.8 },
    "l_eye":      { x: 12, y: 1.75, r: 0.8 },
    "lefteye":    { x: 12, y: 1.75, r: 0.8 }, // Added match

    // Arms
    "right_arm":  { x: 5.5, y: 8, r: 1.2 }, 
    "r_arm":      { x: 5.5, y: 8, r: 1.2 },
    "rightarm":   { x: 5.5, y: 8, r: 1.2 }, // Added match
    
    "left_arm":   { x: 10.5, y: 8, r: 1.2 }, 
    "l_arm":      { x: 10.5, y: 8, r: 1.2 },
    "leftarm":    { x: 10.5, y: 8, r: 1.2 }, // Added match
    
    // Hands
    "right_hand": { x: 5, y: 9.5, r: 1 },
    "r_hand":     { x: 5, y: 9.5, r: 1 },
    "righthand":  { x: 5, y: 9.5, r: 1 }, // Added match
    
    "left_hand":  { x: 11, y: 9.5, r: 1 },
    "l_hand":     { x: 11, y: 9.5, r: 1 },
    "lefthand":   { x: 11, y: 9.5, r: 1 }, // Added match
    
    // Legs
    "right_leg":  { x: 6.75, y: 12.5, r: 1.2 },
    "r_leg":      { x: 6.75, y: 12.5, r: 1.2 },
    "rightleg":   { x: 6.75, y: 12.5, r: 1.2 }, // Added match
    
    "left_leg":   { x: 9.25, y: 12.5, r: 1.2 },
    "l_leg":      { x: 9.25, y: 12.5, r: 1.2 },
    "leftleg":    { x: 9.25, y: 12.5, r: 1.2 }, // Added match
    
    // Special mappings
    "spirit":     { x: 11, y: 12.5, r: 1 },
    "heart":      { x: 11, y: 12.5, r: 1 }, 
    "nerves":     { x: 3, y: 12.5, r: 1 },
    "nervous":    { x: 3, y: 12.5, r: 1 }
};

function createMarker(x, y, rank, isScar=false, location=null, isBandaged=false) {
    const group = document.createElementNS(svgNS, 'g');
    
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', x);
    circle.setAttribute('cy', y);
    circle.setAttribute('r', 1.2); 
    
    // Apply classes for styling
    if (isScar) {
        circle.classList.add('scar-marker');
    } else {
        circle.classList.add('wound-marker');
        if (isBandaged) {
            circle.classList.add('bandaged');
        } else {
            circle.classList.add('fresh');
        }
    }

    const text = document.createElementNS(svgNS, 'text');
    text.setAttribute('x', x);
    text.setAttribute('y', y);
    text.classList.add('marker-text');
    if (isScar) text.classList.add('scar');
    text.textContent = rank;
    
    group.appendChild(circle);
    group.appendChild(text);

    // Context Menu Handler
    if (!isScar && location) {
        group.style.cursor = 'pointer';
        
        const title = document.createElementNS(svgNS, 'title');
        let status = isBandaged ? " (Bandaged)" : " (Bleeding)";
        title.textContent = `${location.replace(/_/g, ' ')}${status}`;
        group.appendChild(title);

        group.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            const readableLoc = location.replace(/_/g, ' ');
            activeKeyword = readableLoc;

            // Populate Context Menu with Tend/Diagnose
            contextMenu.innerHTML = '';
            
            const actions = ['tend', 'diagnose'];
            actions.forEach(verb => {
                const item = document.createElement('div');
                item.innerText = `${verb.toUpperCase()} ${readableLoc}`;
                item.dataset.command = `${verb} my ${readableLoc}`; // Implicitly 'my'
                contextMenu.appendChild(item);
            });

            // Position Menu
            contextMenu.style.left = `${e.pageX}px`;
            contextMenu.style.top = `${e.pageY}px`;
            contextMenu.style.display = 'block';
        });
    }
    
    injurySvg.appendChild(group);
}

function updateGuiPanels(vitals) {
    if (!vitals) return;
    
    if (vitals.exp_to_next !== undefined) {
        expValue.innerText = vitals.exp_to_next.toLocaleString();
        expLabel.innerText = vitals.exp_label || "until next level";
        expFill.style.width = `${vitals.exp_percent || 0}%`;
    }

    // Clear old markers
    const markers = injurySvg.querySelectorAll('.wound-marker, .scar-marker, .marker-text');
    markers.forEach(m => {
        if (m.parentElement && m.parentElement.tagName === 'g') {
            m.parentElement.remove();
        } else {
            m.remove();
        }
    });

    // Draw Scars first (underneath)
    if (vitals.scars) {
        for (const [location, rank] of Object.entries(vitals.scars)) {
            // Check both original key and normalized key
            const coords = WOUND_COORDS[location.toLowerCase()] || WOUND_COORDS[location.replace(" ", "_")];
            
            if (coords && rank > 0) {
                // --- FIX: Check if active wound exists in same location ---
                // If there's a wound, skip rendering the scar
                if (vitals.wounds && vitals.wounds[location] > 0) {
                    continue;
                }
                // ---------------------------------------------------------

                let x = coords.x;
                // Removed shift logic (x -= 1.0)
                createMarker(x, coords.y, rank, true, location);
            }
        }
    }

    // Draw Wounds
    if (vitals.wounds) {
        for (const [location, rank] of Object.entries(vitals.wounds)) {
            const coords = WOUND_COORDS[location.toLowerCase()] || WOUND_COORDS[location.replace(" ", "_")];
            if (coords && rank > 0) {
                let x = coords.x;
                // Removed shift logic (x += 1.0) since scars are now hidden
                
                const isBandaged = vitals.bandages && vitals.bandages[location];
                createMarker(x, coords.y, rank, false, location, isBandaged);
            }
        }
    }

    if (vitals.stance) {
        stanceSelect.value = vitals.stance;
    }

    if (vitals.worn_items) {
        wornItemsList.innerHTML = ''; 
        const items = Object.values(vitals.worn_items);
        
        if (items.length === 0) {
            wornItemsList.innerHTML = 'You are not wearing anything.';
        } else {
            items.forEach(item => {
                wornItemsList.innerHTML += `
                    <div>
                        <span class="worn-item-slot">${item.slot_display}:</span>
                        <span class="worn-item-name">${item.name}</span>
                    </div>
                `;
            });
        }
    }
}

const ROOM_SIZE = 24;
const ROOM_GAP = 12; 
const ROOM_CENTER = ROOM_SIZE / 2;
const TOTAL_CELL_SIZE = ROOM_SIZE + ROOM_GAP;
const ARROW_LEN = 6; 

function drawMap(mapData, currentRoomId) {
    mapSvg.innerHTML = ''; 
    mapRoomName.innerText = 'Loading...';
    mapRoomExits.innerText = '...';
    
    const currentRoom = mapData[currentRoomId];
    if (!currentRoom || currentRoom.x === undefined || currentRoom.y === undefined) {
        mapRoomName.innerText = 'Unknown';
        return;
    }

    mapRoomName.innerText = currentRoom.name || "Unknown";
    
    const svgRect = mapSvg.getBoundingClientRect();
    const svgWidth = svgRect.width;
    const svgHeight = svgRect.height;
    
    const cX = currentRoom.x || 0;
    const cY = currentRoom.y || 0;
    const cZ = currentRoom.z || 0;
    const cInterior = currentRoom.interior_id || null; 
    
    const offsetX = (svgWidth / 2) - (cX * TOTAL_CELL_SIZE) - ROOM_CENTER;
    const offsetY = (svgHeight / 2) - (-cY * TOTAL_CELL_SIZE) - ROOM_CENTER;
    
    const allExits = new Set();
    
    for (const roomId in mapData) {
        const room = mapData[roomId];
        const roomZ = room.z || 0;
        const roomInterior = room.interior_id || null;
        
        if (room.x === undefined || room.y === undefined || roomZ !== cZ || roomInterior !== cInterior) {
            continue;
        }
        
        const rX = offsetX + (room.x * TOTAL_CELL_SIZE);
        const rY = offsetY + (-room.y * TOTAL_CELL_SIZE); 
        
        const g = document.createElementNS(svgNS, 'g');
        g.classList.add('map-room');
        if (roomId === currentRoomId) {
            g.classList.add('current');
        }
        
        const rect = document.createElementNS(svgNS, 'rect');
        rect.setAttribute('x', rX);
        rect.setAttribute('y', rY);
        rect.setAttribute('width', ROOM_SIZE);
        rect.setAttribute('height', ROOM_SIZE);
        rect.setAttribute('rx', 3);
        g.appendChild(rect);
        
        const exits = room.exits || {};
        const drawExit = (dir, x1, y1, x2, y2) => {
            const path = document.createElementNS(svgNS, 'path');
            path.setAttribute('d', `M ${x1} ${y1} L ${x2} ${y2}`);
            path.classList.add('map-exit');
            g.appendChild(path);
            if (roomId === currentRoomId) allExits.add(dir);
        };
        
        if (exits.north)    drawExit('N',  rX + ROOM_CENTER, rY, rX + ROOM_CENTER, rY - ARROW_LEN);
        if (exits.south)    drawExit('S',  rX + ROOM_CENTER, rY + ROOM_SIZE, rX + ROOM_CENTER, rY + ROOM_SIZE + ARROW_LEN);
        if (exits.east)     drawExit('E',  rX + ROOM_SIZE, rY + ROOM_CENTER, rX + ROOM_SIZE + ARROW_LEN, rY + ROOM_CENTER);
        if (exits.west)     drawExit('W',  rX, rY + ROOM_CENTER, rX - ARROW_LEN, rY + ROOM_CENTER);
        if (exits.northeast) drawExit('NE', rX + ROOM_SIZE, rY, rX + ROOM_SIZE + ARROW_LEN, rY - ARROW_LEN);
        if (exits.northwest) drawExit('NW', rX, rY, rX - ARROW_LEN, rY - ARROW_LEN);
        if (exits.southeast) drawExit('SE', rX + ROOM_SIZE, rY + ROOM_SIZE, rX + ROOM_SIZE + ARROW_LEN, rY + ROOM_SIZE + ARROW_LEN);
        if (exits.southwest) drawExit('SW', rX, rY + ROOM_SIZE, rX - ARROW_LEN, rY + ROOM_SIZE + ARROW_LEN);
        
        const specialExits = room.special_exits || [];
        let hasUp = false, hasDown = false, hasInOut = false;
        
        specialExits.forEach(exit => {
            const targetRoom = mapData[exit.target_room];
            if (targetRoom && targetRoom.z !== undefined) {
                if (targetRoom.z > cZ && (targetRoom.interior_id === cInterior || cInterior === null)) hasUp = true;
                if (targetRoom.z < cZ && (targetRoom.interior_id === cInterior || cInterior === null)) hasDown = true;
            }
            if (targetRoom && (targetRoom.z || 0) === cZ && targetRoom.interior_id !== cInterior) {
                hasInOut = true;
            }
            if (roomId === currentRoomId) allExits.add(exit.name.toUpperCase());
        });
        
        const text = document.createElementNS(svgNS, 'text');
        let symbol = '';
        if (hasUp) symbol = '▲';
        if (hasDown) symbol = '▼';
        if (hasInOut && !hasUp && !hasDown) symbol = '○'; 
        
        if (symbol) {
            text.setAttribute('x', rX + ROOM_CENTER);
            text.setAttribute('y', rY + ROOM_CENTER + 4);
            text.classList.add('map-special-exit');
            if (hasUp) text.classList.add('up');
            if (hasDown) text.classList.add('down');
            if (hasInOut) text.classList.add('inout');
            text.textContent = symbol;
            g.appendChild(text);
        }
        mapSvg.appendChild(g);
    }

    mapRoomExits.innerText = Array.from(allExits).join(', ') || 'None';
}

socket.on('command_response', (data) => {
    currentClientState = "in_game"; 
    
    if (data.game_state) {
        currentGameState = data.game_state;
    }
    
    if (data.messages) {
        data.messages.forEach(msg => addMessage(msg));
    }
    
    if (data.vitals) {
        updateVitals(data.vitals);
    }
    
    if (data.map_data && data.vitals && data.vitals.current_room_id) {
        drawMap(data.map_data, data.vitals.current_room_id);
    }
});

socket.on('message', (message) => {
    addMessage(message);
});
socket.on('group_chat', (message) => {
    addMessage(message, 'group-chat'); 
});
socket.on('group_chat_ooc', (message) => {
    addMessage(message, 'group-chat-ooc'); 
});
socket.on('band_chat', (message) => {
    addMessage(message, 'band-chat'); 
});

socket.on('tick', () => {
    if (currentClientState === "in_game" && currentGameState === "playing" && !rtTimer) {
        addMessage(">", "command-echo");
    }
});

socket.on('update_vitals', (data) => {
    if (data) {
        updateVitals(data);
    }
});

socket.on('connect', () => {
    console.log("Connected to server with ID:", socket.id);
});
socket.on('disconnect', () => {
    console.log("Disconnected from server.");
    addMessage("...Connection lost. Please refresh the page.", "command-echo");
    currentClientState = "login_user";
    input.type = 'text';
    input.disabled = true;
});
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
    addMessage(message, "command-echo");
});
socket.on('show_char_list', (data) => {
    addMessage("--- Your Characters ---");
    data.chars.forEach(charName => {
        addMessage(`- <span class="keyword" data-command="${charName}">${charName}</span>`);
    });
    addMessage("\nType a character name to login, or type '<span class='keyword' data-command='create'>create</span>' to make a new one.");
    currentClientState = "char_select";
    input.type = 'text';
    input.disabled = false;
});
socket.on('prompt_create_character', () => {
    addMessage("Please enter a name for your new character:");
    currentClientState = "char_create_name";
    input.type = 'text';
    input.disabled = false;
});
socket.on('name_taken', () => {
    addMessage("That name is already taken. Please choose another:");
    currentClientState = "char_create_name";
});
socket.on('name_invalid', (message) => {
    addMessage(message);
    addMessage("Please enter a name for your new character:");
    currentClientState = "char_create_name";
});
socket.on('char_invalid', (message) => {
    addMessage(message);
});

input.addEventListener('keydown', async function(event) {
    if (event.key === 'Tab') {
        event.preventDefault(); 
        
        const currentText = input.value;
        if (!currentText) return;
        
        const matches = COMMON_COMMANDS.filter(cmd => cmd.startsWith(currentText.toLowerCase()));
        
        if (matches.length === 1) {
            input.value = matches[0] + " ";
        } else if (matches.length > 1) {
            input.value = matches[0] + " ";
        }
        return;
    }

    if (event.key === 'Enter') {
        const commandText = input.value;
        if (!commandText && currentClientState !== 'login_pass') return;
        if (currentClientState === "in_game" && commandText && commandText !== commandHistory[0]) {
            commandHistory.unshift(commandText);
            if (commandHistory.length > 50) {
                commandHistory.pop();
            }
        }
        historyIndex = -1;
        input.value = '';
        if (currentClientState === 'login_pass') {
            addMessage('> ********', 'command-echo');
        } else {
            addMessage(`> ${commandText}`, 'command-echo');
        }
        sendCommand(commandText);
        if (currentClientState === 'login_pass') {
            input.type = 'text';
        }
    }
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

output.addEventListener('click', function(event) {
    const target = event.target;
    if (target.classList.contains('keyword')) {
        event.preventDefault();
        event.stopPropagation();
        const command = target.dataset.command;
        if (command) {
            input.value = ''; 
            addMessage(`> ${command}`, 'command-echo');
            sendCommand(command);
            return; 
        }
        const keyword = target.dataset.name || target.innerText;
        if (currentGameState === "chargen") {
            input.value = '';
            addMessage(`> ${target.innerText}`, 'command-echo');
            sendCommand(target.innerText); 
        } else if (currentClientState === "in_game") {
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
    if (command && currentClientState === "in_game") {
        input.value = ''; 
        addMessage(`> ${command}`, 'command-echo');
        sendCommand(command); 
    }
});

panelToggleButton.addEventListener('click', () => {
    leftPanel.classList.toggle('collapsed');
    if (leftPanel.classList.contains('collapsed')) {
        panelToggleButton.innerText = '»';
    } else {
        panelToggleButton.innerText = '«';
    }
});

leftPanel.addEventListener('click', (e) => {
    const header = e.target.closest('.widget-header');
    if (header) {
        const rect = header.getBoundingClientRect();
        const clickX = e.clientX;
        if (clickX > rect.right - 30) {
            e.preventDefault();
            e.stopPropagation();
            header.closest('.widget').classList.toggle('minimized');
        }
    }
});

let draggedWidget = null;

leftPanel.addEventListener('dragstart', (e) => {
    if (e.target.classList.contains('widget-header')) {
        draggedWidget = e.target.closest('.widget');
        if (draggedWidget.classList.contains('minimized')) {
            draggedWidget = null;
            e.preventDefault();
            return;
        }
        draggedWidget.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
    }
});

leftPanel.addEventListener('dragend', (e) => {
    if (draggedWidget) {
        draggedWidget.classList.remove('dragging');
        draggedWidget = null;
    }
});

leftPanel.addEventListener('dragover', (e) => {
    e.preventDefault(); 
    
    const targetWidget = e.target.closest('.widget');
    if (targetWidget && draggedWidget && targetWidget !== draggedWidget) {
        const rect = targetWidget.getBoundingClientRect();
        const offsetY = e.clientY - rect.top;
        
        if (offsetY < rect.height / 2) {
            leftPanel.insertBefore(draggedWidget, targetWidget);
        } else {
            leftPanel.insertBefore(draggedWidget, targetWidget.nextSibling);
        }
    }
});

stanceSelect.addEventListener('change', (e) => {
    sendCommand(`stance ${e.target.value}`);
});

stowMainhandBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (currentVitals && currentVitals.worn_items.mainhand) {
        const itemName = currentVitals.worn_items.mainhand.name;
        sendCommand(`remove ${itemName.toLowerCase()}`);
    } else {
        addMessage("You are not holding anything in your main hand.");
    }
});

stowOffhandBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (currentVitals && currentVitals.worn_items.offhand) {
        const itemName = currentVitals.worn_items.offhand.name;
        sendCommand(`remove ${itemName.toLowerCase()}`);
    } else {
        addMessage("You are not holding anything in your off hand.");
    }
});

updateVitals({
    hp: 0, max_hp: 0,
    mana: 0, max_mana: 0,
    stamina: 0, max_stamina: 0,
    spirit: 0, max_spirit: 0,
    posture: "...",
    status_effects: [],
    rt_end_time_ms: 0,
    rt_type: "hard",
    stance: "neutral",
    wounds: {},
    scars: {},
    exp_to_next: 0,
    exp_label: "...",
    exp_percent: 0,
    worn_items: {}
});