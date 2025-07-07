from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import json
import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional
import httpx
from pathlib import Path
import hashlib
import sys
import warnings

# LangChain 관련
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from typing_extensions import TypedDict, Annotated
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import END, StateGraph, START
from langgraph.checkpoint.memory import MemorySaver
from langchain_teddynote.messages import random_uuid
from langchain_core.runnables import RunnableConfig
from langchain.memory import ConversationBufferWindowMemory

warnings.filterwarnings('ignore')

# Docker 환경에서 모듈 경로 추가
current_dir = Path(__file__).parent.resolve()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Simple RAG import
from simple_rag_with_pages import init_fast_rag, fast_search

# --- 경로 설정 ---
APP_DIR = Path(__file__).parent.resolve()
# --- 경로 설정 끝 ---

app = FastAPI(title="병무청 Chat API", version="1.0.0")

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
lc_memories: Dict[str, ConversationBufferWindowMemory] = {}  # LangChain 메모리 관리 (세션별)

# LLM 모델 설정 (context 길이 제한 강화)
llm_model_8b = ChatOpenAI(
    model_name="/root/.cache/huggingface/llama-3-Korean-Bllossom-8B",
    base_url="http://vllm_8b:8000/v1",
    api_key="EMPTY",
    temperature=0,
    max_tokens=24000, 
    timeout=120,  # 타임아웃 2분으로 증가
    max_retries=3,  # 최대 3회 재시도
)

llm_model_32b = ChatOpenAI(
    model_name="/root/.cache/huggingface/Qwen2.5-32B-Instruct",
    base_url="http://vllm_32b:8000/v1",
    api_key="EMPTY",
    temperature=0,
    max_tokens=24000,  # context 최대한 활용
    timeout=120,
    max_retries=3,
)

llm_model_generate = ChatOpenAI(
    model_name="/root/.cache/huggingface/Qwen2.5-32B-Instruct",
    base_url="http://vllm_32b:8000/v1",
    api_key="EMPTY",
    temperature=1,
    timeout=120,
    max_retries=3,
)



# RAG 초기화
print("🏗️ RAG 시스템 초기화 중...")
# Docker 환경에서 데이터 경로 설정
data_path = str(APP_DIR / "data")
init_fast_rag(data_path=data_path, store_name="vector_store")
print("✅ RAG 시스템 초기화 완료!")

re_write_system = """
당신의 역할은 사용자의 질문을 키워드 중심으로 재작성하는 것입니다.
절대 답변을 생성하거나, 문서 내용을 요약·설명하거나, 질문 외의 어떤 정보도 추가하지 마세요.

- 대명사/지시어(이것, 그것, 그 보직 등)는 chat history에서 가장 최근에 언급된 명사(특기/보직명 등)로 치환하세요.
- chat history에서 언급된 특기/보직명이 있으면, 현재 질문에 해당 특기/보직명을 명시적으로 포함시키세요.
- 질문이 이미 명확하면 절대 수정하지 말고 그대로 반환하세요.
- 새로운 정보, 불필요한 설명, 반복, 수식어, 예시, 답변, 안내문구는 절대 추가하지 마세요.
- 중국어, 영어, 일본어 등 다른 언어는 절대 사용하지 마세요.
- 반드시 한국어로만 답변하세요.
- 오직 재작성된 질문만, 한 문장으로 반환하세요.

예시)
    * 그 보직의 지원자격은? (chat history: 전차 운전병에 대한 내용) -> 전차 운전병 지원자격
    * 운전면허증은 필요 없어? (chat history: 운전병에 대한 내용) -> 운전병 운전면허증 필요성
    * 지원자격은? (chat history: 카투사에 대한 내용) -> 카투사 지원자격
"""


