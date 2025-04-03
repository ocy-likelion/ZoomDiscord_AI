import os
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
from werkzeug.utils import secure_filename
from app.config import Config
from anthropic import Anthropic
from datetime import datetime
import json
import logging
import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import socket
import asyncio
import anthropic
import re
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# 글로벌 타임아웃 설정
socket.setdefaulttimeout(60)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB 제한
app.config['ALLOWED_EXTENSIONS'] = {'vtt', 'txt'}  # 허용된 파일 확장자

# 업로드 폴더가 없으면 생성
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# API 키 설정
api_key = os.getenv('ANTHROPIC_API_KEY')
if not api_key:
    raise ValueError("ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.")

# requests 세션 설정
session = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=3, pool_maxsize=10)
session.mount("http://", adapter)
session.mount("https://", adapter)

def split_content(content, max_length=800):  # 청크 크기 축소
    """콘텐츠를 작은 청크로 분할"""
    chunks = []
    current_chunk = []
    current_length = 0
    
    sentences = re.split(r'([.!?]+\s+)', content)
    
    for sentence in sentences:
        sentence_length = len(sentence)
        if current_length + sentence_length > max_length and current_chunk:
            chunks.append(''.join(current_chunk))
            current_chunk = [sentence]
            current_length = sentence_length
        else:
            current_chunk.append(sentence)
            current_length += sentence_length
    
    if current_chunk:
        chunks.append(''.join(current_chunk))
    
    return chunks

def call_claude_api(prompt):
    """Claude API 직접 호출"""
    max_retries = 3
    base_wait_time = 10
    
    for attempt in range(max_retries):
        try:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            
            data = {
                "prompt": prompt,
                "model": "claude-instant-1.2",
                "max_tokens_to_sample": 1500,
                "temperature": 0.7,
                "stop_sequences": ["\n\nHuman:"]
            }
            
            response = session.post(
                "https://api.anthropic.com/v1/complete",
                headers=headers,
                json=data,
                timeout=60
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API 응답 오류: {response.status_code} - {response.text}")
                if attempt < max_retries - 1:
                    wait_time = base_wait_time * (2 ** attempt)  # 지수 백오프
                    time.sleep(wait_time)
                    continue
                raise Exception(f"API 응답 오류: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"API 호출 실패 (시도 {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                wait_time = base_wait_time * (2 ** attempt)
                time.sleep(wait_time)
                continue
            raise
    
    raise Exception("최대 재시도 횟수를 초과했습니다.")

def analyze_content_in_chunks(content, analysis_type='vtt'):
    """청크 단위로 콘텐츠 분석"""
    chunks = split_content(content)
    total_chunks = len(chunks)
    logger.info(f"Split content into {total_chunks} chunks")
    
    all_results = []
    for i, chunk in enumerate(chunks, 1):
        logger.info(f"Processing chunk {i}/{total_chunks}")
        
        try:
            result = call_claude_api(
                prompt=f"\n\nHuman: 당신은 {'줌 회의록' if analysis_type == 'vtt' else '채팅 로그'} 분석 전문가입니다. "
                f"다음은 전체 {'회의록' if analysis_type == 'vtt' else '채팅'}의 {i}/{total_chunks} 부분입니다. "
                f"이 부분을 분석해주세요:\n\n{chunk}\n\n"
                f"다음 형식으로 분석 결과를 제공해주세요:\n\n"
                f"# 이 부분의 주요 내용\n[핵심 내용 요약]\n\n"
                f"# 주요 키워드\n[이 부분의 주요 키워드들]\n\n"
                f"{'# 중요 포인트' if analysis_type == 'vtt' else '# 대화 분위기'}\n"
                f"[{'이 부분에서 특별히 주목할 만한 내용' if analysis_type == 'vtt' else '이 부분의 대화 톤과 분위기'}]\n\n"
                f"Assistant:"
            )
            all_results.append(result['completion'])
            time.sleep(3)
            
        except Exception as e:
            logger.error(f"Failed to process chunk {i}: {str(e)}")
            all_results.append(f"[이 부분 처리 중 오류 발생: {str(e)}]")
            time.sleep(10)
    
    if not all_results:
        return "분석에 실패했습니다. 네트워크 연결을 확인해주세요."
    
    return "\n\n".join(all_results)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/vtt_analysis')
def vtt_analysis():
    return render_template('vtt_analysis.html')

@app.route('/chat_analysis')
def chat_analysis():
    return render_template('chat_analysis.html')

@app.route('/analyze_vtt', methods=['POST'])
def analyze_vtt():
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다.'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '선택된 파일이 없습니다.'}), 400
    
    if not file.filename.endswith('.vtt'):
        return jsonify({'error': 'VTT 파일만 업로드 가능합니다.'}), 400
    
    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # VTT 파일 분석
        result = analyze_content_in_chunks(content, 'vtt')
        
        # 분석 결과 저장
        result_filename = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        result_path = os.path.join(app.config['UPLOAD_FOLDER'], result_filename)
        
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(result)
        
        return jsonify({
            'message': '분석이 완료되었습니다.',
            'result': result,
            'download_url': f'/download/{result_filename}'
        })
        
    except Exception as e:
        logger.error(f"Error processing VTT file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/analyze_chat', methods=['POST'])
def analyze_chat():
    try:
        content = None
        logger.info("Received chat analysis request")
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Form data: {request.form}")
        logger.info(f"Files: {request.files}")
        
        # JSON 형식 처리
        if request.is_json:
            logger.info("Processing JSON request")
            data = request.get_json()
            logger.info(f"Received JSON data: {data}")
            if data and 'content' in data:
                content = data['content']
                logger.info("Successfully extracted content from JSON")
        
        # form-data 형식 처리
        elif 'content' in request.form:
            logger.info("Processing form-data request")
            content = request.form['content']
            logger.info("Successfully extracted content from form")
        
        # 파일 업로드 처리
        elif 'file' in request.files:
            logger.info("Processing file upload")
            file = request.files['file']
            if file.filename != '':
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                logger.info(f"File saved to {filepath}")
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    logger.info("Successfully read file content")
                except Exception as e:
                    logger.error(f"Error reading file: {str(e)}")
                    return jsonify({'error': f'파일 읽기 오류: {str(e)}'}), 400
        
        if not content:
            logger.error("No content found in request")
            return jsonify({'error': '채팅 내용이 없습니다. content 필드를 확인해주세요.'}), 400
        
        if not isinstance(content, str):
            logger.error(f"Invalid content type: {type(content)}")
            return jsonify({'error': '채팅 내용은 문자열이어야 합니다.'}), 400
        
        if len(content.strip()) == 0:
            logger.error("Empty content received")
            return jsonify({'error': '채팅 내용이 비어있습니다.'}), 400
        
        logger.info("Starting chat analysis with Claude API")
        logger.info(f"Content length: {len(content)} characters")
        
        # 채팅 내용 분석
        result = analyze_content_in_chunks(content, 'chat')
        
        # 분석 결과 저장
        result_filename = f"chat_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        result_path = os.path.join(app.config['UPLOAD_FOLDER'], result_filename)
        
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(result)
        
        logger.info("Analysis completed successfully")
        return jsonify({
            'message': '분석이 완료되었습니다.',
            'result': result,
            'download_url': f'/download/{result_filename}'
        })
        
    except Exception as e:
        logger.error(f"Error processing chat content: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/result/<filename>')
def get_result(filename):
    result_file = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(result_file):
        return send_file(result_file, as_attachment=True)
    return jsonify({'error': '결과 파일을 찾을 수 없습니다.'}), 404

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True) 