#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
병무청 AI 상담 시스템 - 벡터스토어 생성 스크립트
===============================================
PDF 문서들을 토큰 기반 청킹으로 처리하여 FAISS 벡터스토어를 생성합니다.

실행 방법:
- rag-chat 컨테이너에서 실행: python make_vector_store.py
"""

from simple_rag_with_pages import SimpleRAGWithPages

def main():
    """벡터스토어 생성 메인 함수"""
    print("=" * 50)
    print("🏗️ 병무청 AI 상담 시스템 - 벡터스토어 생성 시작")
    print("=" * 50)
    
    # RAG 시스템 초기화
    print("🔄 RAG 시스템 인스턴스 생성 중...")
    rag_system = SimpleRAGWithPages(
        data_path="/app/workspace/data",
        store_path="/app/shared_data"
    )
    
    # 벡터스토어 생성
    print("\n🔄 벡터스토어 생성 시작...")
    vectorstore = rag_system.create_vectorstore(store_name="vector_store")
    
    if vectorstore:
        print("\n✅ 벡터스토어 생성 완료!")
        print("💡 이제 병무청 AI 상담 시스템을 사용할 수 있습니다.")
    else:
        print("\n❌ 벡터스토어 생성 실패!")
        print("📋 PDF 파일이 /app/workspace/data 경로에 있는지 확인하세요.")

if __name__ == "__main__":
    main()