question_decomposer_system = """
당신의 역할은 사용자의 질문을 기반으로 추가 질문을 생성하여 LLM이 풍부한 답변을 할 수 있도록 돕는 전문가입니다.

아래의 규칙을 반드시 지키세요:
1. 입력받은 질문을 분석하여 핵심 주제를 파악하세요.
2. 원래 질문과 관련된 추가 질문 2개를 생성하세요.
3. 추가 질문은 원래 질문의 맥락을 확장하거나 보완하는 것이어야 합니다.
4. 각 질문은 독립적으로 검색 가능해야 합니다.
5. 반드시 3개의 질문(원래 질문 + 추가 질문 2개)을 JSON 배열 형태로 반환하세요.
6. 반드시 한국어로만 답변하세요. 중국어, 영어, 일본어 등 다른 언어는 절대 사용하지 마세요.
7. JSON 배열 이외의 그 어떤 설명, 안내문구, 불필요한 텍스트도 절대 추가하지 마세요.

예시:
    입력: "전차 운전병 자격요건"
    출력: ["전차 운전병 자격요건", "전차 운전병 지원절차", "전차 운전병 준비사항"]

    입력: "카투사 혜택"
    출력: ["카투사 혜택", "카투사 지원조건", "카투사 준비방법"]

    입력: "운전병 지원자격"
    출력: ["운전병 지원자격", "운전병 자격증", "운전병 지원절차"]

오직 JSON 배열만 반환하세요. 반드시 한국어로만 작성하세요.
"""



generate_system = """
당신은 모집병 지원 상담 AI입니다. 제공된 문서에 있는 정보만을 바탕으로 답변하세요.

**핵심 원칙**:
    1. 제공된 문서에 있는 정보만 답변에 포함
    2. 문서에 없는 내용은 절대 답변에 포함하지 않음
    3. 질문의 핵심 의도를 파악하고 문서에서 찾은 구체적 정보만 제공
    4. 지원자 관점에서 실질적으로 도움이 되는 정보 우선 제공
    5. chat history를 참고하여 맥락을 반영해 답변
    6. 반드시 한국어로만 답변하세요. 중국어, 영어, 일본어 등 다른 언어는 절대 사용하지 마세요

**답변 구조**:
    - 문서 기반 답변: 문서에서 찾은 질문에 대한 핵심 정보만 제공
    - 구체적 조건: 문서에 명시된 지원 자격, 요건, 제한사항, 필요 자격증 등
    - 실용적 정보: 문서에 있는 지원 절차, 준비사항, 주의점, 팁 등
    - 자격증/성적 정보: 문서에 명시된 필요 자격증, 학력 요건, 성적 기준 등을 반드시 포함

**텍스트 강조 규칙**:
    - 중요한 키워드나 핵심 정보는 **텍스트** 형태로 강조하세요
    - 특기명, 자격요건, 중요한 숫자나 조건 등을 강조하세요
    - 예: **운전병**, **만 18세 이상**, **2종 보통 이상**, **신체검사 4급 이상** 등

**자격증/성적 정보 강조 규칙**:
    - 필요 자격증이 있으면 반드시 **강조**하여 명시하세요
    - 학력 요건이나 성적 기준이 있으면 반드시 **강조**하여 명시하세요
    - 예: **운전면허 2종 보통 이상**, **고등학교 졸업 이상**, **평균 성적 3.0 이상** 등

**출처 표시 규칙**:
    - 가능한 경우 문서에서 정보를 인용한 문장 뒤에 출처를 표시하세요
    - 각 문서의 <source_citation> 태그에 있는 정확한 출처 정보를 사용하세요
    - 출처 형식: [출처: 문서명 p.페이지] 형태로 사용하세요
    - 한 문장이 여러 문서에서 나온 정보를 포함하면 모든 출처를 표시하세요

**출처 표시 예시**:
    **운전병** 지원자격은 **만 18세 이상**입니다. [출처: 모집요강 p.15]
    **운전면허 2종 보통 이상**을 소지해야 합니다. [출처: 모집요강 p.15]
    **신체검사 4급 이상**이어야 합니다. [출처: 신체검사기준 p.8]

**주의사항**:
    - 문서에서 찾을 수 없는 정보는 절대 답변에 포함하지 마세요
    - 문서에 없는 내용에 대해서는 "문서에서 해당 정보를 찾을 수 없습니다"라고 명시하세요
    - 질문과 관련 없는 다른 특기/보직 정보는 포함하지 마세요
    - 위험하거나 부정확한 정보는 절대 제공하지 마세요
    - 불확실한 정보는 "확인이 필요합니다"라고 명시하세요
    - 중요한 정보는 반드시 **강조**하세요
    - 필요 자격증이나 성적 기준이 있으면 반드시 **강조**하여 명시하세요
    - 반드시 한국어로만 답변하세요. 중국어, 영어, 일본어 등 다른 언어는 절대 사용하지 마세요

문서 내용을 바탕으로 정확하고 실용적인 답변을 제공하세요. 문서에 없는 내용은 절대 포함하지 마세요. 필요 자격증이나 성적 기준이 있으면 반드시 강조하여 명시하세요. 반드시 한국어로만 답변하세요.
"""

