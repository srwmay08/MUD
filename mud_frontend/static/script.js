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
// --- END NEW ---

// --- MODIFIED: Renamed mapPanel to leftPanel ---
const leftPanel = document.getElementById('left-panel');
const panelToggleButton = document.getElementById('panel-toggle-button'); // MODIFIED
const mapSvg = document.getElementById('map-svg');
const mapRoomName = document.getElementById('map-room-name');
const mapRoomExits = document.getElementById('map-room-exits');
const svgNS = "http://www.w3.org/2000/svg"; 

// --- NEW: Get new Widget elements ---
const stanceSelect = document.getElementById('stance-select');
const stowMainhandBtn = document.getElementById('stow-mainhand-btn');
const stowOffhandBtn = document.getElementById('stow-offhand-btn');
const expValue = document.getElementById('exp-value');
const expLabel = document.getElementById('exp-label');
const expFill = document.getElementById('exp-fill');
const injurySvg = document.getElementById('injury-svg');
const wornItemsList = document.getElementById('worn-items-list');
// --- END NEW ---

// --- NEW: Initialize Socket.IO connection ---
const socket = io();

// --- Client-side state ---
let activeKeyword = null;
let playerName = null; 
let currentGameState = "login"; 
let currentClientState = "login_user"; 
// --- NEW: Client-side vitals cache ---
let currentVitals = null;
// ---
let commandHistory = [];
let historyIndex = -1;
let rtEndTime = 0;
let rtTimer = null;


