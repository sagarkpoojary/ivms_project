document.addEventListener('DOMContentLoaded', () => {
    const launcher = document.getElementById('aiChatLauncher');
    const container = document.getElementById('aiChatContainer');
    const closeBtn = document.getElementById('aiChatCloseBtn');
    const chatInput = document.getElementById('aiChatInput');
    const sendBtn = document.getElementById('aiChatSendBtn');
    const messagesView = document.getElementById('aiChatMessages');
    const suggestions = document.querySelectorAll('.ai-suggestion-pill');
    
    // Toggle Chat widget visibility
    if (launcher && container) {
        launcher.addEventListener('click', () => {
            container.classList.toggle('active');
            if (container.classList.contains('active')) {
                chatInput.focus();
                // Scroll to latest message
                scrollToBottom();
            }
        });
    }
    
    if (closeBtn && container) {
        closeBtn.addEventListener('click', () => {
            container.classList.remove('active');
        });
    }

    // Handle suggestion triggers
    suggestions.forEach(pill => {
        pill.addEventListener('click', () => {
            const prompt = pill.getAttribute('data-prompt');
            if (prompt) {
                submitPrompt(prompt);
            }
        });
    });

    // Handle button click or Enter key submission
    if (sendBtn && chatInput) {
        sendBtn.addEventListener('click', () => {
            const text = chatInput.value.trim();
            if (text) {
                submitPrompt(text);
                chatInput.value = '';
            }
        });

        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const text = chatInput.value.trim();
                if (text) {
                    submitPrompt(text);
                    chatInput.value = '';
                }
            }
        });
    }

    function scrollToBottom() {
        if (messagesView) {
            messagesView.scrollTop = messagesView.scrollHeight;
        }
    }

    function createTypingIndicator() {
        const bubble = document.createElement('div');
        bubble.className = 'ai-msg ai-msg-bot ai-typing-indicator-wrapper';
        bubble.id = 'aiTypingIndicator';
        
        const indicator = document.createElement('div');
        indicator.className = 'ai-typing-indicator';
        
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement('div');
            dot.className = 'ai-typing-dot';
            indicator.appendChild(dot);
        }
        
        bubble.appendChild(indicator);
        return bubble;
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById('aiTypingIndicator');
        if (indicator) {
            indicator.remove();
        }
    }

    function safeEscape(text) {
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function renderMarkdown(text) {
        // Strip any think blocks that slipped through
        text = text.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
        
        // Escape content safely to prevent XSS
        text = safeEscape(text);
        
        // Check if there are markdown tables and parse them
        const lines = text.split('\n');
        let inTable = false;
        let tableHTML = '';
        const parsedLines = [];

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            
            if (line.startsWith('|') && line.endsWith('|')) {
                if (!inTable) {
                    inTable = true;
                    tableHTML = '<div class="table-responsive"><table class="table table-sm">';
                }
                const cells = line.split('|')
                    .map(c => c.trim())
                    .filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
                
                if (line.match(/^\|[\s-|-]*\|$/)) {
                    continue;
                }
                
                tableHTML += '<tr>';
                cells.forEach(cell => {
                    const tag = (tableHTML.match(/<tr>/g).length === 1) ? 'th' : 'td';
                    tableHTML += `<${tag}>${cell}</${tag}>`;
                });
                tableHTML += '</tr>';
            } else {
                if (inTable) {
                    inTable = false;
                    tableHTML += '</table></div>';
                    parsedLines.push(tableHTML);
                    tableHTML = '';
                }
                parsedLines.push(line);
            }
        }
        
        if (inTable) {
            tableHTML += '</table></div>';
            parsedLines.push(tableHTML);
        }
        
        let processedText = parsedLines.join('\n');
        
        // Headers
        processedText = processedText.replace(/^### (.+)$/gm, '<h4>$1</h4>');
        processedText = processedText.replace(/^## (.+)$/gm, '<h3>$1</h3>');
        processedText = processedText.replace(/^# (.+)$/gm, '<h2>$1</h2>');
        
        // Bold
        processedText = processedText.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        
        // Bullet points
        processedText = processedText.replace(/^[•\-\*] (.+)$/gm, '<li>$1</li>');
        processedText = processedText.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
        
        // Line breaks
        processedText = processedText.replace(/\n\n/g, '</p><p>');
        processedText = processedText.replace(/\n/g, '<br>');
        
        return '<p>' + processedText + '</p>';
    }

    function renderReportCard(pdfUrl, filename) {
        const safeUrl = safeEscape(pdfUrl);
        const safeFilename = safeEscape(filename);
        const card = document.createElement('div');
        card.className = 'ai-report-card';
        card.innerHTML = `
            <div class="report-icon">📄</div>
            <div class="report-info">
                <span class="report-name">${safeFilename}</span>
                <span class="report-meta">PDF Report · Ready to download</span>
            </div>
            <a href="${safeUrl}" target="_blank" class="report-download-btn">
                ⬇ Download
            </a>
        `;
        return card;
    }

    function appendMessage(text, isUser, isMarkdown = false) {
        if (!messagesView) return;
        
        const bubble = document.createElement('div');
        bubble.className = `ai-msg ${isUser ? 'ai-msg-user' : 'ai-msg-bot'}`;
        
        if (isUser) {
            bubble.textContent = text;
        } else {
            // Use elements innerHTML with the new lightweight renderMarkdown parser
            bubble.innerHTML = renderMarkdown(text);
        }
        
        messagesView.appendChild(bubble);
        scrollToBottom();
    }

    async function submitPrompt(promptText) {
        if (!messagesView) return;
        
        // Append user prompt bubble
        appendMessage(promptText, true);
        
        // Append typing indicator
        const indicator = createTypingIndicator();
        messagesView.appendChild(indicator);
        scrollToBottom();
        
        // Retrieve CSRF Token from meta elements
        const csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute('content') : '';
        
        try {
            const response = await fetch('/ai/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify({ message: promptText })
            });
            
            removeTypingIndicator();
            
            if (response.ok) {
                const data = await response.json();
                appendMessage(data.response, false, true);
                if (data.pdf_url && data.filename) {
                    const card = renderReportCard(data.pdf_url, data.filename);
                    messagesView.appendChild(card);
                    scrollToBottom();
                }
            } else {
                const data = await response.json();
                appendMessage(`Sorry, I encountered an error: ${data.error || 'Server error'}`, false);
            }
        } catch (err) {
            removeTypingIndicator();
            appendMessage(`Sorry, I couldn't connect to the AI service. Please check your network connection.`, false);
        }
    }
});