# 멀티쿼리 생성 시스템
multi_query_system = """
당신은 하나의 질문을 다양한 각도에서 검색할 수 있는 여러 쿼리로 변환하는 전문가입니다.

**중요**: 원래 질문의 핵심 키워드와 의도를 반드시 유지하세요. 전혀 다른 분야로 확장하지 마세요.

원칙:
1. 원래 질문의 핵심 키워드를 모든 쿼리에 포함
2. 구체적인 용어와 일반적인 용어를 혼용하되 원래 의도 유지
3. 동의어, 유사어만 사용 (관련없는 용어 금지)
4. 2개의 집중된 쿼리 생성. 2개를 넘지 않도록 꼭 제한하세요.
5. 특기/보직 관련 질문의 경우 해당 특기명을 정확히 포함

예시:
    입력: "운전병 근무지"
    출력: [
        "운전병 근무지",
        "운전병 주둔지",
    ]

    입력: "운전병 지원자격"
    출력: [
        "운전병 지원자격",
        "운전병 자격증"
    ]

    입력: "카투사 혜택"
    출력: [
        "카투사 혜택",
        "카투사 보상"
    ]

JSON 배열 형태로만 반환하세요.
"""

# 의미적 리랭킹 시스템
semantic_reranking_system = """
문서와 질문의 관련성을 1-10점으로 평가하세요.

**평가 기준**:
10점: 질문에 직접적 답변, 핵심 키워드 정확히 일치
8-9점: 상당한 답변, 주요 키워드 일치
6-7점: 관련성 있음, 일부 키워드 일치
4-5점: 약간의 관련성 (키워드 1-2개 일치)
2-3점: 거의 관련성 없음
1점: 전혀 관련성 없음

**판단 기준**:
- 질문의 핵심 키워드가 문서에 포함되어 있는가?
- 문서에서 질문에 대한 구체적 정보를 제공하는가?
- 의미적 관련성이 있는가?

**특기/보직 관련**:
- 특정 특기/보직명이 문서에 정확히 포함되어 있는가?
- 해당 특기/보직의 구체적 정보가 있는가?

**중요**: 답변은 반드시 1-10 사이의 숫자만 출력하세요. 다른 텍스트는 포함하지 마세요.
"""


