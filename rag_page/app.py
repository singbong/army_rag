from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional
import httpx
from pathlib import Path
import sys
import warnings

# LangChain 관련
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.memory import ConversationBufferWindowMemory

warnings.filterwarnings('ignore')

# Docker 환경에서 모듈 경로 추가
current_dir = Path(__file__).parent.resolve()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Simple RAG import
from simple_rag_with_pages import init_fast_rag, fast_search

APP_DIR = Path(__file__).parent.resolve()

app = FastAPI(title="병무청 AI 상담 서비스", version="1.0.0")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 및 템플릿 설정
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# 세션 관리
sessions: Dict[str, Dict] = {}
lc_memories: Dict[str, ConversationBufferWindowMemory] = {}

# LLM 모델 설정
llm_model_8b = ChatOpenAI(
    model_name="/root/.cache/huggingface/llama-3-Korean-Bllossom-8B",
    base_url="http://vllm_8b:8000/v1",
    api_key="EMPTY",
    temperature=0.1,
    max_tokens=2048, 
    timeout=60,
    max_retries=2,
)

llm_model_32b = ChatOpenAI(
    model_name="/root/.cache/huggingface/Qwen2.5-32B-Instruct",
    base_url="http://vllm_32b:8000/v1",
    api_key="EMPTY",
    temperature=0.1,
    max_tokens=2048,
    timeout=60,
    max_retries=2,
)

# RAG 초기화
print("🏗️ RAG 시스템 초기화 중...")
data_path = str(APP_DIR / "data")
init_fast_rag(data_path=data_path, store_name="vector_store")
print("✅ RAG 시스템 초기화 완료!")

# 프롬프트 템플릿
RAG_PROMPT = """당신은 병무청 AI 상담원입니다. 모집병 관련 질문에 친절하고 정확하게 답변하세요.

제공된 문서를 바탕으로 답변하되, 다음 규칙을 따르세요:
1. 문서에 명확한 답변이 있으면 그 내용을 기반으로 답변하세요
2. 불확실한 정보는 "확실하지 않다"고 말하세요
3. 문서에 없는 내용은 "제공된 자료에는 해당 정보가 없습니다"라고 하세요
4. 답변은 친근하고 이해하기 쉽게 작성하세요

문서 내용:
{context}

질문: {question}

답변:"""

REWRITE_PROMPT = """사용자의 질문을 명확한 키워드 중심으로 재작성하세요.

규칙:
1. 대명사나 지시어를 구체적인 명사로 바꾸세요
2. 채팅 기록을 참고하여 문맥을 명확히 하세요
3. 질문이 이미 명확하면 그대로 반환하세요
4. 한국어로만 답변하세요

채팅 기록:
{chat_history}

질문: {question}

재작성된 질문:"""

# 프롬프트 체인
rag_chain = ChatPromptTemplate.from_template(RAG_PROMPT) | llm_model_32b | StrOutputParser()
rewrite_chain = ChatPromptTemplate.from_template(REWRITE_PROMPT) | llm_model_8b | StrOutputParser()

def format_docs(docs):
    """문서 목록을 포맷팅"""
    if not docs:
        return "관련 문서를 찾을 수 없습니다."
    
    formatted_docs = []
    for doc in docs:
        source = doc.metadata.get('source', '알 수 없음')
        pages = doc.metadata.get('pages', [])
        page_info = f"(p.{pages[0]}-{pages[-1]})" if len(pages) > 1 else f"(p.{pages[0]})" if pages else ""
        
        formatted_docs.append(f"[{source} {page_info}]\n{doc.page_content}")
    
    return "\n\n".join(formatted_docs)

def get_chat_history(session_id: str) -> str:
    """채팅 기록을 문자열로 반환"""
    if session_id not in lc_memories:
        return ""
    
    messages = lc_memories[session_id].chat_memory.messages
    pairs = []
    for i in range(0, len(messages), 2):
        if i < len(messages):
            user_msg = messages[i]
            if hasattr(user_msg, 'content'):
                pairs.append(f"사용자: {user_msg.content}")
        if i + 1 < len(messages):
            ai_msg = messages[i + 1]
            if hasattr(ai_msg, 'content'):
                pairs.append(f"AI: {ai_msg.content}")
    
    return "\n".join(pairs[-4:])  # 최근 4개 메시지만

