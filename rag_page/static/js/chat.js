// 병무청 모집병 상담 페이지 JavaScript

let currentSessionId = null;
let currentSessionName = null;
let ws = null;
let isTyping = false;

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    console.log('병무청 상담 페이지 로드됨');
    
    // 현재 세션 정보 가져오기
    currentSessionId = localStorage.getItem('currentSessionId');
    currentSessionName = localStorage.getItem('currentSessionName');
    
    // 세션 목록 로드 (세션이 없으면 아무것도 선택하지 않음)
    loadSessions(() => {
        if (currentSessionId) {
            updateSessionInfo();
            loadSessionHistory();
        } else {
            // 세션이 없으면 화면 초기화
            updateSessionInfo();
            clearChatMessages();
        }
    });
    
    // 입력창 자동 크기 조정
    setupTextareaAutoResize();
});

// 새 세션 생성
function createNewSession(callback = null) {
    showLoading();
    
    fetch('/create-session', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        hideLoading();
        
        if (data.session_id) {
            currentSessionId = data.session_id;
            currentSessionName = data.session_name;
            
            // localStorage에 저장
            localStorage.setItem('currentSessionId', currentSessionId);
            localStorage.setItem('currentSessionName', currentSessionName);
            
            // UI 업데이트
            updateSessionInfo();
            clearChatMessages();
            
            // WebSocket 연결
            connectWebSocket();
            
            // 세션 목록 새로고침
            loadSessions();

            // 콜백 실행 (예: 첫 메시지 전송 등)
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
    
    // RAG 상태 업데이트
    updateRAGStatus();
}

// RAG 상태 업데이트
function updateRAGStatus() {
    const ragStatus = document.getElementById('ragStatus');
    if (currentSessionId) {
        // 세션 정보에서 RAG 상태 확인
        fetch('/sessions')
        .then(response => response.json())
        .then(data => {
            const currentSession = data.sessions.find(s => s.session_id === currentSessionId);
            if (currentSession && currentSession.has_rag) {
                ragStatus.style.display = 'block';
            } else {
                ragStatus.style.display = 'none';
            }
        })
        .catch(error => {
            console.error('Error updating RAG status:', error);
            ragStatus.style.display = 'none';
        });
    } else {
        ragStatus.style.display = 'none';
    }
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
            // 세션이 없으므로 현재 세션 정보 초기화
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
    const lastActivity = new Date(session.last_activity).toLocaleString('ko-KR');
    
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
            ${session.has_rag ? '<span class="rag-badge"><i class="fas fa-database"></i> 정보기반</span>' : ''}
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
        
        // localStorage 업데이트
        localStorage.setItem('currentSessionId', currentSessionId);
        localStorage.setItem('currentSessionName', currentSessionName);
        
        // UI 업데이트
        updateSessionInfo();
        loadSessionHistory();
        
        // WebSocket 재연결
        if (ws) {
            ws.close();
        }
        connectWebSocket();
        
        // 세션 목록 새로고침
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

    fetch(`/sessions/${sessionId}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        // 현재 세션이 삭제된 경우
        if (sessionId === currentSessionId) {
            // 남아있는 다른 세션이 있으면 그걸 선택, 없으면 화면 초기화
            fetch('/sessions')
            .then(response => response.json())
            .then(listData => {
                if (listData.sessions && listData.sessions.length > 0) {
                    // 첫 번째 세션으로 전환
                    const nextSession = listData.sessions[0];
                    currentSessionId = nextSession.session_id;
                    currentSessionName = nextSession.name;
                    localStorage.setItem('currentSessionId', currentSessionId);
                    localStorage.setItem('currentSessionName', currentSessionName);
                    updateSessionInfo();
                    loadSessionHistory();
                } else {
                    // 세션이 하나도 없으면 화면 초기화
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
            // 세션 목록만 새로고침
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
        
        if (data.chat_history && data.chat_history.length > 0) {
            data.chat_history.forEach(item => {
                if (item.question) addMessage(item.question, 'user');
                if (item.answer) addMessage(item.answer, 'assistant');
            });
        }
    })
    .catch(error => {
        console.error('Error loading session history:', error);
    });
}

// WebSocket 연결
function connectWebSocket() {
    if (!currentSessionId) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${currentSessionId}`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = function() {
        console.log('WebSocket 연결됨');
    };
    
    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.type === 'bot_response') {
            // 질문 메시지는 여기서 추가하지 않음 (중복 방지)
            if (data.response !== null && data.response !== undefined && data.response !== "") {
                addMessage(data.response, 'assistant');
            }
            hideTypingIndicator();
        }
    };
    
    ws.onclose = function() {
        console.log('WebSocket 연결 종료');
        // 3초 후 재연결 시도
        setTimeout(() => {
            if (currentSessionId) {
                connectWebSocket();
            }
        }, 3000);
    };
    
    ws.onerror = function(error) {
        console.error('WebSocket 오류:', error);
    };
}

// 메시지 전송
function sendMessage() {
    const input = document.getElementById('messageInput');
    const messageText = input.value.trim();

    if (!messageText || isTyping) return;

    // 세션이 없는 경우: 세션 생성 후 다시 전송 시도
    if (!currentSessionId) {
        createNewSession(() => {
            // 세션 생성 후 메시지 텍스트를 다시 입력창에 넣고 재귀 호출
            input.value = messageText;
            sendMessage();
        });
        return;
    }

    // 사용자 메시지 즉시 UI에 추가
    addMessage(messageText, 'user');
    input.value = '';
    input.style.height = 'auto';

    // 타이핑 표시
    showTypingIndicator();

    // WebSocket으로 메시지 전송
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'user_message',
            message: messageText,
            session_id: currentSessionId
        }));
    } else {
        // WebSocket이 연결되지 않은 경우 HTTP API 사용
        fetch(`/chat/${currentSessionId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: messageText })
        })
        .then(response => response.json())
        .then(data => {
            // 질문 메시지는 여기서 추가하지 않음 (중복 방지)
            if (data.response !== null && data.response !== undefined && data.response !== "") {
                addMessage(data.response, 'assistant');
            }
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
function addMessage(content, role, timestamp = null) {
    const chatMessages = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}-message`;
    const avatar = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
    const time = timestamp ? new Date(timestamp).toLocaleString('ko-KR') : new Date().toLocaleString('ko-KR');

    // 텍스트 처리 함수들
    function processText(text) {
        console.log('=== 텍스트 처리 시작 ===');
        console.log('원본 텍스트:', text);
        
        // 1. HTML 특수문자 이스케이프 (하지만 나중에 추가할 태그는 제외)
        text = text.replace(/[&<>"']/g, function(tag) {
            const charsToReplace = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            };
            return charsToReplace[tag] || tag;
        });

        // 2. 마크다운 bold(**텍스트**)를 <strong>텍스트</strong>로 변환
        text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        console.log('강조 처리 후:', text);

        // 3. <strong> 태그 내부의 HTML 태그들을 원래대로 복원
        text = text.replace(/&lt;(\/?strong)&gt;/g, '<$1>');

        // 4. 출처 표시 패턴을 찾아서 스타일 적용
        console.log('출처 패턴 검색 시작...');
        
        // 더 정확한 출처 패턴 매칭 - 한국어 문자와 공백, 특수문자 포함
        const sourcePatterns = [
            /(\[출처\s*:\s*[^\]]+\])/g,  // [출처: ...] 또는 [출처 : ...]
            /(\(출처\s*:\s*[^)]+\))/g,   // (출처: ...) 또는 (출처 : ...)
            /(【출처\s*:\s*[^】]+】)/g,   // 【출처: ...】 또는 【출처 : ...】
            /(\[출처[^\]]*\])/g,         // [출처...] 형태 모두
            /(\(출처[^)]*\))/g,          // (출처...) 형태 모두
            /(출처\s*:\s*[^\s\]\)]+(?:\s+[^\s\]\)]+)*)/g,  // 출처: 문서명 p.페이지 형태
        ];
        
        let foundSources = false;
        sourcePatterns.forEach((pattern, index) => {
            const matches = text.match(pattern);
            if (matches) {
                console.log(`패턴 ${index + 1} 매칭 결과:`, matches);
                foundSources = true;
                text = text.replace(pattern, '<span class="source-citation">$1</span>');
            }
        });
        
        if (!foundSources) {
            console.log('⚠️ 출처 패턴을 찾을 수 없습니다!');
            // 디버깅을 위해 텍스트에서 '출처' 단어가 있는지 확인
            if (text.includes('출처')) {
                console.log('텍스트에 "출처" 단어는 포함되어 있음');
                console.log('출처 주변 텍스트:', text.match(/.{0,20}출처.{0,20}/g));
            }
        }
        
        console.log('출처 처리 후:', text);

        // 5. 줄바꿈 처리
        text = text.replace(/\n/g, '<br>');

        console.log('최종 처리된 텍스트:', text);
        console.log('=== 텍스트 처리 완료 ===');
        return text;
    }

    // 코드와 설명 분리: ```로 감싼 코드블록을 찾아 분리
    let html = '';
    let codeBlockRegex = /```(\w+)?([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;
    let hasCode = false;
    
    while ((match = codeBlockRegex.exec(content)) !== null) {
        hasCode = true;
        // 설명 부분
        if (match.index > lastIndex) {
            let desc = content.substring(lastIndex, match.index).trim();
            desc = processText(desc);
            html += `<div class='message-desc'>${desc}</div>`;
        }
        // 코드 부분
        const lang = match[1] ? match[1] : '';
        const code = match[2].trim();
        // 코드 부분은 HTML 이스케이프만 적용
        const escapedCode = code.replace(/[&<>"']/g, function(tag) {
            const charsToReplace = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            };
            return charsToReplace[tag] || tag;
        });
        html += `<div class='code-block-card'><button class='copy-btn' onclick='copyCode(this)'>복사</button><pre><code class='language-${lang}'>${escapedCode}</code></pre></div>`;
        lastIndex = codeBlockRegex.lastIndex;
    }
    
    if (!hasCode) {
        // 코드가 없는 경우 전체 텍스트 처리
        let desc = content;
        desc = processText(desc);
        html = `<div class='message-desc'>${desc}</div>`;
    } else if (lastIndex < content.length) {
        // 마지막 코드블록 이후 남은 텍스트 처리
        let desc = content.substring(lastIndex).trim();
        desc = processText(desc);
        html += `<div class='message-desc'>${desc}</div>`;
    }

    messageDiv.innerHTML = `
        <div class="message-avatar">
            ${avatar}
        </div>
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
    const code = btn.nextElementSibling.innerText;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = '복사됨!';
        setTimeout(() => { btn.textContent = '복사'; }, 1200);
    });
}

