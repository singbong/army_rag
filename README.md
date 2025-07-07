# Collaborators

- Mizrhan (Collaborator)
- sumkyun (Collaborator)

# 병무청 모집병 정보 제공 RAG 챗봇

## 1. 프로젝트 개요

이 프로젝트는 병역의 의무를 앞둔 대한민국 청년들을 위해, 복잡하고 다양한 모집병 관련 정보를 쉽고 빠르게 찾아볼 수 있는 AI 챗봇을 제공하는 것을 목표로 합니다.

사용자는 자연어 질문을 통해 육군, 공군 등 각 군의 모집 분야, 지원 자격, 제출 서류, 최신 커트라인 등 병역 이행에 필요한 정보를 얻을 수 있습니다. 챗봇은 **LangGraph** 기반의 RAG(Retrieval-Augmented Generation) 기술을 활용하여 `data` 폴더에 저장된 PDF 문서들을 기반으로 정확하고 신뢰성 있는 답변을 생성합니다.

<img width="645" alt="image" src="https://github.com/user-attachments/assets/e494d6ea-451f-479c-91e4-544073e563e9" />


## 2. 주요 기능

- **자연어 질의응답:** 사용자가 채팅 인터페이스를 통해 질문하면 AI가 답변합니다.
- **LangGraph 기반 워크플로우:** 질문 재작성, 하위 질문 생성, 재귀적 문서 검색, 답변 생성 등 복잡한 프로세스를 LangGraph를 통해 체계적으로 관리합니다.
- **고급 RAG 파이프라인:**
    - **질문 재작성:** 대화의 맥락을 파악하여 후속 질문을 명확하게 재구성합니다.
    - **하위 질문 생성:** 하나의 질문을 여러 개의 구체적인 하위 질문으로 분해하여 더 넓고 깊이 있는 정보를 검색합니다.
    - **멀티 쿼리 생성:** 각 하위 질문을 다양한 관점의 검색어로 변환하여 검색 성능을 높입니다.
    - **하이브리드 검색 및 리랭킹:** 키워드 기반(BM25) 및 의미 기반(FAISS) 검색을 결합하고, LLM을 통해 검색된 문서의 관련성을 재평가하여 가장 정확한 문서를 선별합니다.
- **다중 LLM 지원:** `docker-compose.yml`을 통해 여러 LLM 모델(e.g., Llama3-8B, Qwen2.5-32B)을 서비스하며, 각 단계의 목적에 맞는 모델을 활용합니다.
- **웹 인터페이스 및 세션 관리:** FastAPI로 구축된 웹 페이지를 통해 사용자와 상호작용하며, 사용자별 대화 기록을 관리합니다.

## 3. 사용 기술

- **Backend:** FastAPI, Uvicorn
- **LLM/RAG:** LangChain, LangGraph, vLLM
- **Frontend:** HTML, CSS, JavaScript (Jinja2 템플릿 사용)
- **Containerization:** Docker, Docker Compose

## 4. 프로젝트 구조

```
.
├── docker-compose.yml      # 서비스 실행을 위한 Docker Compose 설정
├── Dockerfile              # RAG 챗봇 서비스의 Docker 이미지 빌드 설정
├── requirements.txt        # Python 패키지 의존성 목록
├── data/                   # RAG의 정보 검색 대상이 되는 PDF 문서 폴더
└── rag_page/
    ├── app.py              # FastAPI 웹 애플리케이션 및 LangGraph 워크플로우 정의
    ├── simple_rag_with_pages.py # RAG 검색 및 초기화 로직
    ├── templates/          # 웹 프론트엔드 HTML 템플릿
    └── static/             # CSS, JavaScript 등 정적 파일
```

## 5. 실행 방법

**사전 요구사항:**
- [Docker](https://www.docker.com/get-started) 및 [Docker Compose](https://docs.docker.com/compose/install/)가 설치되어 있어야 합니다.
- NVIDIA GPU 및 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)이 필요합니다.

**실행 순서:**

1. **프로젝트 클론**
   ```bash
   git clone https://github.com/your-username/docker_rag.git
   cd docker_rag
   ```

2. **필요한 LLM 모델 다운로드 (Hugging Face Hub)**
   `docker-compose.yml`에 명시된 모델들을 미리 다운로드하여 vLLM 캐시 경로에 저장해야 합니다.
   - `llama-3-Korean-Bllossom-8B`
   - `Qwen2.5-32B-Instruct`

3. **Docker Compose를 사용하여 서비스 실행**
   아래 명령어를 실행하여 모든 서비스(vLLM, RAG Chat)를 빌드하고 실행합니다.
   ```bash
   docker-compose up --build -d
   ```

4. **애플리케이션 접속**
   웹 브라우저를 열고 `http://localhost:5555` 주소로 접속하여 챗봇 서비스를 이용할 수 있습니다.

## 6. 작동 원리 (LangGraph 기반)

1.  **Vector Store 생성:** `rag_page/app.py`가 실행될 때 `init_fast_rag` 함수가 호출됩니다. 이 함수는 `data` 폴더에 있는 PDF 문서들을 로드하여 텍스트로 분할하고, 임베딩 모델을 사용해 벡터로 변환한 뒤 FAISS 벡터 저장소에 저장합니다.
2.  **사용자 질문:** 사용자가 웹 인터페이스에서 질문을 입력합니다.
3.  **LangGraph 워크플로우 시작:**
    - **ReWriter 노드:** 이전 대화 기록을 참고하여, 모호한 질문("그건 어때?")을 명확한 질문("카투사 지원 자격은 어때?")으로 재작성합니다.
    - **Question Decomposer 노드:** 재작성된 질문을 바탕으로, 더 풍부한 답변을 위해 관련된 하위 질문들을 생성합니다. (예: "카투사 지원 자격" -> "카투사 어학 성적", "카투사 신체 조건")
    - **Recursive Search 노드 (반복 실행):**
        - 각 하위 질문에 대해 `enhanced_multi_search` 함수를 호출합니다.
        - **멀티 쿼리:** 하위 질문을 2개의 다른 검색어로 변환합니다.
        - **문서 검색:** 변환된 검색어들로 FAISS와 BM25에서 문서를 검색합니다.
        - **LLM 리랭킹:** 검색된 모든 문서의 관련성을 경량 LLM(8B)으로 평가하여 점수가 높은 순으로 정렬하고, 가장 관련성 높은 문서들만 선택합니다.
        - 모든 하위 질문에 대한 문서 검색이 끝날 때까지 이 과정을 반복하고 결과를 누적합니다.
    - **Generate Answer 노드:**
        - 모든 관련 문서를 종합하고, 원본 질문 및 대화 기록과 함께 프롬프트를 구성합니다.
        - 이 프롬프트를 주력 LLM(32B)에 전달하여 최종 답변을 생성합니다.
4.  **답변 반환:** 생성된 답변이 사용자에게 표시됩니다.
