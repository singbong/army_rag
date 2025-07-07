// 메인 페이지 JavaScript

// 새 대화 시작
function startNewChat() {
    showLoading();
    
    fetch('/create-session', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.session_id) {
            // 세션 ID를 localStorage에 저장
            localStorage.setItem('currentSessionId', data.session_id);
            localStorage.setItem('currentSessionName', data.session_name);
            
            // 채팅 페이지로 이동
            window.location.href = '/chat';
        } else {
            hideLoading();
            alert('세션 생성에 실패했습니다.');
        }
    })
    .catch(error => {
        hideLoading();
        console.error('Error:', error);
        alert('세션 생성 중 오류가 발생했습니다.');
    });
}

// 기존 대화 보기
function viewSessions() {
    showLoading();
    
    fetch('/sessions')
    .then(response => response.json())
    .then(data => {
        hideLoading();
        
        if (data.sessions && data.sessions.length > 0) {
            // 세션 목록이 있으면 채팅 페이지로 이동
            window.location.href = '/chat';
        } else {
            // 세션이 없으면 새 대화 시작
            startNewChat();
        }
    })
    .catch(error => {
        hideLoading();
        console.error('Error:', error);
        alert('세션 목록을 불러오는 중 오류가 발생했습니다.');
    });
}

// 로딩 표시
function showLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.add('show');
    }
}

// 로딩 숨김
function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.remove('show');
    }
}

// 페이지 로드 시 실행
document.addEventListener('DOMContentLoaded', function() {
    console.log('RAG Chat Interface 로드됨');
    
    // 로딩 오버레이 생성 (없는 경우)
    if (!document.getElementById('loadingOverlay')) {
        const overlay = document.createElement('div');
        overlay.id = 'loadingOverlay';
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-spinner">
                <i class="fas fa-spinner fa-spin"></i>
                <p>로딩 중...</p>
            </div>
        `;
        document.body.appendChild(overlay);
    }
});

// 키보드 단축키
document.addEventListener('keydown', function(event) {
    // Ctrl/Cmd + Enter로 새 대화 시작
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        startNewChat();
    }
    
    // Ctrl/Cmd + L로 세션 목록 보기
    if ((event.ctrlKey || event.metaKey) && event.key === 'l') {
        event.preventDefault();
        viewSessions();
    }
}); 