// HTML 이스케이프
function escapeHtml(text) {
    // 코드블록 내부는 줄바꿈을 그대로 두고, HTML 특수문자만 이스케이프
    return text.replace(/[&<>"']/g, function(tag) {
        const charsToReplace = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        };
        return charsToReplace[tag] || tag;
    });
}

// 채팅 메시지 지우기
function clearChatMessages() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.innerHTML = '';
    // 환영 메시지 추가하지 않음
}

// 대화 지우기
function clearChat() {
    if (confirm('현재 대화를 지우시겠습니까?')) {
        clearChatMessages();
        // 환영 메시지 추가하지 않음
    }
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
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
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
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// 텍스트 영역 자동 크기 조정
function setupTextareaAutoResize() {
    const textarea = document.getElementById('messageInput');
    textarea.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
}

// 타이핑 표시
function showTypingIndicator() {
    isTyping = true;
    document.getElementById('typingIndicator').style.display = 'flex';
    scrollToBottom();
}

// 타이핑 숨김
function hideTypingIndicator() {
    isTyping = false;
    document.getElementById('typingIndicator').style.display = 'none';
}

// 스크롤을 맨 아래로
function scrollToBottom() {
    const chatMessages = document.getElementById('chatMessages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 로딩 표시
function showLoading() {
    document.getElementById('loadingOverlay').classList.add('show');
}

// 로딩 숨김
function hideLoading() {
    document.getElementById('loadingOverlay').classList.remove('show');
}

// 키보드 단축키
document.addEventListener('keydown', function(event) {
    // Ctrl/Cmd + Enter로 새 대화 시작
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        createNewSession();
    }
    
    // Ctrl/Cmd + S로 대화 내보내기
    if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault();
        exportChat();
    }
    
    // Ctrl/Cmd + K로 대화 지우기
    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        clearChat();
    }
}); 