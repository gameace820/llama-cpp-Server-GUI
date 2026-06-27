import sys
import json
import base64
import io
import re
import threading
import time
import os
import requests
import codecs
import webbrowser
from datetime import datetime
from PIL import Image
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tavern-secret-2024'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

SERVER_PORT = 8181

server_status = {
    "running": True,
    "api_url": "http://localhost:8080/completion",
    "api_connected": False,
    "character_name": "老酒",
    "character_description": "",
    "chat_count": 0,
    "start_time": "",
}

chat_history = []
character_card = None
chat_save_dir = "saved_chats"
user_name = "用户"
current_chat_id = None

stop_event = threading.Event()

default_llm_params = {
    "max_context_tokens": 65536,
    "max_response_tokens": 2048,
    "temperature": 0.8,
    "top_p": 0.95,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "model_type": "qwen",
    "no_think": True,
}

NO_THINK_PROMPT = "\n\n【严格禁止】你绝对不能输出任何思考过程、内心独白、推理步骤、括号内的解释或说明。只允许输出最终的直接回复，不得有任何前缀、后缀或附加说明。"

TEMPLATES = {
    "gemma": {
        "system": "<bos><start_of_turn>system\n{system}<end_of_turn>\n",
        "user": "<start_of_turn>user\n{input}<end_of_turn>\n",
        "assistant": "<start_of_turn>model\n",
        "end": "<end_of_turn>\n",
    },
    "qwen": {
        "system": "<|im_start|>system\n{system}<|im_end|>\n",
        "user": "<|im_start|>user\n{input}<|im_end|>\n",
        "assistant": "<|im_start|>assistant\n",
        "end": "<|im_end|>\n",
    },
    "llama": {
        "system": "{system}\n\n",
        "user": "用户: {input}\n",
        "assistant": "",
        "end": "\n",
    },
}

os.makedirs(chat_save_dir, exist_ok=True)

def get_local_ip():
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def parse_v2_character_card(file_bytes):
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img_text = getattr(img, 'text', None)
        if not img_text: return None
        chara_data = None
        for key in ['chara', 'ccv3', 'character', 'data', 'description']:
            if key in img_text:
                raw = img_text[key]
                try:
                    decoded = base64.b64decode(raw).decode('utf-8', errors='ignore')
                    chara_data = json.loads(decoded)
                    break
                except:
                    try:
                        chara_data = json.loads(raw)
                        break
                    except: pass
        if chara_data is None: return None
        char_data = chara_data.get("data", chara_data)
        if isinstance(char_data, str):
            try: char_data = json.loads(char_data)
            except: char_data = {}
        return {
            'name': char_data.get('name', '未命名'),
            'system_prompt': char_data.get('system_prompt', ''),
            'first_mes': char_data.get('first_mes', '你好。'),
            'description': char_data.get('description', ''),
        }
    except: return None

def parse_v2_character_json(json_data):
    try:
        if isinstance(json_data, str): json_data = json.loads(json_data)
        char_data = json_data.get("data", json_data)
        if isinstance(char_data, str): char_data = json.loads(char_data)
        return {
            'name': char_data.get('name', '未命名'),
            'system_prompt': char_data.get('system_prompt', ''),
            'first_mes': char_data.get('first_mes', '你好。'),
            'description': char_data.get('description', ''),
        }
    except: return None

def build_prompt(history, char, llm_params):
    template_name = llm_params.get('model_type', 'qwen')
    template = TEMPLATES.get(template_name, TEMPLATES["qwen"])
    no_think = llm_params.get('no_think', True)

    system_prompt = char.get('system_prompt', '你是一个人工智能助手。') if char else '你是一个人工智能助手。'
    if no_think:
        system_prompt += NO_THINK_PROMPT

    char_name = char.get('name', '角色') if char else '助手'
    system_prompt = system_prompt.replace("{{user}}", user_name).replace("{{char}}", char_name)

    history_str = ""
    for msg in history:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if role == 'system' and not char:
            continue
        if role == 'user':
            history_str += template["user"].format(input=content)
        elif role == 'assistant':
            if template_name in ["qwen", "gemma"]:
                history_str += template["assistant"] + content + template["end"]
            else:
                history_str += content + template["end"]

    prompt = ""
    if system_prompt:
        prompt += template["system"].format(system=system_prompt)
    if history_str:
        prompt += history_str
    
    prompt += template["assistant"]
    return prompt, len(history)

