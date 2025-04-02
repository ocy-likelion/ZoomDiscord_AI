import os
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from app.config import Config
from anthropic import Anthropic
from datetime import datetime
import json

app = Flask(__name__)
app.config.from_object(Config)

# Anthropic 클라이언트 초기화
client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# 업로드 폴더 생성
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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
    if 'vtt_file' not in request.files:
        return jsonify({'error': '파일이 없습니다.'}), 400
    
    file = request.files['vtt_file']
    if file.filename == '':
        return jsonify({'error': '선택된 파일이 없습니다.'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        try:
            # 파일 읽기
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Claude API 호출
            prompt = f"\n\nHuman: 당신은 줌 회의록 분석 전문가입니다. 다음 VTT 파일을 분석해주세요:\n\n{content}\n\n다음 형식으로 분석 결과를 제공해주세요:\n\n# 회의 요약\n- 회의 주제:\n- 주요 참석자:\n- 회의 시간:\n- 핵심 논의 사항:\n- 결정사항:\n- 후속 조치사항:\n\n# 상세 내용\n[시간대별 주요 내용]\n\n# 주요 키워드\n[회의에서 언급된 주요 키워드들]\n\n# 액션 아이템\n[구체적인 할 일과 담당자]\n\n# 추가 참고사항\n[기타 중요한 정보나 맥락]\n\nAssistant:"
            
            completion = client.completions.create(
                prompt=prompt,
                model="claude-2.1",
                max_tokens_to_sample=4000,
                stop_sequences=["\n\nHuman:"],
                temperature=0.7
            )
            
            # 분석 결과
            result = {
                'status': 'success',
                'result': completion.completion,
                'timestamp': datetime.now().isoformat()
            }
            
            # 결과를 JSON 파일로 저장
            result_file = file_path.replace('.vtt', '_analysis.json')
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    return jsonify({'error': '허용되지 않는 파일 형식입니다.'}), 400

@app.route('/analyze_chat', methods=['POST'])
def analyze_chat():
    if 'chat_file' not in request.files:
        return jsonify({'error': '파일이 없습니다.'}), 400
    
    file = request.files['chat_file']
    if file.filename == '':
        return jsonify({'error': '선택된 파일이 없습니다.'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        try:
            # 파일 읽기
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Claude API 호출
            prompt = f"\n\nHuman: 당신은 채팅 로그 분석 전문가입니다. 다음 채팅 로그를 분석해주세요:\n\n{content}\n\n다음 형식으로 분석 결과를 제공해주세요:\n\n# 채팅 요약\n- 대화 주제:\n- 주요 참여자:\n- 핵심 논의 사항:\n- 결정사항:\n- 후속 조치사항:\n\n# 주요 키워드\n[대화에서 언급된 주요 키워드들]\n\n# 감정/태도 분석\n[대화의 전반적인 톤과 참여자들의 태도]\n\n# 추가 참고사항\n[기타 중요한 정보나 맥락]\n\nAssistant:"
            
            completion = client.completions.create(
                prompt=prompt,
                model="claude-2.1",
                max_tokens_to_sample=4000,
                stop_sequences=["\n\nHuman:"],
                temperature=0.7
            )
            
            # 분석 결과
            result = {
                'status': 'success',
                'result': completion.completion,
                'timestamp': datetime.now().isoformat()
            }
            
            # 결과를 JSON 파일로 저장
            result_file = file_path.replace('.txt', '_analysis.json')
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    return jsonify({'error': '허용되지 않는 파일 형식입니다.'}), 400

@app.route('/result/<filename>')
def get_result(filename):
    result_file = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(result_file):
        return send_file(result_file, as_attachment=True)
    return jsonify({'error': '결과 파일을 찾을 수 없습니다.'}), 404

if __name__ == '__main__':
    app.run(debug=True) 