# 새로운 출처 추적 시스템 추가
class SourceTracker:
    """정확한 출처 추적을 위한 클래스"""
    
    def __init__(self):
        self.doc_source_map = {}  # 문서 ID -> 출처 정보 매핑
        self.content_hash_map = {}  # 내용 해시 -> 출처 정보 매핑
    
    def register_document(self, doc_id: str, doc):
        """문서 등록 및 출처 정보 매핑"""
        source_info = self.extract_precise_source_info(doc)
        content_hash = hashlib.md5(doc.page_content.encode()).hexdigest()
        
        self.doc_source_map[doc_id] = source_info
        self.content_hash_map[content_hash] = source_info
        
        return source_info
    
    def extract_precise_source_info(self, doc):
        """문서에서 정확한 출처 정보를 추출"""
        metadata = doc.metadata
        
        # 파일명 처리
        source = metadata.get('source', '알 수 없음')
        if isinstance(source, str):
            # 경로에서 파일명만 추출하고 확장자 제거
            file_name = os.path.basename(source)
            if '.' in file_name:
                file_name = file_name.rsplit('.', 1)[0]
        else:
            file_name = str(source)
        
        # 페이지 정보 정확히 추출
        pages = metadata.get('pages', [])
        primary_page = metadata.get('primary_page', None)
        page_span = metadata.get('page_span', None)
        
        # 페이지 정보 우선순위: pages > primary_page > page_span
        if isinstance(pages, list) and pages:
            if len(pages) == 1:
                page_info = f"p.{pages[0]}"
            else:
                page_info = f"p.{min(pages)}-{max(pages)}"
        elif primary_page and primary_page != '?' and primary_page != 0:
            page_info = f"p.{primary_page}"
        elif page_span and page_span != '?' and page_span != '0':
            page_info = f"p.{page_span}"
        else:
            page_info = ""
        
        # 청크 정보
        chunk_index = metadata.get('chunk_index', '')
        total_chunks = metadata.get('total_chunks', '')
        
        return {
            'file_name': file_name,
            'page_info': page_info,
            'pages': pages,
            'primary_page': primary_page,
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'original_source': source
        }
    
    def get_source_citation(self, doc):
        """문서에 대한 정확한 출처 인용문 생성"""
        content_hash = hashlib.md5(doc.page_content.encode()).hexdigest()
        
        # 해시로 먼저 찾기
        if content_hash in self.content_hash_map:
            source_info = self.content_hash_map[content_hash]
        else:
            # 실시간 추출
            source_info = self.extract_precise_source_info(doc)
        
        file_name = source_info['file_name']
        page_info = source_info['page_info']
        
        if page_info:
            return f"[출처: {file_name} {page_info}]"
        else:
            return f"[출처: {file_name}]"
    
    def get_detailed_source_info(self, doc):
        """상세한 출처 정보 반환"""
        content_hash = hashlib.md5(doc.page_content.encode()).hexdigest()
        
        if content_hash in self.content_hash_map:
            return self.content_hash_map[content_hash]
        else:
            return self.extract_precise_source_info(doc)

# 전역 출처 추적기 인스턴스
source_tracker = SourceTracker()

# 프롬프트 템플릿 생성
re_write_prompt = ChatPromptTemplate.from_messages([
    ("system", re_write_system),
    ("human", "chat history:\n{chat_history}")
])


question_decomposer_prompt = ChatPromptTemplate.from_messages([
    ("system", question_decomposer_system),
    ("human", "질문: {question}"),
])


generate_prompt = ChatPromptTemplate.from_messages([
    ("system", generate_system),
    ("human", "chat history: \n {chat_history} \n\n 문서: \n {document} \n\n 질문: \n {question}")
])

# 새로운 프롬프트 템플릿들
multi_query_prompt = ChatPromptTemplate.from_messages([
    ("system", multi_query_system),
    ("human", "질문: {question}"),
])

semantic_reranking_prompt = ChatPromptTemplate.from_messages([
    ("system", semantic_reranking_system),
    ("human", "문서: {document}\n\n질문: {question}"),
])

# 새로운 함수들 정의

def generate_content_hash(content: str) -> str:
    """문서 내용의 해시값을 생성하여 중복 체크에 사용"""
    return hashlib.md5(content.encode()).hexdigest()

