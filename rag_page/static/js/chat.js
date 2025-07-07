// 병무청 모집병 상담 페이지 JavaScript

let currentSessionId = null;
let currentSessionName = null;
let ws = null;
let isTyping = false;

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    // 현재 세션 정보 가져오기
    currentSessionId = localStorage.getItem('currentSessionId');
    currentSessionName = localStorage.getItem('currentSessionName');
    
    // 세션 목록 로드
    loadSessions(() => {
        if (currentSessionId) {
            updateSessionInfo();
            loadSessionHistory();
        } else {
            updateSessionInfo();
            clearChatMessages();
        }
    });
    
    setupTextareaAutoResize();
});

// 새 세션 생성
function createNewSession(callback = null) {
    showLoading();
    
    fetch('/create-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        hideLoading();
        
        if (data.session_id) {
            currentSessionId = data.session_id;
            currentSessionName = data.session_name;
            
            localStorage.setItem('currentSessionId', currentSessionId);
            localStorage.setItem('currentSessionName', currentSessionName);
            
            updateSessionInfo();
            clearChatMessages();
            connectWebSocket();
            loadSessions();

            if (typeof callback === 'function') {
                callback();
            }
        } else {
            alert('세션 생성에 실패했습니다.');
        }
    })
    .catch(error => {
        hideLoading();
        console.error('Error:', error);
        alert('세션 생성 중 오류가 발생했습니다.');
    });
}

// 세션 정보 업데이트
function updateSessionInfo() {
    document.getElementById('currentSessionName').textContent = currentSessionName || '새 상담';
    document.getElementById('currentSessionId').textContent = currentSessionId ? `ID: ${currentSessionId.substring(0, 8)}...` : '';
}

// 세션 목록 로드
function loadSessions(callback) {
    fetch('/sessions')
    .then(response => response.json())
    .then(data => {
        const sessionList = document.getElementById('sessionList');
        sessionList.innerHTML = '';
        
        if (data.sessions && data.sessions.length > 0) {
            data.sessions.forEach(session => {
                const sessionItem = createSessionItem(session);
                sessionList.appendChild(sessionItem);
            });
        } else {
            sessionList.innerHTML = '<div class="no-sessions">상담 기록이 없습니다.\n새 상담을 시작해보세요!</div>';
            currentSessionId = null;
            currentSessionName = null;
            localStorage.removeItem('currentSessionId');
            localStorage.removeItem('currentSessionName');
        }
        if (callback) callback();
    })
    .catch(error => {
        console.error('Error loading sessions:', error);
        if (callback) callback();
    });
}

// 세션 아이템 생성
function createSessionItem(session) {
    const div = document.createElement('div');
    div.className = 'session-item';
    if (session.session_id === currentSessionId) {
        div.classList.add('active');
    }
    
    const createdAt = new Date(session.created_at).toLocaleString('ko-KR');
    
    div.innerHTML = `
        <div class="session-item-header">
            <span class="session-name">${session.name}</span>
            <div class="session-actions">
                <button onclick="deleteSession('${session.session_id}', event)" title="삭제">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
        <div class="session-meta">
            <span class="session-time">${createdAt}</span>
            <span>${session.message_count}개 메시지</span>
        </div>
    `;
    
    div.addEventListener('click', (e) => {
        if (!e.target.closest('.session-actions')) {
            loadSession(session.session_id);
        }
    });
    
    return div;
}

// 세션 로드
function loadSession(sessionId) {
    if (sessionId === currentSessionId) return;
    
    showLoading();
    
    fetch(`/sessions/${sessionId}`)
    .then(response => response.json())
    .then(data => {
        hideLoading();
        
        currentSessionId = data.session_id;
        currentSessionName = data.session_info.name;
        
        localStorage.setItem('currentSessionId', currentSessionId);
        localStorage.setItem('currentSessionName', currentSessionName);
        
        updateSessionInfo();
        loadSessionHistory();
        
        if (ws) ws.close();
        connectWebSocket();
        
        loadSessions();
    })
    .catch(error => {
        hideLoading();
        console.error('Error loading session:', error);
        alert('세션을 불러오는 중 오류가 발생했습니다.');
    });
}

// 세션 삭제
function deleteSession(sessionId, event) {
    event.stopPropagation();

    if (!confirm('이 상담을 삭제하시겠습니까?')) return;

    fetch(`/sessions/${sessionId}`, { method: 'DELETE' })
    .then(() => {
        if (sessionId === currentSessionId) {
            fetch('/sessions')
            .then(response => response.json())
            .then(listData => {
                if (listData.sessions && listData.sessions.length > 0) {
                    loadSession(listData.sessions[0].session_id);
                } else {
                    currentSessionId = null;
                    currentSessionName = null;
                    localStorage.removeItem('currentSessionId');
                    localStorage.removeItem('currentSessionName');
                    updateSessionInfo();
                    clearChatMessages();
                }
                loadSessions();
            });
        } else {
            loadSessions();
        }
    })
    .catch(error => {
        console.error('Error deleting session:', error);
        alert('세션 삭제 중 오류가 발생했습니다.');
    });
}

