import os
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
from werkzeug.utils import secure_filename
from app.config import Config
from datetime import datetime
import json
import logging
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

def create_session():
    """HTTP 세션 생성"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def split_content(content, max_length=800):
    """콘텐츠를 작은 청크로 분할"""
    if not content:
        return []
        
    # 단순히 길이 기준으로 분할
    chunks = []
    start = 0
    content_length = len(content)
    
    while start < content_length:
        end = start + max_length
        if end < content_length:
            # 문장 끝이나 마침표를 찾아서 자연스럽게 분할
            pos = content.rfind('. ', start, end)
            if pos != -1:
                end = pos + 1
        chunks.append(content[start:end].strip())
        start = end
    
    return chunks

def call_claude_api(session, prompt):
    """Claude API 호출"""
    url = "https://api.anthropic.com/v1/complete"
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
    
    try:
        response = session.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()['completion']
    except requests.exceptions.RequestException as e:
        logger.error(f"API 요청 실패: {str(e)}")
        raise

def analyze_content_in_chunks(content, analysis_type='vtt'):
    """청크 단위로 콘텐츠 분석"""
    try:
        chunks = split_content(content)
        total_chunks = len(chunks)
        logger.info(f"Split content into {total_chunks} chunks")
        
        all_results = []
        session = create_session()
        
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Processing chunk {i}/{total_chunks}")
            
            # 프롬프트 생성
            prompt = "\n\nHuman: " + \
                    f"당신은 {'줌 회의록' if analysis_type == 'vtt' else '채팅 로그'} 분석 전문가입니다. " + \
                    f"다음은 전체 {'회의록' if analysis_type == 'vtt' else '채팅'}의 {i}/{total_chunks} 부분입니다.\n\n" + \
                    f"{chunk}\n\n" + \
                    "다음 형식으로 분석 결과를 제공해주세요:\n\n" + \
                    "# 이 부분의 주요 내용\n[핵심 내용 요약]\n\n" + \
                    "# 주요 키워드\n[이 부분의 주요 키워드들]\n\n" + \
                    f"{'# 중요 포인트' if analysis_type == 'vtt' else '# 대화 분위기'}\n" + \
                    f"[{'이 부분에서 특별히 주목할 만한 내용' if analysis_type == 'vtt' else '이 부분의 대화 톤과 분위기'}]\n\n" + \
                    "Assistant:"
            
            for attempt in range(3):
                try:
                    result = call_claude_api(session, prompt)
                    all_results.append(result)
                    time.sleep(8)
                    break
                except Exception as e:
                    logger.error(f"Chunk {i} 처리 실패 (시도 {attempt + 1}/3): {str(e)}")
                    if attempt < 2:
                        wait_time = 5 * (2 ** attempt)
                        logger.info(f"재시도 대기 중... {wait_time}초")
                        time.sleep(wait_time)
                        session = create_session()  # 새로운 세션 생성
                    else:
                        all_results.append(f"[이 부분 처리 중 오류 발생: {str(e)}]")
                        time.sleep(15)
        
        return "\n\n".join(all_results) if all_results else "분석에 실패했습니다."
        
    except Exception as e:
        logger.error(f"Error in analyze_content_in_chunks: {str(e)}")
        return f"분석 중 오류가 발생했습니다: {str(e)}"

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