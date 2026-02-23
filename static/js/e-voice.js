// Get DOM elements
const startRecordBtn = document.getElementById('start-record');
const messageInput = document.getElementById('message-input');
const chatBox = document.getElementById('chat-box');

// Check browser support for SpeechRecognition
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SpeechRecognition) {
    startRecordBtn.disabled = true;
    startRecordBtn.title = "Voice input not supported on this browser.";
    console.warn("Speech recognition not supported.");
} else {
    const recognition = new SpeechRecognition();

    // Setup recognition
    recognition.lang = 'en-US';
    recognition.continuous = false;
    recognition.interimResults = true;

    let finalTranscript = '';

    // Start recognition on button click
    startRecordBtn.addEventListener('click', () => {
        finalTranscript = '';
        recognition.start();
        startRecordBtn.textContent = "🎙️ Listening...";
    });

    // On speech result (live and final)
    recognition.onresult = (event) => {
        let interimTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                finalTranscript += transcript + ' ';
            } else {
                interimTranscript += transcript;
            }
        }

        messageInput.value = finalTranscript + interimTranscript;
    };

    // On recognition end
    recognition.onend = () => {
        startRecordBtn.textContent = "🎤";
        if (finalTranscript.trim()) {
            messageInput.value = finalTranscript.trim();
            sendMessage();
        }
    };

    // On error
    recognition.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        startRecordBtn.textContent = "🎤";
    };
}

// Send message from input
function sendMessage() {
    const message = messageInput.value.trim();
    if (message !== "") {
        displayMessage(message, 'sent');
        messageInput.value = "";
    }
}

// Display message in chat
function displayMessage(text, type) {
    const messageElement = document.createElement('div');
    messageElement.className = `message ${type}`; // 'sent' or 'received'
    messageElement.textContent = text;
    chatBox.appendChild(messageElement);
    chatBox.scrollTop = chatBox.scrollHeight;
}