// 세션 히스토리 로드
function loadSessionHistory() {
    if (!currentSessionId) return;
    
    fetch(`/sessions/${currentSessionId}`)
    .then(response => response.json())
    .then(data => {
        clearChatMessages();
        
        if (data.chat_history) {
            data.chat_history.forEach(item => {
                if (item.question) addMessage(item.question, 'user');
                if (item.answer) addMessage(item.answer, 'assistant');
            });
        }
    })
    .catch(error => console.error('Error loading session history:', error));
}

// WebSocket 연결
function connectWebSocket() {
    if (!currentSessionId) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/${currentSessionId}`);
    
    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.type === 'bot_response' && data.response) {
            addMessage(data.response, 'assistant');
        }
        hideTypingIndicator();
    };
    
    ws.onclose = function() {
        setTimeout(() => { if (currentSessionId) connectWebSocket(); }, 3000);
    };
    
    ws.onerror = error => console.error('WebSocket 오류:', error);
}

// 메시지 전송
function sendMessage() {
    const input = document.getElementById('messageInput');
    const messageText = input.value.trim();

    if (!messageText || isTyping) return;

    if (!currentSessionId) {
        createNewSession(() => {
            input.value = messageText;
            sendMessage();
        });
        return;
    }

    addMessage(messageText, 'user');
    input.value = '';
    input.style.height = 'auto';
    showTypingIndicator();

    const payload = {
        type: 'user_message',
        message: messageText,
        session_id: currentSessionId
    };

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(payload));
    } else {
        fetch(`/chat/${currentSessionId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: messageText })
        })
        .then(response => response.json())
        .then(data => {
            if (data.response) addMessage(data.response, 'assistant');
            hideTypingIndicator();
        })
        .catch(error => {
            console.error('Error sending message:', error);
            addMessage('메시지 전송에 실패했습니다.', 'assistant');
            hideTypingIndicator();
        });
    }
}

// 메시지 추가
function addMessage(content, role) {
    const chatMessages = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}-message`;
    const avatar = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
    const time = new Date().toLocaleString('ko-KR');

    function processText(text) {
        text = text.replace(/[&<>"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;','"': '&quot;','\'': '&#39;'}[tag] || tag));
        text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/(\[출처\s*:\s*[^\]]+\])/g, '<span class="source-citation">$1</span>');
        return text.replace(/\n/g, '<br>');
    }

    let html = '';
    let codeBlockRegex = /```(\w+)?([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;
    
    while ((match = codeBlockRegex.exec(content)) !== null) {
        if (match.index > lastIndex) {
            html += `<div class='message-desc'>${processText(content.substring(lastIndex, match.index).trim())}</div>`;
        }
        const lang = match[1] || '';
        const code = match[2].trim();
        const escapedCode = code.replace(/[&<>"]/g, tag => ({'&': '&amp;','<': '&lt;','>': '&gt;','"': '&quot;','\'': '&#39;'}[tag] || tag));
        html += `<div class='code-block-card'><button class='copy-btn' onclick='copyCode(this)'>복사</button><pre><code class='language-${lang}'>${escapedCode}</code></pre></div>`;
        lastIndex = codeBlockRegex.lastIndex;
    }
    
    html += `<div class='message-desc'>${processText(content.substring(lastIndex).trim())}</div>`;

    messageDiv.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div class="message-text">${html}</div>
            <div class="message-time">${time}</div>
        </div>
    `;
    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

// 코드 복사 함수
function copyCode(btn) {
    navigator.clipboard.writeText(btn.nextElementSibling.innerText).then(() => {
        btn.textContent = '복사됨!';
        setTimeout(() => { btn.textContent = '복사'; }, 1200);
    });
}

// 채팅 메시지 지우기
function clearChatMessages() {
    document.getElementById('chatMessages').innerHTML = '';
}

// 대화 지우기
function clearChat() {
    if (confirm('현재 대화를 지우시겠습니까?')) clearChatMessages();
}

// 대화 내보내기
function exportChat() {
    if (!currentSessionId) return;
    
    fetch(`/sessions/${currentSessionId}`)
    .then(response => response.json())
    .then(data => {
        const chatData = {
            session_name: data.session_info.name,
            created_at: data.session_info.created_at,
            messages: data.chat_history
        };
        
        const blob = new Blob([JSON.stringify(chatData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat_${currentSessionId.substring(0, 8)}_${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        URL.revokeObjectURL(url);
    })
    .catch(error => {
        console.error('Error exporting chat:', error);
        alert('대화 내보내기에 실패했습니다.');
    });
}

// 홈으로 이동
function goHome() {
    window.location.href = '/';
}

// 키보드 이벤트 처리
document.getElementById('messageInput').addEventListener('keydown', function(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
});

// 텍스트 영역 자동 크기 조정
function setupTextareaAutoResize() {
    const textarea = document.getElementById('messageInput');
    textarea.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = `${Math.min(this.scrollHeight, 120)}px`;
    });
}

function showTypingIndicator() {
    isTyping = true;
    document.getElementById('typingIndicator').style.display = 'flex';
    scrollToBottom();
}

function hideTypingIndicator() {
    isTyping = false;
    document.getElementById('typingIndicator').style.display = 'none';
}

function scrollToBottom() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showLoading() {
    document.getElementById('loadingOverlay').classList.add('show');
}

function hideLoading() {
    document.getElementById('loadingOverlay').classList.remove('show');
}

// 키보드 단축키
document.addEventListener('keydown', function(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        createNewSession();
    }
    if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault();
        exportChat();
    }
    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        clearChat();
    }
});