def auto_save_current_chat():
    global current_chat_id
    if not character_card or len(chat_history) <= 1: return
    if not current_chat_id:
        current_chat_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = safe_filename("{}_{}.json".format(character_card.get('name', 'chat'), current_chat_id))
    filepath = os.path.join(chat_save_dir, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                'chat_id': current_chat_id,
                'timestamp': datetime.now().isoformat(),
                'character': character_card,
                'history': chat_history,
                'llm_params': dict(default_llm_params),
                'chat_count': server_status['chat_count'],
                'user_name': user_name,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[自动存档失败] {e}")

def apply_character(char_data):
    global character_card, chat_history, current_chat_id
    auto_save_current_chat()
    current_chat_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    character_card = char_data
    server_status['character_name'] = char_data['name']
    server_status['character_description'] = char_data.get('description', '')[:200]
    chat_history = []
    
    first_mes = char_data.get('first_mes', '')
    if first_mes:
        first_mes = first_mes.replace("{{user}}", user_name).replace("{{char}}", char_data['name'])
        chat_history.append({"role": "assistant", "content": first_mes})

    filename = safe_filename("{}_{}.json".format(char_data['name'], current_chat_id))
    filepath = os.path.join(chat_save_dir, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                'chat_id': current_chat_id,
                'timestamp': datetime.now().isoformat(),
                'character': char_data,
                'history': chat_history,
                'llm_params': dict(default_llm_params),
                'chat_count': 0,
                'user_name': user_name,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e: pass
    return jsonify({
        'success': True,
        'character': { 'name': char_data['name'], 'description': char_data.get('description', '')[:500], 'first_mes': first_mes }
    })

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/status')
def get_status(): return jsonify(server_status)

@app.route('/api/llm_params')
def get_llm_params(): return jsonify(default_llm_params)

@app.route('/api/local_ip')
def api_get_local_ip():
    return jsonify({'ip': get_local_ip(), 'port': SERVER_PORT})

@app.route('/api/user_name', methods=['GET', 'POST'])
def handle_user_name():
    global user_name
    if request.method == 'POST':
        data = request.json
        if data and 'user_name' in data:
            user_name = data['user_name'].strip() or '用户'
            return jsonify({'success': True, 'user_name': user_name})
    return jsonify({'user_name': user_name})

@app.route('/api/set_api_url', methods=['POST'])
def set_api_url():
    data = request.json
    if not data: return jsonify({'success': False})
    url = data.get('api_url', '').strip()
    if url:
        server_status['api_url'] = url
        connected = False
        try:
            check_url = url.replace('/completion', '/health') if '/completion' in url else url.rsplit('/', 1)[0] + '/health'
            r = requests.get(check_url, timeout=2)
            connected = (r.status_code == 200)
        except: pass
        server_status['api_connected'] = connected
        return jsonify({'success': True, 'connected': connected})
    return jsonify({'success': False})

@app.route('/api/upload_character', methods=['POST'])
def upload_character():
    if 'file' not in request.files: return jsonify({'success': False, 'error': '没有文件'})
    file = request.files['file']
    file_bytes = file.read()
    if len(file_bytes) == 0: return jsonify({'success': False, 'error': '文件为空'})
    char_data = parse_v2_character_card(file_bytes)
    if char_data is None: return jsonify({'success': False, 'error': '无法解析PNG角色卡'})
    return apply_character(char_data)

@app.route('/api/upload_character_json_file', methods=['POST'])
def upload_character_json_file():
    if 'file' not in request.files: return jsonify({'success': False, 'error': '没有文件'})
    file = request.files['file']
    try:
        file_bytes = file.read()
        if len(file_bytes) == 0: return jsonify({'success': False, 'error': '文件为空'})
        json_data = json.loads(file_bytes.decode('utf-8', errors='ignore'))
        char_data = parse_v2_character_json(json_data)
        if char_data is None: return jsonify({'success': False, 'error': '无法解析JSON角色文件'})
        return apply_character(char_data)
    except: return jsonify({'success': False, 'error': 'JSON格式错误'})

@app.route('/api/upload_character_json', methods=['POST'])
def upload_character_json():
    data = request.json
    if not data: return jsonify({'success': False, 'error': '没有数据'})
    char_data = parse_v2_character_json(data)
    if char_data is None: return jsonify({'success': False, 'error': '无法解析JSON角色数据'})
    return apply_character(char_data)

@app.route('/api/character')
def get_character():
    if character_card:
        return jsonify({'loaded': True, 'character': { 'name': character_card['name'], 'description': character_card.get('description', '')[:500], 'first_mes': character_card.get('first_mes', '') }})
    return jsonify({'loaded': False})

def safe_filename(filename):
    filename = re.sub(r'[^\w\-.]', '_', filename)
    if not filename.endswith('.json'): filename += '.json'
    return os.path.basename(filename)

@app.route('/api/save_chat', methods=['POST'])
def save_chat():
    auto_save_current_chat()
    return jsonify({'success': True, 'filename': 'auto_saved'})

@app.route('/api/load_chat', methods=['POST'])
def load_chat():
    global chat_history, character_card, user_name, current_chat_id
    data = request.json
    if not data: return jsonify({'success': False})
    filename = safe_filename(data.get('filename', ''))
    filepath = os.path.join(chat_save_dir, filename)
    if not os.path.exists(filepath): return jsonify({'success': False})
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            save_data = json.load(f)
        chat_history = save_data.get('history', [])
        character_card = save_data.get('character')
        if character_card: server_status['character_name'] = character_card.get('name', '未命名')
        server_status['chat_count'] = save_data.get('chat_count', len(chat_history))
        default_llm_params.update(save_data.get('llm_params', {}))
        user_name = save_data.get('user_name', '用户')
        current_chat_id = save_data.get('chat_id')
        return jsonify({'success': True, 'character': character_card, 'history': chat_history, 'params': default_llm_params, 'user_name': user_name})
    except: return jsonify({'success': False})

@app.route('/api/list_chats')
def list_chats():
    chats = []
    if os.path.exists(chat_save_dir):
        for f in sorted(os.listdir(chat_save_dir), reverse=True):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(chat_save_dir, f), 'r', encoding='utf-8') as fp:
                        d = json.load(fp)
                    chats.append({
                        'filename': f,
                        'timestamp': d.get('timestamp', ''),
                        'character_name': d.get('character', {}).get('name', '无角色') if d.get('character') else '无角色',
                        'message_count': len(d.get('history', [])),
                    })
                except: pass
    return jsonify({'success': True, 'chats': chats})

@app.route('/api/delete_chat', methods=['POST'])
def delete_chat():
    data = request.json
    if not data: return jsonify({'success': False})
    filepath = os.path.join(chat_save_dir, safe_filename(data.get('filename', '')))
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({'success': True})
    return jsonify({'success': False})

@socketio.on('send_message')
def handle_message(data):
    global chat_history
    msg = data.get('message', '').strip()
    if not msg: return
    
    stop_event.clear()

    llm_params = {
        "max_context_tokens": data.get('max_context_tokens', default_llm_params['max_context_tokens']),
        "max_response_tokens": data.get('max_response_tokens', default_llm_params['max_response_tokens']),
        "temperature": data.get('temperature', default_llm_params['temperature']),
        "top_p": data.get('top_p', default_llm_params['top_p']),
        "top_k": data.get('top_k', default_llm_params['top_k']),
        "repeat_penalty": data.get('repeat_penalty', default_llm_params['repeat_penalty']),
        "model_type": data.get('model_type', default_llm_params.get('model_type', 'qwen')),
        "no_think": data.get('no_think', default_llm_params.get('no_think', True)),
    }
    default_llm_params.update(llm_params)

    chat_history.append({"role": "user", "content": msg})
    socketio.emit('stream_start', {'user_message': msg})

    char = character_card or {'name': '老酒', 'system_prompt': '你是一个人工智能助手。', 'first_mes': '你好。'}
    prompt, kept_count = build_prompt(chat_history, char, llm_params)
    api_url = server_status['api_url']
    full_reply = ""

    try:
        resp = requests.post(api_url, json={
            "prompt": prompt,
            "temperature": llm_params['temperature'],
            "top_p": llm_params['top_p'],
            "top_k": llm_params['top_k'],
            "n_predict": llm_params['max_response_tokens'],
            "repeat_penalty": llm_params['repeat_penalty'],
            "stream": True,
            "stop": ["<end_of_turn>", "<|im_end|>", "<|im_start|>"],
        }, timeout=300, stream=True)
        
        server_status['api_connected'] = True
        utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        head_buffer = ""
        head_checked = False

        for line_bytes in resp.iter_lines(decode_unicode=False):
            if stop_event.is_set(): break
            if not line_bytes: continue
            
            try: line = utf8_decoder.decode(line_bytes + b'\n')
            except: continue

            token = None
            if line.startswith('data: '):
                data_str = line[6:]
                if data_str.strip() == '[DONE]': break
                try:
                    chunk = json.loads(data_str)
                    token = chunk.get('content') or chunk.get('token') or chunk.get('text') or ''
                except: pass
            else:
                try:
                    chunk = json.loads(line)
                    token = chunk.get('content') or chunk.get('token') or chunk.get('text') or ''
                except: pass
     
            if token:
                full_reply += token
                if llm_params.get('no_think', True) and not head_checked:
                    head_buffer += token
                    if len(head_buffer) >= 25:
                        cleaned_head = re.sub(r'<[^>]*>', '', head_buffer)
                        cleaned_head = re.sub(r'^[\s\n/<>|thinkreasons]*', '', cleaned_head)
                        if cleaned_head:
                            socketio.emit('stream_token', {'token': cleaned_head.lstrip()})
                        head_checked = True
                else:
                    if not head_checked and llm_params.get('no_think', True):
                        socketio.emit('stream_token', {'token': token.lstrip()})
                        head_checked = True
                    else:
                        socketio.emit('stream_token', {'token': token})
                socketio.sleep(0)

        if llm_params.get('no_think', True) and not head_checked and head_buffer:
            cleaned_head = re.sub(r'<[^>]*>', '', head_buffer)
            cleaned_head = re.sub(r'^[\s\n/<>|thinkreasons]*', '', cleaned_head)
            if cleaned_head: socketio.emit('stream_token', {'token': cleaned_head.lstrip()})

    except Exception as e:
        full_reply = "(连接失败: {})".format(str(e))
        server_status['api_connected'] = False
        socketio.emit('stream_token', {'token': full_reply})

    full_reply = re.sub(r'/\*.*?\*/', '', full_reply, flags=re.DOTALL).strip()
    if llm_params.get('no_think', True):
        clean_history_reply = re.sub(r'<[^>]*>', '', full_reply)
        clean_history_reply = re.sub(r'^[\s\n/<>|thinkreasons]*', '', clean_history_reply).strip()
    else:
        clean_history_reply = full_reply

    if stop_event.is_set():
        clean_history_reply = "[已强行熔断中断]"

    if clean_history_reply and not clean_history_reply.startswith("(连接失败") and not stop_event.is_set():
        chat_history.append({"role": "assistant", "content": clean_history_reply})
    
    server_status['chat_count'] += 1
    auto_save_current_chat()

    socketio.emit('stream_end', {
        'full_reply': clean_history_reply,
        'context_info': { 'total_tokens': 0, 'max_tokens': llm_params['max_context_tokens'], 'usage_percent': 0, 'kept_messages': kept_count }
    })

@socketio.on('stop_generation')
def handle_stop_generation():
    stop_event.set()
    socketio.emit('stream_end', {'full_reply': '[已强行熔断中断]', 'context_info': {'total_tokens': 0, 'max_tokens': 65536, 'usage_percent': 0, 'kept_messages': 0}})

@socketio.on('clear_history')
def handle_clear_history():
    global chat_history, current_chat_id
    auto_save_current_chat()
    chat_history = []
    server_status['chat_count'] = 0
    current_chat_id = None
    if character_card and character_card.get('first_mes'):
        chat_history.append({"role": "assistant", "content": character_card['first_mes'].replace("{{user}}", user_name).replace("{{char}}", character_card.get('name', ''))})
    socketio.emit('history_cleared')

@socketio.on('update_params')
def handle_update_params(data):
    for k in default_llm_params:
        if k in data: default_llm_params[k] = data[k]
    socketio.emit('params_updated', default_llm_params)


# ========== PySide6 状态监控窗口 ==========
class StatusWindow(QWidget):
    def __init__(self, local_ip):
        super().__init__()
        self.local_ip = local_ip
        self.setWindowTitle("老酒馆控制台")
        self.setFixedSize(440, 340)
        self.setStyleSheet("background-color: #f8fafc;")
        self._init_ui()
        
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_status)
        self._timer.start(1000)
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(0)
        
        title = QLabel("🥃 老酒馆")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        title.setStyleSheet("color: #0f172a;")
        layout.addWidget(title)
        
        subtitle = QLabel("AI 角色服务 · 运行中")
        subtitle.setFont(QFont("Microsoft YaHei", 10))
        subtitle.setStyleSheet("color: #64748b;")
        layout.addWidget(subtitle)
        
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: #e2e8f0; max-height: 1px; margin: 12px 0;")
        layout.addWidget(sep1)
        
        self._api_label = QLabel("○ 后端 API: 未连接")
        self._api_label.setFont(QFont("Microsoft YaHei", 10))
        self._api_label.setStyleSheet("color: #ef4444; font-weight: bold; padding: 3px 0;")
        layout.addWidget(self._api_label)
        
        self._model_label = QLabel("模型: 正在读取...")
        self._model_label.setFont(QFont("Microsoft YaHei", 10))
        self._model_label.setStyleSheet("color: #1e293b; padding: 3px 0;")
        layout.addWidget(self._model_label)
        
        self._think_label = QLabel("思维拦截: 开启")
        self._think_label.setFont(QFont("Microsoft YaHei", 10))
        self._think_label.setStyleSheet("color: #10b981; font-weight: bold; padding: 3px 0;")
        layout.addWidget(self._think_label)
        
        self._char_label = QLabel("角色: 正在加载...")
        self._char_label.setFont(QFont("Microsoft YaHei", 10))
        self._char_label.setStyleSheet("color: #1e293b; padding: 3px 0;")
        layout.addWidget(self._char_label)
        
        self._chat_label = QLabel("对话轮数: 0 轮")
        self._chat_label.setFont(QFont("Microsoft YaHei", 10))
        self._chat_label.setStyleSheet("color: #1e293b; padding: 3px 0;")
        layout.addWidget(self._chat_label)
        
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background-color: #e2e8f0; max-height: 1px; margin: 10px 0;")
        layout.addWidget(sep2)
        
        url_text = f"局域网: http://{self.local_ip}:{SERVER_PORT}"
        self._url_label = QLabel(url_text)
        self._url_label.setFont(QFont("Microsoft YaHei", 10))
        self._url_label.setStyleSheet("color: #10b981; font-weight: bold; padding: 2px 0;")
        layout.addWidget(self._url_label)
        
        local_text = f"本机: http://127.0.0.1:{SERVER_PORT}"
        self._local_url_label = QLabel(local_text)
        self._local_url_label.setFont(QFont("Microsoft YaHei", 10))
        self._local_url_label.setStyleSheet("color: #10b981; font-weight: bold; padding: 2px 0;")
        layout.addWidget(self._local_url_label)
        
        layout.addSpacing(14)
        warn_label = QLabel("聊天中途请勿关闭此窗口")
        warn_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        warn_label.setStyleSheet("color: #dc2626;")
        layout.addWidget(warn_label)
    
    def _update_status(self):
        try:
            if server_status['api_connected']:
                self._api_label.setText("● 后端 API: 已连接")
                self._api_label.setStyleSheet("color: #10b981; font-weight: bold; padding: 3px 0;")
            else:
                self._api_label.setText("○ 后端 API: 未连接")
                self._api_label.setStyleSheet("color: #ef4444; font-weight: bold; padding: 3px 0;")
            
            names = {'qwen': '通义千问 (Qwen)', 'gemma': 'Gemma (谷歌)', 'llama': 'LLaMA (通用)'}
            model_name = names.get(default_llm_params.get('model_type', 'qwen'), default_llm_params.get('model_type', 'qwen'))
            self._model_label.setText(f"模型: {model_name}")
            
            if default_llm_params.get('no_think', True):
                self._think_label.setText("思维拦截: 开启 (拦截 <think>)")
                self._think_label.setStyleSheet("color: #10b981; font-weight: bold; padding: 3px 0;")
            else:
                self._think_label.setText("思维拦截: 关闭 (允许思考)")
                self._think_label.setStyleSheet("color: #ef4444; font-weight: bold; padding: 3px 0;")
            
            self._char_label.setText(f"角色: {server_status['character_name']}")
            self._chat_label.setText(f"对话轮数: {server_status['chat_count']} 轮")
        except:
            pass
    
    def closeEvent(self, event):
        auto_save_current_chat()
        event.accept()
        os._exit(0)


def start_flask():
    server_status['start_time'] = datetime.now().strftime('%H:%M:%S')
    print(f"🥃 老酒馆启动中...")
    print(f"   本机访问: http://127.0.0.1:{SERVER_PORT}")
    print(f"   局域网访问: http://{get_local_ip()}:{SERVER_PORT}")
    socketio.run(app, host='0.0.0.0', port=SERVER_PORT, debug=False, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    local_ip = get_local_ip()
    
    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1.5)
    
    webbrowser.open(f"http://127.0.0.1:{SERVER_PORT}")
    
    qt_app = QApplication(sys.argv)
    qt_app.setStyle('Fusion')
    window = StatusWindow(local_ip)
    window.show()
    sys.exit(qt_app.exec())