def enhanced_multi_search(question: str) -> List:
    """BM25/FAISS+LLM 리랭킹만 사용하는 개선된 검색 함수"""
    try:
        # 1. 멀티쿼리 생성
        multi_query_generator = multi_query_prompt | llm_model_32b | StrOutputParser()
        queries_result = multi_query_generator.invoke({"question": question})
        try:
            # JSON 파싱 시도
            queries = json.loads(queries_result)
            if not isinstance(queries, list):
                queries = [question]
        except Exception:
            # 파싱 실패 시 원래 질문 사용
            queries = [question]
        print(f"🔍 생성된 멀티쿼리: {queries}")
        
        # 2. 각 쿼리로 검색 수행 (키워드 필터링 없이, context 관리 강화)
        all_documents = []
        seen_hashes = set()
        
        for query in queries:
            try:
                docs_per_query = 5
                docs = fast_search(query, k=docs_per_query)
                
                for doc in docs:
                    content_hash = generate_content_hash(doc.page_content)
                    if content_hash not in seen_hashes:
                        seen_hashes.add(content_hash)
                        all_documents.append(doc)
                        
            except Exception as e:
                print(f"쿼리 '{query}' 검색 실패: {e}")
                continue


        
        # 3. LLM 의미적 리랭킹 (검색된 모든 문서에 대해)
        scored_documents = []
        reranker = semantic_reranking_prompt | llm_model_8b | StrOutputParser()
        for i, doc in enumerate(all_documents):  # 모든 문서에 대해 리랭킹 수행
            try:
                content = doc.page_content.strip()
                # 정말로 빈 문서만 제외(10자 미만)
                if len(content) < 10:
                    scored_documents.append((doc, 1))
                    continue
                # 그 외에는 모두 LLM 리랭킹에 맡김 (키워드 필터링 없음)
                score_text = reranker.invoke({
                    "document": content,  # 문서 전체 내용 사용
                    "question": question
                })
                # 점수 추출 (1-10)
                score = 1
                for char in score_text:
                    if char.isdigit():
                        potential_score = int(char)
                        if 1 <= potential_score <= 10:
                            score = potential_score
                            break
                scored_documents.append((doc, score))
            except Exception as e:
                print(f"리랭킹 실패: {e}")
                scored_documents.append((doc, 3))  # 낮은 기본 점수
        
        # 4. 점수 기준 정렬 및 상위 10개 문서 선택
        scored_documents.sort(key=lambda x: x[1], reverse=True)  # 점수 순으로 정렬
        top_documents = [doc for doc, score in scored_documents if score >= 8]
        
        return top_documents
    except Exception as e:
        print(f"❌ 멀티쿼리 검색 실패: {e}")
        # 폴백: 기본 검색
        return fast_search(question, k=10)

# 그래프 상태 정의
class GraphState(TypedDict):
    question: Annotated[str, "User question"]
    chat_history: Annotated[str, "Chat history for context"]
    sub_questions: Annotated[List[str], "List of sub-questions in logical order"]
    current_question_index: Annotated[int, "Current sub-question being processed"]
    document: Annotated[List[str], "Combined documents"]
    generation: Annotated[str, "LLM generated answer"]

# 노드 함수들 정의

def re_writer(state):
    """질문 재작성 - chat_history를 올바르게 포맷해서 LLM 프롬프트에 넘김 (명사 추출 없이)"""
    question = state["question"]
    chat_history = state.get("chat_history", "")
    # chat_history가 리스트(messages)면 포맷팅
    if isinstance(chat_history, list):
        # ConversationBufferWindowMemory에서 직접 메시지 가져오기
        chat_history_str = ""
        if chat_history and len(chat_history) > 0:
            messages = chat_history
            pairs = []
            for i in range(0, len(messages), 2):
                if i < len(messages):
                    user_msg = messages[i]
                    if hasattr(user_msg, 'content'):
                        pairs.append(f"Question: {user_msg.content}")
                if i + 1 < len(messages):
                    ai_msg = messages[i + 1]
                    if hasattr(ai_msg, 'content'):
                        pairs.append(f"Answer: {ai_msg.content}")
            chat_history_str = "\n".join(pairs) if pairs else ""
    else:
        chat_history_str = chat_history

    # 첫 번째 질문이거나 chat history가 없으면 재작성 건너뛰기
    if not chat_history_str or chat_history_str.strip() == "" or len(chat_history_str.strip()) < 10:
        print(f"🔍 질문 재작성 건너뜀: 첫 번째 질문이거나 chat history 없음 - '{question}'")
        return {"question": question}
    try:
        re_writer_chain = re_write_prompt | llm_model_32b | StrOutputParser()
        rewritten = re_writer_chain.invoke({
            "question": question,
            "chat_history": chat_history_str
        })
        if len(rewritten) > len(question) * 2:
            print(f"⚠️  재작성 결과가 너무 길어서 원래 질문 유지: '{question}'")
            return {"question": question}
        print(f"✅ 질문 재작성(LLM): '{question}' → '{rewritten}'")
        return {"question": rewritten}
    except Exception as e:
        print(f"❌ 재작성 실패, 원본 유지: {e}")
        return {"question": question}

