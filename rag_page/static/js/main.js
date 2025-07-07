// 메인 페이지 JavaScript

function startNewChat() {
    showLoading();
    
    fetch('/create-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.session_id) {
            localStorage.setItem('currentSessionId', data.session_id);
            localStorage.setItem('currentSessionName', data.session_name);
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

function viewSessions() {
    showLoading();
    
    fetch('/sessions')
    .then(response => response.json())
    .then(data => {
        hideLoading();
        window.location.href = '/chat';
    })
    .catch(error => {
        hideLoading();
        console.error('Error:', error);
        alert('세션 목록을 불러오는 중 오류가 발생했습니다.');
    });
}

function showLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.classList.add('show');
}

function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.classList.remove('show');
}

document.addEventListener('keydown', function(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        startNewChat();
    }
    if ((event.ctrlKey || event.metaKey) && event.key === 'l') {
        event.preventDefault();
        viewSessions();
    }
});