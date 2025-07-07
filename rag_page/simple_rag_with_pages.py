#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
병무청 AI 상담 시스템 - RAG 모듈
=================================
핵심 기능:
1. PDF 문서 → 토큰 기반 청킹 → 임베딩 → FAISS 저장
2. 하이브리드 검색 (FAISS + BM25)
"""

import os
import glob
import pdfplumber
from typing import List
import warnings
from transformers import AutoTokenizer

warnings.filterwarnings("ignore")

# LangChain imports
from langchain_community.vectorstores import FAISS
try:
    from langchain_ollama import OllamaEmbeddings
except ImportError:
    from langchain_community.embeddings import OllamaEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain_community.retrievers.bm25 import BM25Retriever
from langchain.retrievers.ensemble import EnsembleRetriever
from langchain_experimental.text_splitter import SemanticChunker

class SimpleRAGWithPages:
    """병무청 AI 상담을 위한 토큰 기반 RAG 시스템"""
    
    def __init__(self, data_path: str = "/app/workspace/data", store_path: str = "/app/shared_data"):
        self.data_path = data_path
        self.store_path = store_path
        os.makedirs(self.store_path, exist_ok=True)
        
        # 임베딩 모델
        self.embedding = OllamaEmbeddings(
            model="bge-m3:latest",
            base_url="http://ollama:11434"
        )
        
        # BGE M3 토크나이저 (토큰 기반 청킹용)
        self.tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
        
        # 검색기들
        self.vectorstore = None
        self.bm25_retriever = None
        self.faiss_retriever = None
        self.ensemble_retriever = None
        self.is_loaded = False
        
    def count_tokens(self, text: str) -> int:
        """텍스트의 토큰 수 계산"""
        return len(self.tokenizer.encode(text, add_special_tokens=False))
    
    def create_vectorstore(self, store_name: str = "vector_store"):
        """PDF 문서를 토큰 기반 청킹으로 처리하여 벡터스토어 생성"""
        # PDF 파일 수집
        pdf_files = glob.glob(os.path.join(self.data_path, "*.pdf"))
        if not pdf_files:
            print(f"{self.data_path}에 PDF 파일이 없습니다!")
            return None
            
        print(f"처리할 PDF 파일: {len(pdf_files)}개")
        
        # 모든 문서 수집
        all_documents = []
        
        for pdf_path in pdf_files:
            file_name = os.path.basename(pdf_path)
            print(f"처리 중: {file_name}")
            
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    for page_num, page in enumerate(pdf.pages, 1):
                        text = page.extract_text()
                        if text and text.strip():
                            doc = Document(
                                page_content=text.strip(),
                                metadata={
                                    "source": file_name,
                                    "page": page_num,
                                    "total_pages": len(pdf.pages)
                                }
                            )
                            all_documents.append(doc)
                            
                print(f"{file_name}: {len(pdf.pages)}페이지 처리 완료")
            except Exception as e:
                print(f"{file_name} 처리 중 오류: {e}")
                continue
        
        if not all_documents:
            print("처리된 문서가 없습니다!")
            return None
            
        print(f"총 {len(all_documents)}개 페이지 문서 생성")
        
        # 재귀적 텍스트 분할기를 사용한 고정 크기 청킹
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=3000,
            chunk_overlap=300,
            length_function=self.count_tokens,
            separators=["\n\n", "\n", " ", ""]
        )
        
        # 문서 청킹
        all_chunks = []
        for doc in all_documents:
            chunks = text_splitter.split_documents([doc])
            for chunk in chunks:
                # 메타데이터 업데이트
                chunk.metadata.update({
                    "pages": [doc.metadata["page"]],
                    "primary_page": doc.metadata["page"]
                })
                all_chunks.append(chunk)
        
        print(f"총 {len(all_chunks)}개 청크 생성")
        
        # FAISS 벡터스토어 생성
        print("벡터스토어 생성 중...")
        vectorstore = FAISS.from_documents(
            documents=all_chunks,
            embedding=self.embedding
        )
        
        # 저장
        save_path = os.path.join(self.store_path, store_name)
        vectorstore.save_local(save_path)
        print(f"벡터스토어 저장 완료: {save_path}")
        
        return vectorstore
    
    def load_retriever(self, store_name: str = "vector_store"):
        """벡터스토어 로드 및 검색기 초기화"""
        if self.is_loaded:
            return True
            
        store_path = os.path.join(self.store_path, store_name)
        if not os.path.exists(store_path):
            print(f"벡터스토어를 찾을 수 없습니다: {store_path}")
            return False
        
        try:
            # FAISS 로드
            self.vectorstore = FAISS.load_local(
                store_path,
                self.embedding,
                allow_dangerous_deserialization=True
            )
            
            # 검색기 설정
            self.faiss_retriever = self.vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 10}
            )
            
            # BM25 검색기 초기화
            documents = [doc.page_content for doc in self.vectorstore.docstore._dict.values()]
            self.bm25_retriever = BM25Retriever.from_texts(
                documents,
                metadatas=[doc.metadata for doc in self.vectorstore.docstore._dict.values()]
            )
            self.bm25_retriever.k = 10
            
            # 앙상블 검색기
            self.ensemble_retriever = EnsembleRetriever(
                retrievers=[self.faiss_retriever, self.bm25_retriever],
                weights=[0.6, 0.4]  # FAISS 60%, BM25 40%
            )
            
            self.is_loaded = True
            print(f"검색기 로드 완료: {store_name}")
            return True
            
        except Exception as e:
            print(f"검색기 로드 실패: {e}")
            return False
    
    def search(self, query: str, k: int = 5):
        """하이브리드 검색 수행"""
        if not self.is_loaded:
            print("검색기가 로드되지 않았습니다.")
            return []
        
        try:
            # 앙상블 검색
            results = self.ensemble_retriever.get_relevant_documents(query)
            
            # 결과 제한
            if len(results) > k:
                results = results[:k]
                
            print(f"검색 결과: {len(results)}개 문서")
            return results
            
        except Exception as e:
            print(f"검색 중 오류: {e}")
            return []

# 전역 RAG 인스턴스
rag_instance = None

def init_fast_rag(data_path: str = "/app/workspace/data", store_name: str = "vector_store"):
    """RAG 시스템 초기화"""
    global rag_instance
    
    if rag_instance is None:
        rag_instance = SimpleRAGWithPages(data_path=data_path)
    
    success = rag_instance.load_retriever(store_name)
    if not success:
        print("기존 벡터스토어를 찾을 수 없습니다. 새로 생성합니다...")
        rag_instance.create_vectorstore(store_name)
        rag_instance.load_retriever(store_name)
    
    return rag_instance

def fast_search(query: str, k: int = 5):
    """빠른 검색 함수"""
    global rag_instance
    
    if rag_instance is None:
        print("RAG 시스템이 초기화되지 않았습니다.")
        return []
    
    return rag_instance.search(query, k)

def reset_rag():
    """RAG 시스템 리셋"""
    global rag_instance
    rag_instance = None
    print("RAG 시스템이 리셋되었습니다.")