def question_decomposer(state):
    """입력 질문을 기반으로 추가 질문을 생성하여 풍부한 답변을 위한 문서 검색 - state 전체 유지하면서 필요한 값만 갱신"""
    max_retries = 3
    
    for attempt in range(max_retries):
        print(f"🔍 추가 질문 생성 시도 {attempt + 1}/{max_retries}: {state['question']}")
        
        try:
            # LLM 호출 시 제한 적용
            decomposer = question_decomposer_prompt | llm_model_8b | StrOutputParser()
            result = decomposer.invoke({
                "question": state["question"]
            })
            
            # JSON 파싱 시도
            try:
                sub_questions = json.loads(result)
                if not isinstance(sub_questions, list):
                    sub_questions = [state["question"]]
            except Exception:
                # JSON 파싱 실패 시 원래 질문 사용
                sub_questions = [state["question"]]
            
            print(f"✅ 추가 질문 생성 성공: {len(sub_questions)}개 질문")
            
            # 질문이 3개를 넘으면 앞 3개만 사용 (context 관리)
            if len(sub_questions) > 3:
                sub_questions = sub_questions[:3]
            
            # state 전체를 유지하면서 필요한 값만 갱신
            return {
                **state,  # 기존 state 유지
                "sub_questions": sub_questions,
                "current_question_index": 0,
                "document": [],  # 매번 새로운 질문마다 document 초기화
                "generation": ""
            }
            
        except Exception as e:
            print(f"❌ 추가 질문 생성 실패 (시도 {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                return {
                    **state,  # 기존 state 유지
                    "sub_questions": [state["question"]],
                    "current_question_index": 0,
                    "document": [],  # 매번 새로운 질문마다 document 초기화
                    "generation": ""
                }
    
    # 예외 상황 대비
    return {
        **state,  # 기존 state 유지
        "sub_questions": [state["question"]],
        "current_question_index": 0,
        "document": [],  # 매번 새로운 질문마다 document 초기화
        "generation": ""
    }
            

def recursive_search(state):
    """재귀 검색 - state 전체 유지하면서 필요한 값만 갱신"""
    sub_questions = state.get("sub_questions", [state["question"]])
    current_index = state.get("current_question_index", 0)
    all_documents = state.get("document", [])

    if current_index >= len(sub_questions):
        return {
            **state,  # 기존 state 유지
            "document": all_documents,
            "current_question_index": current_index
        }

    current_question = sub_questions[current_index]

    try:
        print(f"🔍 하위 질문 {current_index + 1}: {current_question}")
        documents = enhanced_multi_search(current_question)  
    except Exception as e:
        print(f"❌ 검색 중 오류: {e}")
        documents = []

    # 누적 방식으로 document 합치기
    all_documents = all_documents + documents

    return {
        **state,  # 기존 state 유지
        "document": all_documents,
        "current_question_index": current_index + 1,
        "sub_questions": sub_questions
    }

def check_recursion_complete(state):
    """재귀 처리가 완료되었는지 확인"""
    sub_questions = state.get("sub_questions", [])
    current_index = state.get("current_question_index", 0)
    
    if current_index >= len(sub_questions):
        return "complete"
    else:
        return "continue"

# 2. Qwen 32B용 포맷 함수 추가

def format_docs_for_qwen(docs, max_docs=15):
    """개선된 Qwen 32B용: 정확한 출처 정보가 포함된 문서 포맷"""
    formatted = []
    for i, doc in enumerate(docs[:max_docs]):
        content = doc.page_content
        
        # 출처 추적기를 사용한 정확한 출처 정보
        source_citation = source_tracker.get_source_citation(doc)
        
        # 디버깅용 상세 정보 (개발 중에만 사용)
        debug_info = source_tracker.get_detailed_source_info(doc)
        
        formatted.append(
            f'<document id="{i+1}">'
            f'<content>{content}</content>'
            f'<source_citation>{source_citation}</source_citation>'
            f'<debug_info>파일: {debug_info["file_name"]}, 페이지: {debug_info["page_info"]}, 청크: {debug_info["chunk_index"]}</debug_info>'
            f'</document>'
        )
    return "\n\n".join(formatted)