// --- Helper: Send Command to Backend (Unchanged) ---
function sendCommand(command) {
    socket.emit('command', {
        command: command
    });
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

// ---
// --- GUI Update Functions
// ---

function updateRtDisplay() {
    // (This function is unchanged)
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
    // (This function is unchanged)
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
    
    // --- NEW: Store vitals globally ---
    currentVitals = vitals;

    // 1. Update Gauges
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

    // 2. Update Posture & Status
    let statusText = vitals.posture || "Unknown";
    if (vitals.status_effects && vitals.status_effects.length > 0) {
        statusText += ` (${vitals.status_effects.join(', ')})`;
    }
    postureStatusEl.innerText = statusText;

    // 3. Update Roundtime
    if (vitals.rt_end_time_ms > Date.now()) {
        startRtTimer(vitals.rt_duration_ms, vitals.rt_end_time_ms, vitals.rt_type || 'hard');
    }
    
    // --- NEW: 4. Update GUI Panels ---
    updateGuiPanels(vitals);
}

// ---
// --- NEW: Wound Marker Creation
// ---

// ---
// --- THIS IS THE FIX
// ---
// New coordinates mapped to the "0 0 16 16" viewBox of the bi-person-standing icon.
const WOUND_COORDS = {
    "head":       { x: 8, y: 1.5, r: 1.5 },
    "neck":       { x: 8, y: 3.5, r: 0.5 },
    "chest":      { x: 8, y: 6, r: 2 },
    "abdomen":    { x: 8, y: 8.5, r: 2 },
    "back":       { x: 8, y: 7, r: 2 }, // Slightly offset from chest
    "right_eye":  { x: 7.5, y: 1.2, r: 0.5 },
    "left_eye":   { x: 8.5, y: 1.2, r: 0.5 },
    "right_arm":  { x: 5.5, y: 8, r: 1.5 }, // Player's right, SVG's left
    "left_arm":   { x: 10.5, y: 8, r: 1.5 }, // Player's left, SVG's right
    "right_hand": { x: 5, y: 9.5, r: 1 },
    "left_hand":  { x: 11, y: 9.5, r: 1 },
    "right_leg":  { x: 6.75, y: 12.5, r: 2 },
    "left_leg":   { x: 9.25, y: 12.5, r: 2 }
};
// --- END FIX ---

function createWoundMarker(x, y, rank) {
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', x);
    circle.setAttribute('cy', y);
    // --- THIS IS THE FIX ---
    // Use a smaller, 1px radius to fit the new 16x16 coordinate system
    circle.setAttribute('r', 1); 
    // --- END FIX ---
    circle.classList.add('wound-marker');
    
    // You could vary size/color based on rank
    // circle.setAttribute('r', 0.5 + (rank * 0.5)); 
    
    injurySvg.appendChild(circle);
}

// ---
// --- NEW: Main GUI Panel Update Function
// ---
function updateGuiPanels(vitals) {
    if (!vitals) return;
    
    // 1. Update Experience Widget
    if (vitals.exp_to_next !== undefined) {
        expValue.innerText = vitals.exp_to_next.toLocaleString();
        expLabel.innerText = vitals.exp_label || "until next level";
        expFill.style.width = `${vitals.exp_percent || 0}%`;
    }

    // 2. Update Injuries Widget
    // Clear old wounds
    injurySvg.querySelectorAll('.wound-marker').forEach(m => m.remove());
    if (vitals.wounds) {
        for (const [location, rank] of Object.entries(vitals.wounds)) {
            const coords = WOUND_COORDS[location];
            if (coords) {
                createWoundMarker(coords.x, coords.y, rank);
            }
        }
    }

    // 3. Update Combat Widget
    if (vitals.stance) {
        stanceSelect.value = vitals.stance;
    }

    // 4. Update Inventory Widget
    if (vitals.worn_items) {
        wornItemsList.innerHTML = ''; // Clear list
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


// ---
// --- MAP DRAWING FUNCTION (THIS IS THE FIX)
// ---
const ROOM_SIZE = 24;
const ROOM_GAP = 12; 
const ROOM_CENTER = ROOM_SIZE / 2;
const TOTAL_CELL_SIZE = ROOM_SIZE + ROOM_GAP;
const ARROW_LEN = 6; 

function drawMap(mapData, currentRoomId) {
    // ---
    // --- THIS IS THE FIX: Clear map elements *before* checking for the room
    // ---
    mapSvg.innerHTML = ''; 
    mapRoomName.innerText = 'Loading...';
    mapRoomExits.innerText = '...';
    // ---
    // --- END FIX
    // ---
    
    const currentRoom = mapData[currentRoomId];
    if (!currentRoom || currentRoom.x === undefined || currentRoom.y === undefined) {
        mapRoomName.innerText = 'Unknown';
        return;
    }

    // ---
    // --- THIS IS THE FIX: Set the room name *before* the drawing loop
    // ---
    mapRoomName.innerText = currentRoom.name || "Unknown";
    // ---
    // --- END FIX
    // ---
    
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

    // ---
    // --- THIS IS THE FIX: Set exits at the end
    // ---
    mapRoomExits.innerText = Array.from(allExits).join(', ') || 'None';
    // ---
    // --- END FIX
    // ---
}


// ---
// --- WEBSOCKET EVENT LISTENERS (Unchanged logic, just calls new func)
// ---

socket.on('command_response', (data) => {
    currentClientState = "in_game"; 
    
    if (data.game_state) {
        currentGameState = data.game_state;
    }
    
    if (data.messages) {
        data.messages.forEach(msg => addMessage(msg));
    }
    
    if (data.vitals) {
        updateVitals(data.vitals); // This will now call updateGuiPanels
    }
    
    if (data.map_data && data.vitals && data.vitals.current_room_id) {
        drawMap(data.map_data, data.vitals.current_room_id);
    }
});

socket.on('message', (message) => {
    addMessage(message);
});
// ---
// --- NEW: Added listeners for group/band chat
// ---
socket.on('group_chat', (message) => {
    addMessage(message, 'group-chat'); // You'll need to add a 'group-chat' style
});
socket.on('group_chat_ooc', (message) => {
    addMessage(message, 'group-chat-ooc'); // You'll need to add a 'group-chat-ooc' style
});
socket.on('band_chat', (message) => {
    addMessage(message, 'band-chat'); // You'll need to add a 'band-chat' style
});
// --- END NEW ---


socket.on('tick', () => {
    if (currentClientState === "in_game" && currentGameState === "playing" && !rtTimer) {
        addMessage(">", "command-echo");
    }
});

socket.on('update_vitals', (data) => {
    if (data) {
        updateVitals(data); // This will now call updateGuiPanels
    }
});

// (All login/auth flow listeners are unchanged)
// ...
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

// ---
// --- INPUT LISTENERS
// ---

// (Input 'keydown' listener for Enter/ArrowUp/ArrowDown is unchanged)
// ...
input.addEventListener('keydown', async function(event) {
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


// (All click listeners for context menu and output are unchanged)
// ...
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

// ---
// --- NEW: WIDGET AND PANEL EVENT LISTENERS
// ---

// --- Panel Toggle Button ---
panelToggleButton.addEventListener('click', () => {
    leftPanel.classList.toggle('collapsed');
    if (leftPanel.classList.contains('collapsed')) {
        panelToggleButton.innerText = '»';
    } else {
        panelToggleButton.innerText = '«';
    }
});

// --- Widget Minimize ---
leftPanel.addEventListener('click', (e) => {
    // Check if the click was on the header's pseudo-element (::after)
    // We do this by checking click position relative to the header's right edge
    const header = e.target.closest('.widget-header');
    if (header) {
        const rect = header.getBoundingClientRect();
        const clickX = e.clientX;
        // If click is on the "button" area (last 30px)
        if (clickX > rect.right - 30) {
            e.preventDefault();
            e.stopPropagation();
            header.closest('.widget').classList.toggle('minimized');
        }
    }
});

// --- Widget Drag and Drop ---
let draggedWidget = null;

leftPanel.addEventListener('dragstart', (e) => {
    if (e.target.classList.contains('widget-header')) {
        draggedWidget = e.target.closest('.widget');
        // Check if the widget is minimized, if so, don't allow drag
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
    e.preventDefault(); // Necessary to allow drop
    
    const targetWidget = e.target.closest('.widget');
    if (targetWidget && draggedWidget && targetWidget !== draggedWidget) {
        const rect = targetWidget.getBoundingClientRect();
        // Get mouse position relative to the target widget
        const offsetY = e.clientY - rect.top;
        
        // If dragging over the top half, insert before, else insert after
        if (offsetY < rect.height / 2) {
            leftPanel.insertBefore(draggedWidget, targetWidget);
        } else {
            // insertAfter
            leftPanel.insertBefore(draggedWidget, targetWidget.nextSibling);
        }
    }
});

// --- Combat Widget Actions ---
stanceSelect.addEventListener('change', (e) => {
    sendCommand(`stance ${e.target.value}`);
});

stowMainhandBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (currentVitals && currentVitals.worn_items.mainhand) {
        const itemName = currentVitals.worn_items.mainhand.name;
        // --- FIX: Use REMOVE command to stow ---
        sendCommand(`remove ${itemName.toLowerCase()}`);
    } else {
        addMessage("You are not holding anything in your main hand.");
    }
});

stowOffhandBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (currentVitals && currentVitals.worn_items.offhand) {
        const itemName = currentVitals.worn_items.offhand.name;
        // --- FIX: Use REMOVE command to stow ---
        sendCommand(`remove ${itemName.toLowerCase()}`);
    } else {
        addMessage("You are not holding anything in your off hand.");
    }
});


// --- Initialize GUI on load (Unchanged) ---
updateVitals({
    hp: 0, max_hp: 0,
    mana: 0, max_mana: 0,
    stamina: 0, max_stamina: 0,
    spirit: 0, max_spirit: 0,
    posture: "...",
    status_effects: [],
    rt_end_time_ms: 0,
    rt_type: "hard",
    // --- NEW: Add defaults for new GUI ---
    stance: "neutral",
    wounds: {},
    exp_to_next: 0,
    exp_label: "...",
    exp_percent: 0,
    worn_items: {}
});