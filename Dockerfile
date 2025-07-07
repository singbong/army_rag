# 1단계: 빌드 환경 (Builder)
# Faiss를 소스에서 컴파일하기 위해 CUDA 개발 도구가 포함된 NVIDIA 공식 이미지를 사용합니다.
FROM nvidia/cuda:12.1.1-devel-ubuntu22.04 AS builder

# 시스템 도구 및 기본 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    libpython3.11-dev \
    python3-pip \
    curl \
    wget \
    gnupg2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Miniconda 설치 (INSTALL.md 권장 방법)
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda clean -ya

# PATH에 conda 추가
ENV PATH="/opt/conda/bin:$PATH"

# Python 3.11을 기본 python/python3으로 설정
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# pip 업그레이드
RUN python -m pip install --upgrade pip setuptools wheel

# INSTALL.md 권장: faiss-gpu-cuvs conda 패키지 설치 (소스 빌드 대신)
RUN conda install -y -c pytorch -c nvidia -c rapidsai -c conda-forge \
    libnvjitlink \
    faiss-gpu-cuvs=1.11.0 \
    'cuda-version>=12.0,<=12.5' \
    python=3.11 \
    'numpy<2' && \
    conda clean -ya

# 2단계: 최종 실행 환경 (Final Runtime Image)
# 실제 애플리케이션을 실행할 가벼운 CUDA 런타임 이미지를 사용합니다.
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# 비대화형 환경 지정
ENV DEBIAN_FRONTEND=noninteractive

# 타임존 파일 미리 복사 및 환경변수 지정
RUN ln -snf /usr/share/zoneinfo/Asia/Seoul /etc/localtime && echo "Asia/Seoul" > /etc/timezone

# 애플리케이션 실행에 필요한 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3-pip \
    curl \
    wget \
    git \
    libpoppler-cpp-dev \
    pkg-config \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 타임존을 서울로 설정
ENV TZ=Asia/Seoul

# Python 3.11을 기본 python/python3으로 설정
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# 빌드 환경에서 Conda 전체 환경 복사 (faiss-gpu-cuvs 포함)
COPY --from=builder /opt/conda /opt/conda

# PATH에 conda 추가
ENV PATH="/opt/conda/bin:$PATH"

# 라이브러리 경로 설정
ENV LD_LIBRARY_PATH=/opt/conda/lib:$LD_LIBRARY_PATH

# 라이브러리 캐시 업데이트
RUN ldconfig

# 애플리케이션 작업 디렉토리 설정
WORKDIR /app

# requirements.txt 복사 및 Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 전체 소스 코드 복사
COPY . .

# 애플리케이션에서 사용할 디렉토리 생성
RUN mkdir -p /app/rag_storage /app/uploads /app/outputs

# FastAPI 애플리케이션 포트 노출
EXPOSE 5555

# 컨테이너 실행 시 FastAPI 서버 구동
CMD ["uvicorn", "rag_page.app:app", "--host", "0.0.0.0", "--port", "5555"]