def format_chat_history_for_qwen(history) -> str:
    """Qwen 32B용: 모든 메시지 + 가장 최근 AI 답변 전체를 포맷"""
    if not history:
        return "없음"
    recent_history = history
    prev_ai_full = ""
    for msg in reversed(history[:-1]):
        role = getattr(msg, "role", None) or getattr(msg, "type", None)
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
        if role in ("assistant", "ai"):
            prev_ai_full = content or ""
            break
    formatted = []
    for msg in recent_history:
        role = getattr(msg, "role", None) or getattr(msg, "type", None)
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
        role_str = "human" if role in ("user", "human") else "AI"
        content_str = content or ""
        formatted.append(f"{role_str}: {content_str}")
    result = "\n".join(formatted)
    if prev_ai_full:
        result += f"\n[이전 AI 답변]: {prev_ai_full}"
    return result


def generate_answer(state):
    """개선된 답변 생성 - 정확한 출처 정보 포함"""
    try:
        generator = generate_prompt | llm_model_generate | StrOutputParser()
        docs = state["document"]
        chat_history = state.get("chat_history", "")
        
        # 문서가 있는 경우에만 답변 생성
        if docs:
            # 각 문서를 출처 추적기에 등록
            for i, doc in enumerate(docs):
                source_tracker.register_document(f"doc_{i}", doc)
            
            answer = generator.invoke({
                "document": format_docs_for_qwen(docs),
                "question": state["question"],
                "chat_history": format_chat_history_for_qwen(chat_history) if isinstance(chat_history, list) else chat_history
            })
            
            # 답변이 비어있는 경우 fallback
            if not answer or not answer.strip():
                # 정확한 출처 정보가 포함된 문서 요약 제공
                doc_summaries = []
                for doc in docs[:5]:  # 상위 5개 문서만 사용
                    content = doc.page_content[:500]  # 500자로 제한
                    source_citation = source_tracker.get_source_citation(doc)
                    doc_summaries.append(f"{content}\n{source_citation}")
                
                answer = "문서에서 찾은 정보:\n\n" + "\n\n".join(doc_summaries)
        else:
            answer = "제공된 문서에는 해당 질문에 대한 정보가 없습니다."

        return {"generation": answer}
    except Exception as e:
        print(f"❌ 답변 생성 실패: {e}")
        docs = state.get("document", [])
        if docs:
            # 에러 발생 시에도 정확한 출처 정보 포함
            doc_summaries = []
            for doc in docs[:3]:  # 상위 3개 문서만 사용
                content = doc.page_content[:300]  # 300자로 제한
                source_citation = source_tracker.get_source_citation(doc)
                doc_summaries.append(f"{content}\n{source_citation}")
            
            answer = "처리 중 오류가 발생했지만, 다음 정보를 찾았습니다:\n\n" + "\n\n".join(doc_summaries)
        else:
            answer = "죄송합니다. 처리 중 오류가 발생했습니다."
        return {"generation": answer}

# LangGraph 워크플로우 생성
workflow = StateGraph(GraphState)

# 노드들 추가
workflow.add_node("re_writer", re_writer)
workflow.add_node("question_decomposer", question_decomposer)
workflow.add_node("recursive_search", recursive_search)
workflow.add_node("generate_answer", generate_answer)

# 워크플로우 구성
workflow.add_edge(START, "re_writer")
workflow.add_edge("re_writer", "question_decomposer")
workflow.add_edge("question_decomposer", "recursive_search")
workflow.add_conditional_edges(
    "recursive_search",
    check_recursion_complete,
    {
        "continue": "recursive_search",  # 다음 하위 질문 처리
        "complete": "generate_answer"    # 모든 질문 처리 완료 시 답변 생성
    }
)

# 답변 생성 후 종료
workflow.add_edge("generate_answer", END)

# 워크플로우 컴파일
flow = workflow.compile(checkpointer=MemorySaver())