async def process_rag_query(question: str, session_id: Optional[str] = None) -> str:
    """RAG 시스템을 통해 질문을 처리하고 답변을 반환"""
    try:
        print(f"🔍 RAG 처리 시작: {question}")
        
        # 채팅 기록 가져오기
        chat_history = get_chat_history(session_id) if session_id else ""
        
        # 질문 재작성 (필요시)
        if chat_history:
            try:
                rewritten_question = await rewrite_chain.ainvoke({
                    "question": question,
                    "chat_history": chat_history
                })
                print(f"📝 재작성된 질문: {rewritten_question}")
                search_query = rewritten_question.strip()
            except Exception as e:
                print(f"⚠️ 질문 재작성 실패: {e}")
                search_query = question
        else:
            search_query = question
        
        # 문서 검색
        docs = fast_search(search_query, k=5)
        if not docs:
            return "죄송합니다. 해당 질문과 관련된 자료를 찾을 수 없습니다."
        
        # 문서 포맷팅
        context = format_docs(docs)
        
        # 답변 생성
        response = await rag_chain.ainvoke({
            "context": context,
            "question": question
        })
        
        print(f"✅ RAG 처리 완료")
        return response
        
    except Exception as e:
        print(f"💥 RAG 처리 오류: {e}")
        return f"죄송합니다. 처리 중 오류가 발생했습니다: {str(e)}"

class ChatManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
    
    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
    
    async def send_message(self, message: str, session_id: str):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_text(message)

chat_manager = ChatManager()

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/chat")
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/create-session")
async def create_session():
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "created_at": datetime.now().isoformat(),
        "last_activity": datetime.now().isoformat(),
        "name": f"모집병 상담 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    }
    lc_memories[session_id] = ConversationBufferWindowMemory(k=3, return_messages=True)
    return {"session_id": session_id, "session_name": sessions[session_id]["name"]}

@app.get("/sessions")
async def get_all_sessions():
    return {
        "sessions": [
            {
                "session_id": session_id,
                "name": session_info["name"],
                "created_at": session_info["created_at"],
                "last_activity": session_info["last_activity"],
                "message_count": len(lc_memories[session_id].chat_memory.messages) if session_id in lc_memories else 0
            }
            for session_id, session_info in sessions.items()
        ]
    }

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    qa_pairs = []
    if session_id in lc_memories:
        messages = lc_memories[session_id].chat_memory.messages
        for i in range(0, len(messages), 2):
            q = messages[i].content if i < len(messages) and hasattr(messages[i], 'content') else None
            a = messages[i+1].content if i+1 < len(messages) and hasattr(messages[i+1], 'content') else None
            if q or a:
                qa_pairs.append({"question": q, "answer": a})
    
    return {
        "session_id": session_id,
        "session_info": sessions[session_id],
        "chat_history": qa_pairs
    }

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    del sessions[session_id]
    if session_id in lc_memories:
        del lc_memories[session_id]
    
    return {"message": "Session deleted successfully"}

@app.post("/chat/{session_id}")
async def chat(session_id: str, message: dict):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    user_message = message.get("message", "")
    if not user_message.strip():
        return {
            "response": "질문을 입력해주세요.",
            "question": None,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
    
    sessions[session_id]["last_activity"] = datetime.now().isoformat()
    
    # 메모리 관리
    if session_id not in lc_memories:
        lc_memories[session_id] = ConversationBufferWindowMemory(k=3, return_messages=True)
    
    lc_memories[session_id].chat_memory.add_user_message(user_message)
    
    try:
        response_text = await process_rag_query(user_message, session_id)
        lc_memories[session_id].chat_memory.add_ai_message(response_text)
        
        return {
            "response": response_text,
            "question": user_message,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "response": f"죄송합니다. 처리 중 오류가 발생했습니다: {str(e)}",
            "question": user_message,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await chat_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_message = message_data.get("message", "")
            
            if user_message.strip():
                # 메모리 관리
                if session_id not in lc_memories:
                    lc_memories[session_id] = ConversationBufferWindowMemory(k=3, return_messages=True)
                
                lc_memories[session_id].chat_memory.add_user_message(user_message)
                
                try:
                    response_text = await process_rag_query(user_message, session_id)
                    lc_memories[session_id].chat_memory.add_ai_message(response_text)
                    
                    await websocket.send_text(json.dumps({
                        "response": response_text,
                        "question": user_message,
                        "session_id": session_id,
                        "timestamp": datetime.now().isoformat()
                    }))
                except Exception as e:
                    await websocket.send_text(json.dumps({
                        "response": f"죄송합니다. 처리 중 오류가 발생했습니다: {str(e)}",
                        "question": user_message,
                        "session_id": session_id,
                        "timestamp": datetime.now().isoformat()
                    }))
    except WebSocketDisconnect:
        chat_manager.disconnect(session_id)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/vllm/models")
async def get_vllm_models():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://vllm_8b:8000/v1/models")
            return response.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/vllm/test")
async def test_vllm_connection():
    try:
        test_response = await llm_model_8b.ainvoke("안녕하세요")
        return {"status": "success", "response": test_response}
    except Exception as e:
        return {"status": "error", "error": str(e)}