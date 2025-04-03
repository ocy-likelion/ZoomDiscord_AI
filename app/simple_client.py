import os
import logging
import time
import requests
from typing import List, Optional

logger = logging.getLogger(__name__)

class SimpleAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1/complete"
        self.headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        logger.info("SimpleAPIClient 초기화 완료")

    def split_text(self, text: str, chunk_size: int = 800) -> List[str]:
        """단순한 텍스트 분할"""
        if not text:
            logger.warning("분할할 텍스트가 비어있음")
            return []
        
        chunks = []
        start = 0
        text_length = len(text)
        logger.info(f"텍스트 분할 시작. 전체 길이: {text_length} 문자")
        
        while start < text_length:
            end = min(start + chunk_size, text_length)
            # 문장 끝을 찾아서 자연스럽게 분할
            if end < text_length:
                last_period = text.rfind('. ', start, end)
                if last_period != -1:
                    end = last_period + 1
            chunk = text[start:end].strip()
            chunks.append(chunk)
            logger.debug(f"청크 생성: {len(chunk)} 문자")
            start = end
        
        logger.info(f"텍스트 분할 완료. 총 {len(chunks)}개의 청크 생성")
        return chunks

    def make_request(self, prompt: str) -> Optional[str]:
        """단순한 API 요청"""
        try:
            logger.info("API 요청 시작")
            data = {
                "prompt": prompt,
                "model": "claude-instant-1.2",
                "max_tokens_to_sample": 1500,
                "temperature": 0.7,
                "stop_sequences": ["\n\nHuman:"]
            }
            
            logger.debug(f"요청 데이터: {data}")
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()['completion']
            logger.info("API 요청 성공")
            logger.debug(f"응답 길이: {len(result)} 문자")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API 요청 실패 (네트워크/HTTP 오류): {str(e)}")
            return None
        except Exception as e:
            logger.error(f"API 요청 실패 (예상치 못한 오류): {str(e)}")
            return None

    def analyze_text(self, text: str, analysis_type: str = 'chat') -> str:
        """텍스트 분석"""
        try:
            logger.info(f"텍스트 분석 시작 (유형: {analysis_type})")
            
            # 텍스트 분할
            chunks = self.split_text(text)
            total_chunks = len(chunks)
            logger.info(f"분할된 청크 수: {total_chunks}")
            
            if not chunks:
                logger.error("분석할 청크가 없음")
                return "분석할 내용이 없습니다."
            
            results = []
            
            # 각 청크 처리
            for i, chunk in enumerate(chunks, 1):
                logger.info(f"청크 {i}/{total_chunks} 처리 중")
                
                # 기본 프롬프트
                prompt = (
                    f"\n\nHuman: 당신은 {analysis_type} 분석 전문가입니다. "
                    f"다음은 전체 텍스트의 {i}/{total_chunks} 부분입니다.\n\n"
                    f"{chunk}\n\n"
                    "다음 형식으로 분석 결과를 제공해주세요:\n\n"
                    "# 주요 내용\n[핵심 내용 요약]\n\n"
                    "# 키워드\n[주요 키워드들]\n\n"
                    "# 분석\n[상세 분석 내용]\n\n"
                    "Assistant:"
                )
                
                # API 호출 및 재시도
                for attempt in range(3):
                    logger.info(f"청크 {i} API 호출 시도 {attempt + 1}/3")
                    result = self.make_request(prompt)
                    if result:
                        results.append(result)
                        logger.info(f"청크 {i} 처리 성공")
                        time.sleep(5)  # API 호출 간격
                        break
                    else:
                        logger.warning(f"청크 {i} 처리 실패 (시도 {attempt + 1}/3)")
                        if attempt < 2:
                            wait_time = 5 * (attempt + 1)
                            logger.info(f"{wait_time}초 대기 후 재시도")
                            time.sleep(wait_time)
                        else:
                            results.append(f"[청크 {i} 처리 실패]")
                            logger.error(f"청크 {i} 최종 처리 실패")
                            time.sleep(10)
            
            # 결과 조합
            final_result = "\n\n".join(results) if results else "분석 실패"
            logger.info("텍스트 분석 완료")
            return final_result
            
        except Exception as e:
            logger.error(f"분석 중 예상치 못한 오류 발생: {str(e)}")
            return f"오류 발생: {str(e)}" 