# RAG 처리 함수
async def process_rag_query(question: str, session_id: Optional[str] = None) -> str:
    """RAG 시스템을 통해 질문을 처리하고 답변을 반환 - context 관리 및 fallback 로직 강화"""
    try:
        print(f"🔍 RAG 처리 시작: {question}")
        
        # chat history 가져오기 (lc_memories 사용)
        chat_history_str = ""
        if session_id and session_id in lc_memories:
            messages = lc_memories[session_id].chat_memory.messages
            # ConversationBufferWindowMemory에서 직접 메시지 가져오기
            if messages and len(messages) > 0:
                pairs = []
                for i in range(0, len(messages), 2):
                    if i < len(messages):
                        user_msg = messages[i]
                        if hasattr(user_msg, 'content'):
                            pairs.append(f"Question: {user_msg.content}")
                    if i + 1 < len(messages):
                        ai_msg = messages[i + 1]
                        if hasattr(ai_msg, 'content'):
                            pairs.append(f"Answer: {ai_msg.content}")
                chat_history_str = "\n".join(pairs) if pairs else ""
        # 첫 번째 질문이거나 채팅 기록이 없으면 빈 문자열로 설정
        
        # LLM 호출 제한 적용
        config = RunnableConfig(
            recursion_limit=20, 
            configurable={"thread_id": random_uuid()},
            timeout=120,  # 2분 타임아웃
            max_retries=3  # 최대 3회 재시도
        )
        
        inputs = {
            "question": question,
            "chat_history": chat_history_str,
            "sub_questions": [],
            "current_question_index": 0,
            "document": [],  # 매번 새로운 질문마다 document 초기화
            "generation": ""
        }
        
        print(f"⚙️ 입력 데이터 준비 완료")
        print(f"🚀 워크플로우 실행 시작...")
        result = flow.invoke(inputs, config)
        print(f"✅ 워크플로우 실행 완료")
        print(f"📊 결과: {list(result.keys())}")
        
        # 답변 생성 확인 및 fallback
        if "generation" in result and result["generation"] and result["generation"].strip():
            return result["generation"]
        else:
            docs = result.get("document", [])
            if docs:
                content = "\n\n".join([doc.page_content[:300] for doc in docs])  # context 절약을 위해 300자로 제한
                print(f"⚠️ LLM 답변 없음, 문서 요약 반환")
                return f"[문서 요약]\n{content}"
            else:
                print(f"❌ 답변 생성 실패: 문서도 없음")
                return "제공된 문서에는 해당 질문에 대한 정보가 없습니다."
                
    except Exception as e:
        print(f"💥 RAG 처리 오류: {e}")
        import traceback
        traceback.print_exc()
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
    # LangChain 메모리 생성
    lc_memories[session_id] = ConversationBufferWindowMemory(k=2, return_messages=True)
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
        i = 0
        while i < len(messages):
            q = None
            a = None
            # user 메시지
            if i < len(messages):
                m = messages[i]
                if hasattr(m, 'content'):
                    q = m.content
            # assistant 메시지
            if i+1 < len(messages):
                m = messages[i+1]
                if hasattr(m, 'content'):
                    a = m.content
            if q or a:
                qa_pairs.append({"question": q, "answer": a})
            i += 2
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
            "response": None,
            "question": None,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
    
    sessions[session_id]["last_activity"] = datetime.now().isoformat()
    
    # LangChain 메모리 관리
    if session_id not in lc_memories:
        lc_memories[session_id] = ConversationBufferWindowMemory(k=2, return_messages=True)
    lc_memories[session_id].chat_memory.add_user_message(user_message)
    
    try:
        response_text = await process_rag_query(user_message, session_id)
        # LangChain 메모리에 AI 답변 추가
        lc_memories[session_id].chat_memory.add_ai_message(response_text)
        return {
            "response": response_text,
            "question": user_message,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        error_response = f"RAG 시스템 오류: {str(e)}"
        # LangChain 메모리에 에러 답변 추가
        lc_memories[session_id].chat_memory.add_ai_message(error_response)
        return {
            "response": error_response,
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
            message = json.loads(data)
            
            response = await chat(session_id, message)
            
            websocket_response = {
                "type": "bot_response",
                "message": response.get("response", ""),
                "session_id": session_id,
                "timestamp": response.get("timestamp")
            }
            
            await chat_manager.send_message(json.dumps(websocket_response), session_id)
    except WebSocketDisconnect:
        chat_manager.disconnect(session_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5555)