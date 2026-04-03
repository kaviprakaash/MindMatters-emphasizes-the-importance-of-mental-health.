document.getElementById('chat-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const input = document.getElementById('message-input');
    const message = input.value.trim();
    if (!message) return;

    // Add user message
    addMessage('user', message);
    input.value = '';

    // Send to API
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: message }),
        });
        const data = await response.json();
        if (data.response) {
            addMessage('assistant', data.response);
        } else if (data.error) {
            addMessage('assistant', data.error);
        } else {
            addMessage('assistant', 'Sorry, I\'m having trouble responding right now. Please try again.');
        }
    } catch (error) {
        addMessage('assistant', 'Sorry, I\'m having trouble responding right now. Please try again.');
    }
});

function addMessage(sender, text) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'flex items-start space-x-3';

    if (sender === 'user') {
        messageDiv.innerHTML = `
            <div class="bg-indigo-100 p-2 rounded-lg flex-shrink-0">
                <i class="fas fa-user text-indigo-600 text-sm"></i>
            </div>
            <div class="bg-indigo-600 text-white rounded-lg px-4 py-3 shadow-sm max-w-xs lg:max-w-md ml-auto">
                <p class="text-sm">${text}</p>
            </div>
        `;
        messageDiv.classList.add('justify-end');
    } else {
        messageDiv.innerHTML = `
            <div class="gradient-bg p-2 rounded-lg flex-shrink-0">
                <i class="fas fa-robot text-white text-sm"></i>
            </div>
            <div class="bg-white rounded-lg px-4 py-3 shadow-sm max-w-xs lg:max-w-md">
                <p class="text-gray-800 text-sm">${text}</p>
            </div>
        `;
    }

    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}