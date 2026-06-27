import sys
import json
import os
import subprocess
import webbrowser
import socket
import threading
from datetime import datetime
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

# 进程检测库
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ==================== 配置管理 ====================
class ConfigManager:
    CONFIG_FILE = "llamu_configs.json"
    LAST_SESSION_FILE = "last_session.json"
    TOTAL_PRESETS = 7
    
    @staticmethod
    def load_all():
        default = {f"config_{i}": {} for i in range(1, ConfigManager.TOTAL_PRESETS + 1)}
        if not os.path.exists(ConfigManager.CONFIG_FILE): return default
        try:
            with open(ConfigManager.CONFIG_FILE, 'r', encoding='utf-8') as f: 
                data = json.load(f)
                for i in range(1, ConfigManager.TOTAL_PRESETS + 1):
                    if f"config_{i}" not in data: data[f"config_{i}"] = {}
                return data
        except: return default
    
    @staticmethod
    def save_all(configs):
        with open(ConfigManager.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(configs, f, indent=2, ensure_ascii=False)

    @staticmethod
    def save_last_session(config):
        try:
            with open(ConfigManager.LAST_SESSION_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存会话失败: {e}")

    @staticmethod
    def load_last_session():
        if not os.path.exists(ConfigManager.LAST_SESSION_FILE):
            return None
        try:
            with open(ConfigManager.LAST_SESSION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("model"):
                    return data
        except:
            pass
        return None

# ==================== 高级参数配置 ====================
class AdvancedParams:
    PARAMS = [
        ("threads", "threads", "int", 8, {},
         "CPU 线程数，用于并行计算，越大推理越快（受物理核心数限制）"),
        ("threads_batch", "threads-batch", "int", 8, {},
         "批处理专用线程数，与 threads 分开设置可优化吞吐量"),
        ("gpu_layers", "gpu-layers", "int", 99, {},
         "将多少层模型加载到 GPU 显存，层数越多 GPU 占用越高但推理越快（99=全部）"),
        ("batch_size", "batch-size", "int", 512, {},
         "单次前向传播的批次大小，影响显存占用和吞吐量"),
        ("ubatch_size", "ubatch-size", "int", 512, {},
         "微批次大小，用于优化多 GPU 或流水线并行"),
        ("rope_scale", "rope-scale", "float", 1.0, {},
         "RoPE 缩放因子，用于扩展上下文长度（>1 可延长 ctx）"),
        ("rope_freq_base", "rope-freq-base", "float", 10000.0, {},
         "RoPE 频率基数，默认 10000，调整可改变位置编码分布"),
        ("rope_freq_scale", "rope-freq-scale", "float", 1.0, {},
         "RoPE 频率缩放，配合 rope_scale 使用"),
        ("temp", "temp", "float", 0.7, {},
         "温度参数，越高输出越随机，越低越确定性（0=贪婪）"),
        ("repeat_penalty", "repeat-penalty", "float", 1.1, {},
         "重复惩罚，>1 抑制重复生成，1.0=无惩罚"),
        ("frequency_penalty", "frequency-penalty", "float", 0.0, {},
         "频率惩罚，基于 token 出现频率降低重复概率"),
        ("presence_penalty", "presence-penalty", "float", 0.0, {},
         "存在惩罚，只要 token 出现过就降低其概率，鼓励新话题"),
        ("top_k", "top-k", "int", 40, {},
         "Top-K 采样，只从概率最高的 K 个 token 中选取，0=禁用"),
        ("top_p", "top-p", "float", 0.95, {},
         "Top-P（核采样），累积概率阈值，只从概率和达到 P 的 token 中选取"),
        ("min_p", "min-p", "float", 0.05, {},
         "最小概率阈值，低于此概率的 token 被过滤（相对于最高概率）"),
        ("seed", "seed", "int", -1, {},
         "随机种子，-1=随机，固定种子可复现结果"),
        ("fa", "fa", "choice", "off", {"choices": ["on", "off"]},
         "Flash Attention 加速（需 GPU 支持），开启后大幅提升推理速度"),
        ("memory_f32", "memory-f32", "choice", "off", {"choices": ["on", "off"]},
         "以 FP32 精度存储 KV Cache（更精确但占显存更大）"),
        ("embedding", "embedding", "choice", "off", {"choices": ["on", "off"]},
         "启用 Embedding 模式（向量嵌入），用于 RAG 或语义搜索"),
        ("cache_type_k", "cache-type-k", "choice", "f16", {"choices": ["f16", "q8_0", "q4_0"]},
         "K Cache 量化类型，f16=高精度，q8_0/q4_0=低精度省显存"),
        ("cache_type_v", "cache-type-v", "choice", "f16", {"choices": ["f16", "q8_0", "q4_0"]},
         "V Cache 量化类型，f16=高精度，q8_0/q4_0=低精度省显存"),
        ("model_alias", "model-alias", "str", "", {},
         "模型别名，用于日志和 API 标识"),
        ("no_mmap", "no-mmap", "flag", False, {},
         "禁用内存映射（mmap），模型加载更慢但可能更稳定"),
        ("mlock", "mlock", "flag", False, {},
         "锁定模型到物理内存，防止被交换到虚拟内存（需管理员权限）"),
        ("numa", "numa", "flag", False, {},
         "启用 NUMA 感知内存分配，多 CPU 插槽服务器优化"),
        ("verbose", "verbose", "flag", False, {},
         "输出详细日志（调试用），会显示更多内部信息"),
        ("json_response", "json-response", "flag", False, {},
         "API 响应以 JSON 格式输出（便于程序化调用）"),
        ("metrics", "metrics", "flag", False, {},
         "启用指标统计，输出 token/s 等 performance 数据"),
    ]

# ==================== 工作线程 ====================
class ServerSignals(QObject):
    output = Signal(str)
    finished = Signal(int)
    error = Signal(str)
    server_ready = Signal(str)

class ServerWorker(QThread):
    def __init__(self, command, host, port):
        super().__init__()
        self.command = command
        self.host = host
        self.port = port
        self.process = None
        self.signals = ServerSignals()
        self._is_running = False

    def run(self):
        try:
            creationflags = 0x08000000 if sys.platform == "win32" else 0
            self.process = subprocess.Popen(
                self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=creationflags, encoding='utf-8', errors='replace'
            )
            self._is_running = True
            ready_detected = False
            for line in iter(self.process.stdout.readline, ''):
                if not self._is_running: break
                if line:
                    line = line.strip()
                    self.signals.output.emit(line)
                    if not ready_detected and "server is listening on" in line.lower():
                        ready_detected = True
                        host_for_browser = "127.0.0.1" if self.host == "0.0.0.0" else self.host
                        self.signals.server_ready.emit(f"http://{host_for_browser}:{self.port}")
            if self.process:
                self.process.wait()
                self.signals.finished.emit(self.process.returncode)
        except Exception as e: self.signals.error.emit(str(e))
        finally: self._is_running = False

# ==================== 全盘搜索线程 ====================
class SearchSignals(QObject):
    found = Signal(str)
    not_found = Signal()
    progress = Signal(str)

class SearchWorker(QThread):
    def __init__(self):
        super().__init__()
        self.signals = SearchSignals()
        self._stop_flag = False
    
    def stop(self):
        self._stop_flag = True

    def run(self):
        self._stop_flag = False
        # Windows 下获取所有盘符
        drives = []
        for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ':
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
        
        # 要跳过的目录（加速搜索）
        skip_dirs = {
            'Windows', 'Program Files', 'Program Files (x86)', 
            'ProgramData', '$Recycle.Bin', 'System Volume Information',
            'Recovery', 'MSOCache', 'PerfLogs', 'Intel',
            'NVIDIA', 'AMD', 'node_modules', '.git', '__pycache__',
            'venv', '.venv', 'env', '.env', 'AppData',
        }
        
        for drive in drives:
            if self._stop_flag:
                return
            try:
                self.signals.progress.emit(f"正在搜索 {drive} ...")
                for root, dirs, files in os.walk(drive):
                    if self._stop_flag:
                        return
                    # 跳过系统目录
                    dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.') and not d.startswith('$')]
                    if 'llama-server.exe' in files:
                        found_path = os.path.join(root, 'llama-server.exe')
                        self.signals.found.emit(found_path)
                        return
            except (PermissionError, OSError):
                continue
        
        self.signals.not_found.emit()

# ==================== 帮助对话框 ====================
class HelpDialog(QDialog):
    def __init__(self, is_zh=True, parent=None):
        super().__init__(parent)
        self.is_zh = is_zh
        self.setMinimumSize(540, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.init_ui()

    def init_ui(self):
        if self.is_zh:
            self.setWindowTitle("❓ 帮助与关于")
        else:
            self.setWindowTitle("❓ Help & About")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel("🦙 Llama Server GUI")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #2980b9;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        version_lbl = QLabel("Version 1.0.0")
        version_lbl.setAlignment(Qt.AlignCenter)
        version_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(version_lbl)
        
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: #dcdde1; max-height: 1px;")
        layout.addWidget(sep)
        
        if self.is_zh:
            desc_text = (
                "本程序是 llama.cpp 的图形化启动器，\n"
                "用于在本地运行大语言模型。\n\n"
                "📌 主要功能：\n"
                "  • 管理多个模型配置方案（7 个预设槽位）\n"
                "  • 支持 GGUF 格式模型、多模态 (mmproj)、\n"
                "    MTP 加速、LoRA 挂载\n"
                "  • 启动 / 停止 llama-server 服务进程\n"
                "  • 提供局域网联机服务（手机 / 平板可连接）\n"
                "  • 可外挂「本地微型酒馆」（支持 V2 角色卡导入）\n"
                "  • 可外挂 HardwareMonitor 监控内存状态\n\n"
                "📋 运行环境要求：\n"
                "  • Python 3.8 或更高版本\n"
                "  • PySide6 — GUI 框架（必需）\n"
                "    pip install PySide6\n"
                "  • psutil — 进程检测（可选，推荐安装）\n"
                "    pip install psutil\n\n"
                "🔧 一键安装依赖：\n"
                "  pip install PySide6 psutil\n\n"
                "📖 使用步骤：\n"
                "  1. 点击「🔍 定位」自动搜索 llama-server.exe\n"
                "     或手动将其与本程序放在同一目录\n"
                "  2. 选择 GGUF 模型文件\n"
                "  3. 配置上下文大小、端口等核心参数\n"
                "  4. 点击「启动」加载模型\n"
                "  5. 服务就绪后，点击「CHAT」外挂微型酒馆\n"
                "     或使用浏览器访问服务地址\n"
                "  6. 点击「停止」结束服务\n\n"
                "💡 提示：\n"
                "  • 「📱 跨设备联机向导」可获取局域网连接地址\n"
                "    - 浏览器直接访问: http://IP:8080\n"
                "    - 酒馆 OpenAI 格式: http://IP:8080/v1\n"
                "  • HardwareMonitor 为外挂程序，用于可视化\n"
                "    确认服务进程是否已完全退出"
            )
        else:
            desc_text = (
                "A GUI launcher for llama.cpp,\n"
                "used to run large language models locally.\n\n"
                "📌 Main Features:\n"
                "  • Manage multiple model configs (7 presets)\n"
                "  • Support GGUF, multimodal (mmproj),\n"
                "    MTP spec, LoRA mounting\n"
                "  • Start / Stop llama-server process\n"
                "  • LAN service for mobile/tablet connection\n"
                "  • External micro-SillyTavern (V2 card support)\n"
                "  • External HardwareMonitor for memory status\n\n"
                "📋 Requirements:\n"
                "  • Python 3.8 or higher\n"
                "  • PySide6 — GUI framework (required)\n"
                "    pip install PySide6\n"
                "  • psutil — Process detection (optional, recommended)\n"
                "    pip install psutil\n\n"
                "🔧 One-click install:\n"
                "  pip install PySide6 psutil\n\n"
                "📖 Usage:\n"
                "  1. Click '🔍 Locate' to auto-search llama-server.exe\n"
                "     or place it in the same directory as this program\n"
                "  2. Select a GGUF model file\n"
                "  3. Configure context size, port, etc.\n"
                "  4. Click 'Start' to load the model\n"
                "  5. When ready, click 'CHAT' for micro-SillyTavern\n"
                "     or access via browser\n"
                "  6. Click 'Stop' to stop the server\n\n"
                "💡 Tips:\n"
                "  • '📱 Mobile LAN Guide' shows LAN addresses:\n"
                "    - Browser direct: http://IP:8080\n"
                "    - SillyTavern OpenAI: http://IP:8080/v1\n"
                "  • HardwareMonitor is an external tool to visually\n"
                "    confirm the server process has fully exited"
            )
        
        desc_label = QLabel(desc_text)
        desc_label.setWordWrap(True)
        desc_label.setFont(QFont("Segoe UI", 10))
        desc_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                padding: 12px;
                color: #333333;
            }
        """)
        layout.addWidget(desc_label)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        close_btn = QPushButton("关闭" if self.is_zh else "Close")
        close_btn.setFixedHeight(34)
        close_btn.setFixedWidth(100)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #1890ff;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 6px 24px;
            }
            QPushButton:hover {
                background-color: #40a9ff;
            }
        """)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

# ==================== 日志窗口 ====================
class LogWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(550, 400)
        self.setWindowFlags(Qt.Window) 
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.log_output = QTextEdit()
        self.log_output.setFont(QFont("Consolas", 10))
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self.log_output)
        
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("💾 保存日志")
        self.save_btn.clicked.connect(self.save_log)
        btn_layout.addWidget(self.save_btn)
        
        self.clear_btn = QPushButton("🗑️ 清空日志")
        self.clear_btn.clicked.connect(self.log_output.clear)
        btn_layout.addWidget(self.clear_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def append_log(self, message):
        self.log_output.append(message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def save_log(self):
        log_content = self.log_output.toPlainText()
        if not log_content.strip(): return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Log", f"llamu_log_{timestamp}.txt", "Text Files (*.txt)")
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f: f.write(log_content)

    def retranslate_ui(self, is_zh):
        if is_zh:
            self.setWindowTitle("📋 系统日志输出")
            self.save_btn.setText("💾 保存日志")
            self.clear_btn.setText("🗑️ 清空日志")
        else:
            self.setWindowTitle("📋 System Log Stream")
            self.save_btn.setText("💾 Save Log")
            self.clear_btn.setText("🗑️ Clear Log")

# ==================== 高级参数窗口 ====================
class AdvancedWindow(QWidget):
    def __init__(self, advanced_widgets, is_zh=True, parent=None):
        super().__init__(parent)
        self.advanced_widgets = advanced_widgets
        self.is_zh = is_zh
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(700, 600)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("⚙️ 参数配置" if self.is_zh else "⚙️ Advanced Parameters")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        title = QLabel("⚙️ 参数配置" if self.is_zh else "⚙️ Advanced Parameters")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #2980b9;")
        layout.addWidget(title)
        
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: #dcdde1; max-height: 1px;")
        layout.addWidget(sep)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        
        content = QWidget()
        grid = QGridLayout(content)
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        row, col = 0, 0
        for key, display, ptype, default, opts, tip_zh in AdvancedParams.PARAMS:
            if ptype == "flag":
                cb = QCheckBox(display)
                cb.setToolTip(tip_zh)
                grid.addWidget(cb, row, col, 1, 2)
                if key in self.advanced_widgets:
                    cb.setChecked(self.advanced_widgets[key]["cb"].isChecked())
                    cb.toggled.connect(lambda checked, k=key: self.advanced_widgets[k]["cb"].setChecked(checked))
                    self.advanced_widgets[key]["cb"] = cb
                col += 2
                if col >= 4:
                    col = 0
                    row += 1
                continue

            cb = QCheckBox(display)
            cb.setToolTip(tip_zh)
            grid.addWidget(cb, row, col)

            if ptype == "int":
                spin = QSpinBox()
                spin.setRange(-1, 999999)
                spin.setValue(default)
                spin.setEnabled(False)
                cb.toggled.connect(spin.setEnabled)
                grid.addWidget(spin, row, col + 1)
                if key in self.advanced_widgets:
                    cb.setChecked(self.advanced_widgets[key]["cb"].isChecked())
                    spin.setValue(self.advanced_widgets[key]["value"].value())
                    cb.toggled.connect(lambda checked, k=key: self.advanced_widgets[k]["cb"].setChecked(checked))
                    spin.valueChanged.connect(lambda val, k=key: self.advanced_widgets[k]["value"].setValue(val))
                    self.advanced_widgets[key] = {"cb": cb, "value": spin, "type": ptype}
            elif ptype == "float":
                spin = QDoubleSpinBox()
                spin.setRange(-1.0, 999999.0)
                spin.setSingleStep(0.05)
                spin.setValue(default)
                spin.setEnabled(False)
                cb.toggled.connect(spin.setEnabled)
                grid.addWidget(spin, row, col + 1)
                if key in self.advanced_widgets:
                    cb.setChecked(self.advanced_widgets[key]["cb"].isChecked())
                    spin.setValue(self.advanced_widgets[key]["value"].value())
                    cb.toggled.connect(lambda checked, k=key: self.advanced_widgets[k]["cb"].setChecked(checked))
                    spin.valueChanged.connect(lambda val, k=key: self.advanced_widgets[k]["value"].setValue(val))
                    self.advanced_widgets[key] = {"cb": cb, "value": spin, "type": ptype}
            elif ptype == "choice":
                combo = QComboBox()
                combo.addItems(opts.get("choices", ["on", "off"]))
                combo.setCurrentText(default)
                combo.setEnabled(False)
                cb.toggled.connect(combo.setEnabled)
                grid.addWidget(combo, row, col + 1)
                if key in self.advanced_widgets:
                    cb.setChecked(self.advanced_widgets[key]["cb"].isChecked())
                    combo.setCurrentText(self.advanced_widgets[key]["value"].currentText())
                    cb.toggled.connect(lambda checked, k=key: self.advanced_widgets[k]["cb"].setChecked(checked))
                    combo.currentTextChanged.connect(lambda val, k=key: self.advanced_widgets[k]["value"].setCurrentText(val))
                    self.advanced_widgets[key] = {"cb": cb, "value": combo, "type": ptype}
            elif ptype == "str":
                edit = QLineEdit()
                edit.setText(default)
                edit.setEnabled(False)
                cb.toggled.connect(edit.setEnabled)
                grid.addWidget(edit, row, col + 1)
                if key in self.advanced_widgets:
                    cb.setChecked(self.advanced_widgets[key]["cb"].isChecked())
                    edit.setText(self.advanced_widgets[key]["value"].text())
                    cb.toggled.connect(lambda checked, k=key: self.advanced_widgets[k]["cb"].setChecked(checked))
                    edit.textChanged.connect(lambda val, k=key: self.advanced_widgets[k]["value"].setText(val))
                    self.advanced_widgets[key] = {"cb": cb, "value": edit, "type": ptype}

            col += 2
            if col >= 4:
                col = 0
                row += 1

        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭" if self.is_zh else "Close")
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #1890ff;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 6px 24px;
            }
            QPushButton:hover {
                background-color: #40a9ff;
            }
        """)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

# ==================== 流光按钮类 ====================
class GlowButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._phase = 0.0
        self._glow_active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_phase)
        self._timer.start(30)
        self._base_color = QColor("#8e44ad")

    def set_glow_active(self, active):
        self._glow_active = active
        if not active:
            self._phase = 0.0
        self.update()

    def _update_phase(self):
        if self._glow_active:
            self._phase = (self._phase + 0.02) % 1.0
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 4, 4)
        painter.setClipPath(path)

        if not self._glow_active:
            painter.fillRect(rect, QColor("#333333"))
            painter.setPen(QColor("#888888"))
        else:
            base_gradient = QLinearGradient(0, 0, 0, rect.height())
            base_gradient.setColorAt(0.0, self._base_color.darker(110))
            base_gradient.setColorAt(1.0, self._base_color)
            painter.fillRect(rect, base_gradient)

            glow_width = rect.width() * 0.3
            x_start = self._phase * (rect.width() + glow_width) - glow_width
            glow_gradient = QLinearGradient(x_start, 0, x_start + glow_width, 0)
            glow_gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            glow_gradient.setColorAt(0.5, QColor(255, 255, 255, 80))
            glow_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(rect, glow_gradient)
            painter.setPen(Qt.white)

        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignCenter, self.text())
        painter.end()

# ==================== 跨设备API向导面板（修正版） ====================
class ApiGuideDialog(QDialog):
    def __init__(self, current_port, is_zh=True, parent=None):
        super().__init__(parent)
        self.port = current_port
        self.is_zh = is_zh
        self.init_ui()
        
    def get_real_local_ip(self):
        try:
            hostname = socket.gethostname()
            ip_list = socket.gethostbyname_ex(hostname)[2]
            for ip in ip_list:
                if ip.startswith("192.168.") or ip.startswith("10."):
                    if not ip.startswith("10.0.0.") and not ip.startswith("192.168.56."): return ip
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("192.168.1.1", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            try:
                for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                    if not ip.startswith("127."): return ip
            except: pass
            return "127.0.0.1"

    def init_ui(self):
        self.setMinimumSize(500, 340)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        
        local_ip = self.get_real_local_ip()
        direct_url = f"http://{local_ip}:{self.port}"
        openai_url = f"http://{local_ip}:{self.port}/v1"
        
        if self.is_zh:
            self.setWindowTitle("🛠️ 跨设备移动端联机向导")
            title_text = "📱 局域网多机联机服务"
            title_tip = "请确保手机/平板与本电脑连接在 **同一个 Wi-Fi** 下"
            
            direct_label = "🌐 浏览器直接访问（llama 原生界面）："
            direct_tip = "在手机浏览器输入此地址即可打开 llama.cpp 自带聊天界面"
            
            openai_label = "🍺 酒馆 OpenAI 格式（SillyTavern 用）："
            openai_tip = "在酒馆中选择 OpenAI API，填写此地址即可连接"
            
            copy_direct_txt = "📋 复制浏览器地址"
            copy_openai_txt = "📋 复制酒馆地址"
            close_txt = "知道了"
        else:
            self.setWindowTitle("🛠️ Cross-Device Connection Guide")
            title_text = "📱 LAN Multi-Device Service"
            title_tip = "Make sure phone/tablet is on the **SAME Wi-Fi** as this PC"
            
            direct_label = "🌐 Browser Direct (llama native UI):"
            direct_tip = "Open this URL in mobile browser for llama.cpp built-in chat"
            
            openai_label = "🍺 SillyTavern OpenAI Format:"
            openai_tip = "In SillyTavern, select OpenAI API and use this address"
            
            copy_direct_txt = "📋 Copy Browser URL"
            copy_openai_txt = "📋 Copy Tavern URL"
            close_txt = "Got it"

        title_lbl = QLabel(title_text)
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title_lbl.setStyleSheet("color: #2980b9;")
        layout.addWidget(title_lbl)
        
        tip_lbl = QLabel(title_tip)
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(tip_lbl)
        
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: #dcdde1; max-height: 1px;")
        layout.addWidget(sep)
        
        # 浏览器直接访问
        layout.addWidget(QLabel(direct_label))
        
        self.direct_url_edit = QLineEdit(direct_url)
        self.direct_url_edit.setFont(QFont("Consolas", 11, QFont.Bold))
        self.direct_url_edit.setReadOnly(True)
        self.direct_url_edit.setStyleSheet(
            "background-color: #f4f6f7; color: #2980b9; padding: 6px; "
            "border: 1px solid #bdc3c7; border-radius: 4px;"
        )
        self.direct_url_edit.setToolTip(direct_tip)
        layout.addWidget(self.direct_url_edit)
        
        btn_direct_layout = QHBoxLayout()
        btn_direct_layout.addStretch()
        copy_direct_btn = QPushButton(copy_direct_txt)
        copy_direct_btn.setFixedHeight(30)
        copy_direct_btn.clicked.connect(lambda: QApplication.clipboard().setText(direct_url))
        btn_direct_layout.addWidget(copy_direct_btn)
        layout.addLayout(btn_direct_layout)
        
        # 酒馆 OpenAI 格式
        layout.addSpacing(4)
        layout.addWidget(QLabel(openai_label))
        
        self.openai_url_edit = QLineEdit(openai_url)
        self.openai_url_edit.setFont(QFont("Consolas", 11, QFont.Bold))
        self.openai_url_edit.setReadOnly(True)
        self.openai_url_edit.setStyleSheet(
            "background-color: #f4f6f7; color: #e74c3c; padding: 6px; "
            "border: 1px solid #bdc3c7; border-radius: 4px;"
        )
        self.openai_url_edit.setToolTip(openai_tip)
        layout.addWidget(self.openai_url_edit)
        
        btn_openai_layout = QHBoxLayout()
        btn_openai_layout.addStretch()
        copy_openai_btn = QPushButton(copy_openai_txt)
        copy_openai_btn.setFixedHeight(30)
        copy_openai_btn.clicked.connect(lambda: QApplication.clipboard().setText(openai_url))
        btn_openai_layout.addWidget(copy_openai_btn)
        layout.addLayout(btn_openai_layout)
        
        layout.addSpacing(6)
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton(close_txt)
        close_btn.setFixedHeight(34)
        close_btn.setFixedWidth(120)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #1890ff;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #40a9ff;
            }
        """)
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        close_layout.addStretch()
        layout.addLayout(close_layout)

# ==================== 主窗口 ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.search_worker = None
        self.active_index = 1
        self.advanced_widgets = {}
        self.is_disconnecting = False  
        self.ball_process = None  
        self.server_url = ""  
        self.is_zh = True  
        self.external_server_pid = None
        self.saved_server_path = ""  # 固化的 llama-server.exe 路径
        
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.handle_button_blink)
        self.blink_state = False

        self.log_window = LogWindow()
        self.advanced_window = None
        self.help_dialog = None
        
        # 加载固化的 server 路径
        self.load_server_path()
        
        self.init_ui()
        self.retranslate_ui()
        self.refresh_advanced_tooltips() 
        
        last_session = ConfigManager.load_last_session()
        if last_session and last_session.get("model"):
            self.apply_config(last_session)
        else:
            self.switch_preset_slot(1)
        self.refresh_preset_buttons()
        
        self.reset_to_initial_ui()
        QTimer.singleShot(100, self.detect_existing_server)

    def load_server_path(self):
        """加载固化的 llama-server.exe 路径"""
        config_path = "llamu_server_path.json"
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.saved_server_path = data.get("server_path", "")
            except:
                self.saved_server_path = ""
    
    def save_server_path(self, path):
        """固化 llama-server.exe 路径"""
        self.saved_server_path = path
        config_path = "llamu_server_path.json"
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump({"server_path": path}, f, indent=2)
        except:
            pass

    def init_ui(self):
        self.setMinimumSize(880, 350) 
        self.statusBar().show()
        
        try:
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setFont(QFont("Segoe UI Emoji", 20))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "🦙")
            painter.end()
            self.setWindowIcon(QIcon(pixmap))
        except: pass
        
        self.setStyleSheet("""
            QGroupBox { font-weight: bold; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #2980b9; }
            QPushButton { padding: 6px 15px; }
            QLineEdit { padding: 3px; border: 1px solid #cccccc; border-radius: 3px; }
            QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border: 1px solid #1890ff; background-color: #f0f8ff; }
            QCheckBox:hover { color: #1890ff; }
            QToolTip { background-color: white; color: #0066cc; border: 1px solid #0066cc; font-size: 12px; padding: 6px; border-radius: 4px; }
        """)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)

        # ===== 顶层布局（预设按钮 + 语言切换） =====
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addStretch()
        
        preset_spacing = 6
        
        self.preset_buttons = []
        for i in range(1, 8):
            btn = QPushButton(f"{i}")
            btn.setFixedWidth(40)
            btn.setFixedHeight(34)
            btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
            btn.clicked.connect(lambda checked, idx=i: self.switch_preset_slot(idx))
            top_bar_layout.addWidget(btn)
            self.preset_buttons.append(btn)
            
        top_bar_layout.addSpacing(preset_spacing)
        
        self.save_preset_btn = QPushButton("💾 保存")
        self.save_preset_btn.setObjectName("preset_save_btn")
        self.save_preset_btn.setFixedHeight(34)
        self.save_preset_btn.clicked.connect(self.save_current_preset)
        self.save_preset_btn.setStyleSheet("""
            QPushButton#preset_save_btn {
                background-color: #ffffff; color: #333333; border: 1px solid #cccccc; border-radius: 4px; font-weight: bold;
            }
            QPushButton#preset_save_btn:hover {
                background-color: #f5eef8; border: 1px solid #8e44ad; color: #8e44ad;
            }
        """)
        top_bar_layout.addWidget(self.save_preset_btn)
        
        top_bar_layout.addSpacing(preset_spacing)
        
        self.clear_preset_btn = QPushButton("🗑️ 清空")
        self.clear_preset_btn.setObjectName("preset_clear_btn")
        self.clear_preset_btn.setFixedHeight(34)
        self.clear_preset_btn.clicked.connect(self.clear_current_preset)
        self.clear_preset_btn.setStyleSheet("""
            QPushButton#preset_clear_btn {
                background-color: #ffffff; color: #333333; border: 1px solid #cccccc; border-radius: 4px; font-weight: bold;
            }
            QPushButton#preset_clear_btn:hover {
                background-color: #f5eef8; border: 1px solid #8e44ad; color: #8e44ad;
            }
        """)
        top_bar_layout.addWidget(self.clear_preset_btn)
        
        top_bar_layout.addStretch()
        
        # 语言按钮
        lang_wrapper = QWidget()
        lang_wrapper.setFixedHeight(34)
        lang_wrapper_layout = QVBoxLayout(lang_wrapper)
        lang_wrapper_layout.setContentsMargins(0, 0, 12, 0)
        lang_wrapper_layout.setSpacing(0)
        
        self.lang_btn = QPushButton("🇺🇸")
        self.lang_btn.setFont(QFont("Segoe UI Emoji", 18, QFont.Bold))
        self.lang_btn.setStyleSheet("""
            QPushButton { 
                background-color: transparent; 
                border: none; 
                padding: 0px 8px;
            } 
            QPushButton:hover { 
                background-color: transparent;
            }
        """)
        self.lang_btn.setFixedHeight(34)
        self.lang_btn.clicked.connect(self.toggle_language)
        lang_wrapper_layout.addStretch()
        lang_wrapper_layout.addWidget(self.lang_btn)
        lang_wrapper_layout.addStretch()
        
        top_bar_layout.addWidget(lang_wrapper)
        main_layout.addLayout(top_bar_layout)

        # ===== 模型文件组 =====
        self.model_group = QGroupBox("模型文件")
        model_layout = QVBoxLayout()
        
        main_model_layout = QHBoxLayout()
        self.main_model_wrapper = QWidget()
        self.main_model_wrapper.setFixedWidth(150)
        wrapper_layout = QHBoxLayout(self.main_model_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_main_model = QLabel("主模型 (GGUF):")
        wrapper_layout.addWidget(self.lbl_main_model)
        main_model_layout.addWidget(self.main_model_wrapper)
        
        self.open_dir_btn = QPushButton("目录")
        self.open_dir_btn.setObjectName("open_dir_btn")
        self.open_dir_btn.setEnabled(False)
        self.open_dir_btn.clicked.connect(self.open_current_model_directory)
        main_model_layout.addWidget(self.open_dir_btn)
        main_model_layout.addSpacing(6)
        
        self.model_info_btn = QPushButton("信息")
        self.model_info_btn.setObjectName("model_info_btn")
        self.model_info_btn.setEnabled(False)
        self.model_info_btn.clicked.connect(self.open_independent_model_viewer)
        main_model_layout.addWidget(self.model_info_btn)
        main_model_layout.addSpacing(6)
        
        self.model_path = QLineEdit()
        self.model_path.setPlaceholderText("GGUF模型文件路径...")
        self.model_path.textChanged.connect(lambda text: self.refresh_model_related_buttons())
        main_model_layout.addWidget(self.model_path, 1)
        self.browse_btn = QPushButton("📂 浏览")
        self.browse_btn.setObjectName("browse_btn")
        self.browse_btn.setFixedWidth(100)
        self.browse_btn.setFixedHeight(34)
        self.browse_btn.clicked.connect(lambda: self.browse_file(self.model_path, "Model", "*.gguf"))
        main_model_layout.addWidget(self.browse_btn)
        model_layout.addLayout(main_model_layout)
        
        mm_layout = QHBoxLayout()
        self.mmproj_check = QCheckBox("启用多模态 (mmproj)")
        self.mmproj_check.setFixedWidth(150)
        self.mmproj_check.toggled.connect(lambda checked: self.mmproj_path.setEnabled(checked))
        mm_layout.addWidget(self.mmproj_check)
        self.mmproj_path = QLineEdit()
        self.mmproj_path.setPlaceholderText("mmproj 文件路径...")
        self.mmproj_path.setEnabled(False)
        self.mmproj_path.textChanged.connect(lambda text: self.update_single_btn_color(self.mmproj_browse_btn, text))
        mm_layout.addWidget(self.mmproj_path, 1)
        self.mmproj_browse_btn = QPushButton("📂 浏览")
        self.mmproj_browse_btn.setObjectName("mmproj_browse_btn")
        self.mmproj_browse_btn.setFixedWidth(100)
        self.mmproj_browse_btn.clicked.connect(lambda: self.browse_file(self.mmproj_path, "mmproj", "*.gguf;;*.*"))
        mm_layout.addWidget(self.mmproj_browse_btn)
        model_layout.addLayout(mm_layout)
        
        mtp_layout = QHBoxLayout()
        self.mtp_check = QCheckBox("启用 MTP 加速")
        self.mtp_check.setFixedWidth(150)
        self.mtp_check.toggled.connect(lambda checked: self.mtp_path.setEnabled(checked))
        mtp_layout.addWidget(self.mtp_check)
        self.mtp_path = QLineEdit()
        self.mtp_path.setPlaceholderText("MTP 草稿模型路径...")
        self.mtp_path.setEnabled(False)
        self.mtp_path.textChanged.connect(lambda text: self.update_single_btn_color(self.mtp_browse_btn, text))
        mtp_layout.addWidget(self.mtp_path, 1)
        self.mtp_browse_btn = QPushButton("📂 浏览")
        self.mtp_browse_btn.setObjectName("mtp_browse_btn")
        self.mtp_browse_btn.setFixedWidth(100)
        self.mtp_browse_btn.clicked.connect(lambda: self.browse_file(self.mtp_path, "MTP", "*.safetensors;;*.gguf"))
        mtp_layout.addWidget(self.mtp_browse_btn)
        model_layout.addLayout(mtp_layout)

        lora_layout = QHBoxLayout()
        self.lora_check = QCheckBox("启用 LoRA 挂载")
        self.lora_check.setFixedWidth(150)
        self.lora_check.toggled.connect(lambda checked: self.lora_path.setEnabled(checked))
        lora_layout.addWidget(self.lora_check)
        self.lora_path = QLineEdit()
        self.lora_path.setPlaceholderText("LoRA 权重文件 (.bin / .gguf)...")
        self.lora_path.setEnabled(False)
        self.lora_path.textChanged.connect(lambda text: self.update_single_btn_color(self.lora_browse_btn, text))
        lora_layout.addWidget(self.lora_path, 1)
        self.lora_browse_btn = QPushButton("📂 浏览")
        self.lora_browse_btn.setObjectName("lora_browse_btn")
        self.lora_browse_btn.setFixedWidth(100)
        self.lora_browse_btn.clicked.connect(lambda: self.browse_file(self.lora_path, "LoRA", "*.bin;;*.gguf;;*.*"))
        lora_layout.addWidget(self.lora_browse_btn)
        model_layout.addLayout(lora_layout)
        
        self.model_group.setLayout(model_layout)
        main_layout.addWidget(self.model_group)

        # ===== 核心参数组 =====
        self.core_group = QGroupBox("核心参数")
        core_layout = QHBoxLayout()
        core_layout.addWidget(QLabel("ctx-size:"))
        self.ctx_size = QLineEdit("40960")
        self.ctx_size.setFixedWidth(80)
        core_layout.addWidget(self.ctx_size)
        
        core_layout.addSpacing(5)
        core_layout.addWidget(QLabel("host:"))
        self.host = QLineEdit("0.0.0.0")
        self.host.setFixedWidth(100)
        core_layout.addWidget(self.host)
        
        core_layout.addSpacing(5)
        core_layout.addWidget(QLabel("port:"))
        self.port = QLineEdit("8080")
        self.port.setFixedWidth(60)
        core_layout.addWidget(self.port)
        
        core_layout.addStretch()
        
        # 定位 llama-server 按钮
        self.locate_btn = QPushButton("🔍 定位 llama-server")
        self.locate_btn.setStyleSheet("""
            QPushButton { 
                background-color: #fff3e0; border: 1px solid #ff9800; border-radius: 4px; font-weight: bold; color: #e65100; padding: 6px 12px;
            } 
            QPushButton:hover { 
                background-color: #ffe0b2; border: 1px solid #f57c00; color: #bf360c; 
            }
        """)
        self.locate_btn.setToolTip("自动搜索全盘定位 llama-server.exe" if self.is_zh else "Auto-search entire disk for llama-server.exe")
        self.locate_btn.clicked.connect(self.locate_llama_server)
        core_layout.addWidget(self.locate_btn)
        
        # 帮助按钮
        self.help_btn = QPushButton("❓ 帮助")
        self.help_btn.setStyleSheet("""
            QPushButton { 
                background-color: #f3f3f3; border: 1px solid #c8c8c8; border-radius: 4px; font-weight: bold; color: #2c3e50; padding: 6px 12px;
            } 
            QPushButton:hover { 
                background-color: #e8f0fe; border: 1px solid #1890ff; color: #1890ff; 
            }
        """)
        self.help_btn.clicked.connect(self.open_help_dialog)
        core_layout.addWidget(self.help_btn)
        
        # 联机向导按钮
        self.api_guide_btn = QPushButton("📱 跨设备联机向导")
        self.api_guide_btn.setStyleSheet("""
            QPushButton { 
                background-color: #f3f3f3; border: 1px solid #c8c8c8; border-radius: 4px; font-weight: bold; color: #2c3e50; padding: 6px 12px;
            } 
            QPushButton:hover { 
                background-color: #e8f8f5; border: 1px solid #16a085; color: #16a085; 
            }
        """)
        self.api_guide_btn.clicked.connect(self.open_api_guide_panel)
        core_layout.addWidget(self.api_guide_btn)
        
        self.core_group.setLayout(core_layout)
        main_layout.addWidget(self.core_group)

        # ===== 控制区按钮 =====
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)
        ctrl_layout.setContentsMargins(0, 5, 0, 0)
        
        self.advanced_btn = QPushButton("⚙️ 参数")
        self.advanced_btn.setFixedHeight(36)
        self.advanced_btn.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
                padding: 0px 10px;
            }
            QPushButton:hover {
                background-color: #a569bd;
            }
        """)
        self.advanced_btn.clicked.connect(self.open_advanced_window)
        ctrl_layout.addWidget(self.advanced_btn, 1)
        
        self.ctrl_btn = QPushButton("启动")
        self.ctrl_btn.setFixedHeight(36)
        self.ctrl_btn.clicked.connect(self.on_ctrl_click)
        ctrl_layout.addWidget(self.ctrl_btn, 1)
        
        self.web_btn = QPushButton("LLAMA")
        self.web_btn.setEnabled(False)
        self.web_btn.setFixedHeight(36)
        self.web_btn.setStyleSheet("QPushButton { font-weight: bold; color: #888888; background-color: #333333; font-size: 14px; border-radius: 4px; border: none; }")
        self.web_btn.clicked.connect(self.open_llama_web)
        ctrl_layout.addWidget(self.web_btn, 1)

        self.chat_btn = GlowButton("CHAT")
        self.chat_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.chat_btn.setFixedHeight(36)
        self.chat_btn.setEnabled(False)
        self.chat_btn.setStyleSheet("""
            QPushButton { 
                font-weight: bold; color: #888888; font-size: 14px; border-radius: 4px; border: none; 
            }
            QPushButton:disabled {
                color: #888888;
            }
        """)
        self.chat_btn.clicked.connect(self.open_chat)
        ctrl_layout.addWidget(self.chat_btn, 1)
        
        self.show_log_btn = QPushButton("📋 日志")
        self.show_log_btn.setFixedHeight(36)
        self.show_log_btn.setStyleSheet("""
            QPushButton { 
                font-weight: bold; color: white; background-color: #1890ff; font-size: 13px; border-radius: 4px; border: none; 
                padding: 0px 10px;
            } 
            QPushButton:hover { background-color: #40a9ff; }
        """)
        self.show_log_btn.clicked.connect(self.toggle_log_window)
        ctrl_layout.addWidget(self.show_log_btn, 1)
        
        main_layout.addLayout(ctrl_layout)

    # ==================== 定位 llama-server ====================
    def locate_llama_server(self):
        """自动搜索全盘 llama-server.exe"""
        # 先检查同目录
        local_path = os.path.join(os.getcwd(), "llama-server.exe")
        if os.path.exists(local_path):
            self.save_server_path(local_path)
            self.log(f"✅ 在同目录找到 llama-server.exe: {local_path}" if self.is_zh else f"✅ Found llama-server.exe in current directory: {local_path}")
            self.statusBar().showMessage("✅ 已定位 llama-server.exe（同目录）" if self.is_zh else "✅ Found llama-server.exe (same directory)", 3000)
            return
        
        # 检查已固化路径
        if self.saved_server_path and os.path.exists(self.saved_server_path):
            self.log(f"✅ 使用已固化路径: {self.saved_server_path}")
            self.statusBar().showMessage("✅ llama-server.exe 路径已就绪" if self.is_zh else "✅ llama-server.exe path ready", 2000)
            return
        
        # 开始全盘搜索
        self.locate_btn.setEnabled(False)
        self.locate_btn.setText("⏳ 搜索中..." if self.is_zh else "⏳ Searching...")
        self.statusBar().showMessage("🔍 正在全盘搜索 llama-server.exe..." if self.is_zh else "🔍 Searching entire disk for llama-server.exe...")
        
        self.search_worker = SearchWorker()
        self.search_worker.signals.found.connect(self.on_server_found)
        self.search_worker.signals.not_found.connect(self.on_server_not_found)
        self.search_worker.signals.progress.connect(lambda msg: self.statusBar().showMessage(msg, 0))
        self.search_worker.start()
        
        # 5 秒超时
        QTimer.singleShot(5000, self.check_search_timeout)
    
    def check_search_timeout(self):
        """检查搜索是否超时"""
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.stop()
            self.search_worker.wait(1000)
            self.on_server_not_found()
    
    def on_server_found(self, path):
        """找到 llama-server.exe"""
        self.locate_btn.setEnabled(True)
        self.locate_btn.setText("🔍 定位 llama-server")
        self.save_server_path(path)
        self.log(f"✅ 找到 llama-server.exe: {path}")
        self.statusBar().showMessage(f"✅ 已定位: {path}" if self.is_zh else f"✅ Found: {path}", 5000)
        QMessageBox.information(self, 
            "✅ 找到" if self.is_zh else "✅ Found",
            f"已定位 llama-server.exe:\n{path}" if self.is_zh else f"Found llama-server.exe:\n{path}"
        )
    
    def on_server_not_found(self):
        """未找到 llama-server.exe"""
        self.locate_btn.setEnabled(True)
        self.locate_btn.setText("🔍 定位 llama-server")
        
        # 弹窗让用户手动选择
        result = QMessageBox.question(self,
            "⚠️ 未找到" if self.is_zh else "⚠️ Not Found",
            "全盘搜索未找到 llama-server.exe，是否手动选择？" if self.is_zh else "llama-server.exe not found. Select it manually?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if result == QMessageBox.Yes:
            file_path, _ = QFileDialog.getOpenFileName(
                self, 
                "选择 llama-server.exe" if self.is_zh else "Select llama-server.exe",
                "", 
                "llama-server.exe (llama-server.exe);;All Files (*.*)"
            )
            if file_path:
                self.save_server_path(file_path)
                self.log(f"✅ 手动选择 llama-server.exe: {file_path}")
                self.statusBar().showMessage("✅ 已设置 llama-server.exe 路径" if self.is_zh else "✅ llama-server.exe path set", 3000)
            else:
                self.statusBar().showMessage("⚠️ 未设置 llama-server.exe 路径" if self.is_zh else "⚠️ llama-server.exe path not set", 3000)
        else:
            self.statusBar().showMessage("⚠️ 未找到 llama-server.exe，请手动设置" if self.is_zh else "⚠️ llama-server.exe not found, please set manually", 3000)

    # ==================== 其他方法 ====================
    def open_help_dialog(self):
        if self.help_dialog is None or not self.help_dialog.isVisible():
            self.help_dialog = HelpDialog(self.is_zh, self)
            self.help_dialog.show()
        else:
            self.help_dialog.raise_()
            self.help_dialog.activateWindow()

    def detect_existing_server(self):
        if not PSUTIL_AVAILABLE:
            self.log("⚠️ psutil 未安装，无法自动检测后台服务 (pip install psutil)")
            return
        target_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and target_name.lower() in proc.info['name'].lower():
                    self.external_server_pid = proc.info['pid']
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if self.external_server_pid:
            self.log(f"🔍 检测到已有 llama-server 进程 (PID: {self.external_server_pid})，界面恢复为运行状态。")
            host = self.host.text().strip() or "0.0.0.0"
            port = self.port.text().strip() or "8080"
            url_host = "127.0.0.1" if host == "0.0.0.0" else host
            self.server_url = f"http://{url_host}:{port}"
            self.ctrl_btn.setEnabled(True)
            self.ctrl_btn.setText("停止" if self.is_zh else "Stop")
            self.ctrl_btn.setStyleSheet("QPushButton { font-weight: bold; color: white; background-color: #27ae60; font-size: 14px; height: 34px; border-radius: 4px; border: none; } QPushButton:hover { background-color: #2ecc71; } QPushButton:pressed { background-color: #1e8449; }")
            self.web_btn.setEnabled(True)
            self.chat_btn.setEnabled(True)
            self.chat_btn.set_glow_active(True)
            self.blink_timer.start(400)
            self.statusBar().showMessage(f"🔥 已连接至现有 Llama 服务: {self.server_url}" if self.is_zh else f"🔥 Connected to existing server: {self.server_url}")

    def open_advanced_window(self):
        if self.advanced_window is None or not self.advanced_window.isVisible():
            self.advanced_window = AdvancedWindow(self.advanced_widgets, self.is_zh, self)
            self.advanced_window.show()
        else:
            self.advanced_window.raise_()
            self.advanced_window.activateWindow()
    
    def refresh_all_browse_buttons(self):
        self.update_single_btn_color(self.browse_btn, self.model_path.text())
        self.update_single_btn_color(self.mmproj_browse_btn, self.mmproj_path.text())
        self.update_single_btn_color(self.mtp_browse_btn, self.mtp_path.text())
        self.update_single_btn_color(self.lora_browse_btn, self.lora_path.text())
        self.refresh_model_related_buttons()

    def refresh_model_related_buttons(self):
        text = self.model_path.text()
        model_exists = bool(text.strip() and os.path.exists(text.strip()))
        
        self.update_single_btn_color(self.browse_btn, text)
        
        if model_exists:
            self.open_dir_btn.setEnabled(True)
            self.model_info_btn.setEnabled(True)
            self.open_dir_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e67e22; color: white; font-weight: bold; border-radius: 4px; border: 1px solid #d35400;
                }
                QPushButton:hover {
                    background-color: #f39c12; border: 1px solid #e67e22;
                }
                QPushButton:disabled {
                    background-color: #e67e22; color: white;
                }
            """)
            self.model_info_btn.setStyleSheet("""
                QPushButton {
                    background-color: #16a085; color: white; font-weight: bold; border-radius: 4px; border: 1px solid #117a65;
                }
                QPushButton:hover {
                    background-color: #1abc9c; border: 1px solid #1abc9c;
                }
                QPushButton:disabled {
                    background-color: #16a085; color: white;
                }
            """)
        else:
            self.open_dir_btn.setEnabled(False)
            self.model_info_btn.setEnabled(False)
            self.open_dir_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f3f3f3; color: #999999; border: 1px solid #cccccc; border-radius: 4px; font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #f3f3f3; color: #999999;
                }
                QPushButton:disabled {
                    background-color: #f3f3f3; color: #999999;
                }
            """)
            self.model_info_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f3f3f3; border: 1px solid #cccccc; border-radius: 4px; font-weight: bold; color: #999999;
                }
                QPushButton:hover {
                    background-color: #f3f3f3; color: #999999;
                }
                QPushButton:disabled {
                    background-color: #f3f3f3; color: #999999;
                }
            """)

    def update_single_btn_color(self, button_widget, text):
        if text.strip() and os.path.exists(text.strip()):
            button_widget.setStyleSheet("""
                QPushButton {
                    background-color: #16a085; color: white; font-weight: bold; border-radius: 4px; border: 1px solid #16a085;
                }
                QPushButton:hover {
                    background-color: #1abc9c; border: 1px solid #1abc9c;
                }
            """)
        else:
            button_widget.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff; color: #333333; border: 1px solid #cccccc; border-radius: 4px; font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #e6f7ff; border: 1px solid #1890ff; color: #1890ff;
                }
            """)

    def open_chat(self):
        host = self.host.text().strip() or "127.0.0.1"
        port = self.port.text().strip() or "8080"
        if os.path.exists("chat.exe"): subprocess.Popen([os.path.abspath("chat.exe"), host, port])
        elif os.path.exists("chat.pyw"): subprocess.Popen([sys.executable, "chat.pyw", host, port])
        else: self.statusBar().showMessage("找不到 chat.exe 或 chat.pyw" if self.is_zh else "Cannot find chat.exe or chat.pyw", 3000)

    def open_current_model_directory(self):
        model_file = self.model_path.text().strip()
        if model_file and os.path.exists(model_file):
            if sys.platform == "win32": subprocess.Popen(f'explorer /select,"{os.path.abspath(model_file)}"', shell=True)
            else: webbrowser.open(os.path.dirname(os.path.abspath(model_file)))
        else:
            if sys.platform == "win32": os.startfile(os.getcwd())
            else: webbrowser.open(os.getcwd())

    def toggle_language(self):
        self.is_zh = not self.is_zh
        self.retranslate_ui()
        self.refresh_advanced_tooltips()

    def refresh_advanced_tooltips(self):
        for key, display, ptype, default, opts, tip_zh in AdvancedParams.PARAMS:
            if key in self.advanced_widgets:
                w = self.advanced_widgets[key]
                w["cb"].setToolTip(tip_zh)
                if "value" in w:
                    w["value"].setToolTip(tip_zh)

    def retranslate_ui(self):
        self.lang_btn.setText("🇺🇸" if self.is_zh else "🇨🇳")
        self.lang_btn.setToolTip("Switch to English" if self.is_zh else "切换至中文")

        if self.is_zh:
            self.setWindowTitle("🦙 Llama Server GUI")
            self.save_preset_btn.setText("💾 保存")
            self.clear_preset_btn.setText("🗑️ 清空")
            self.open_dir_btn.setText("目录")
            self.model_group.setTitle("模型文件")
            self.lbl_main_model.setText("主模型 (GGUF):")
            self.model_info_btn.setText("信息")
            self.mmproj_check.setText("启用多模态 (mmproj)")
            self.mtp_check.setText("启用 MTP 加速")
            self.lora_check.setText("启用 LoRA 挂载")
            self.core_group.setTitle("核心参数")
            self.locate_btn.setText("🔍 定位 llama-server")
            self.locate_btn.setToolTip("自动搜索全盘定位 llama-server.exe")
            self.help_btn.setText("❓ 帮助")
            self.api_guide_btn.setText("📱 跨设备联机向导")
            self.advanced_btn.setToolTip("高级参数配置")
            if self.worker is not None or self.external_server_pid is not None:
                self.ctrl_btn.setText("停止")
            else:
                self.ctrl_btn.setText("启动")
            
            self.model_path.setPlaceholderText("GGUF模型文件路径...")
            self.mmproj_path.setPlaceholderText("mmproj 文件路径...")
            self.mtp_path.setPlaceholderText("MTP 草稿模型路径...")
            self.lora_path.setPlaceholderText("LoRA 权重文件 (.bin / .gguf)...")
            self.browse_btn.setText("📂 浏览")
            self.mmproj_browse_btn.setText("📂 浏览")
            self.mtp_browse_btn.setText("📂 浏览")
            self.lora_browse_btn.setText("📂 浏览")
            self.log_window.retranslate_ui(True)
        else:
            self.setWindowTitle("🦙 Llama Server GUI")
            self.save_preset_btn.setText("💾 Save")
            self.clear_preset_btn.setText("🗑️ Clear")
            self.open_dir_btn.setText("Dir")
            self.model_group.setTitle("Model Files")
            self.lbl_main_model.setText("Main GGUF:")
            self.model_info_btn.setText("INFO")
            self.mmproj_check.setText("Enable Multimodal")
            self.mtp_check.setText("Enable MTP Spec")
            self.lora_check.setText("Enable LoRA Mount")
            self.core_group.setTitle("Core Settings")
            self.locate_btn.setText("🔍 Locate llama-server")
            self.locate_btn.setToolTip("Auto-search entire disk for llama-server.exe")
            self.help_btn.setText("❓ Help")
            self.api_guide_btn.setText("📱 Mobile LAN Guide")
            self.advanced_btn.setToolTip("Advanced Parameters")
            if self.worker is not None or self.external_server_pid is not None:
                self.ctrl_btn.setText("Stop")
            else:
                self.ctrl_btn.setText("Start")
            
            self.model_path.setPlaceholderText("GGUF model file path...")
            self.mmproj_path.setPlaceholderText("mmproj file path...")
            self.mtp_path.setPlaceholderText("MTP draft model path...")
            self.lora_path.setPlaceholderText("LoRA weight file (.bin / .gguf)...")
            self.browse_btn.setText("📂 Browse")
            self.mmproj_browse_btn.setText("📂 Browse")
            self.mtp_browse_btn.setText("📂 Browse")
            self.lora_browse_btn.setText("📂 Browse")
            self.log_window.retranslate_ui(False)

    def open_api_guide_panel(self):
        port_str = self.port.text().strip() or "8080"
        ApiGuideDialog(port_str, is_zh=self.is_zh, parent=self).exec()

    def refresh_preset_buttons(self):
        all_configs = ConfigManager.load_all()
        for i in range(1, 8):
            btn = self.preset_buttons[i - 1]
            has_data = bool(all_configs.get(f"config_{i}", {}).get("model"))
            if i == self.active_index:
                btn.setStyleSheet("""
                    QPushButton { 
                        background-color: #16a085; color: white; border: 1px solid #117a65; border-radius: 4px; font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #1abc9c; border: 1px solid #1abc9c;
                    }
                """)
            elif has_data:
                btn.setStyleSheet("""
                    QPushButton { 
                        background-color: #1890ff; color: white; border: 1px solid #1890ff; border-radius: 4px; font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #40a9ff; border: 1px solid #40a9ff;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton { 
                        background-color: #ffffff; color: #333333; border: 1px solid #cccccc; border-radius: 4px; font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #e6f7ff; border: 1px solid #1890ff; color: #1890ff;
                    }
                """)

    def switch_preset_slot(self, idx):
        self.active_index = idx
        self.apply_config(ConfigManager.load_all().get(f"config_{idx}", {}))
        self.refresh_preset_buttons()

    def save_current_preset(self):
        all_configs = ConfigManager.load_all()
        all_configs[f"config_{self.active_index}"] = self.get_current_config()
        ConfigManager.save_all(all_configs)
        self.refresh_preset_buttons()
        self.statusBar().showMessage(f"💾 方案 {self.active_index} 已保存" if self.is_zh else f"💾 Preset {self.active_index} saved", 2000)

    def clear_current_preset(self):
        msg = f"清空方案 {self.active_index}？" if self.is_zh else f"Clear preset {self.active_index}?"
        if QMessageBox.question(self, "确认" if self.is_zh else "Confirm", msg, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            all_configs = ConfigManager.load_all()
            all_configs[f"config_{self.active_index}"] = {}
            ConfigManager.save_all(all_configs)
            self.apply_config({})
            self.refresh_preset_buttons()

    def get_current_config(self):
        return {
            "model": self.model_path.text(), "mmproj_enabled": self.mmproj_check.isChecked(), "mmproj": self.mmproj_path.text(),
            "mtp_enabled": self.mtp_check.isChecked(), "mtp": self.mtp_path.text(), "lora_enabled": self.lora_check.isChecked(), "lora": self.lora_path.text(),
            "ctx_size": self.ctx_size.text(), "host": self.host.text(), "port": self.port.text(),
            "advanced": {
                k: (v["cb"].isChecked() if v["type"] == "flag" else v["value"].value() if v["type"] in ["int", "float"] else v["value"].currentText() if v["type"] == "choice" else v["value"].text()) 
                if v["cb"].isChecked() else None 
                for k, v in self.advanced_widgets.items()
            }
        }

    def apply_config(self, config):
        if not config or not config.get("model"):
            self.model_path.clear(); self.mmproj_check.setChecked(False); self.mmproj_path.clear()
            self.mtp_check.setChecked(False); self.mtp_path.clear(); self.lora_check.setChecked(False); self.lora_path.clear()
            self.ctx_size.setText("40960"); self.host.setText("0.0.0.0"); self.port.setText("8080")
            for w in self.advanced_widgets.values(): w["cb"].setChecked(False)
        else:
            self.model_path.setText(config.get("model", "")); self.mmproj_check.setChecked(config.get("mmproj_enabled", False)); self.mmproj_path.setText(config.get("mmproj", ""))
            self.mtp_check.setChecked(config.get("mtp_enabled", False)); self.mtp_path.setText(config.get("mtp", "")); self.lora_check.setChecked(config.get("lora_enabled", False)); self.lora_path.setText(config.get("lora", ""))
            self.ctx_size.setText(config.get("ctx_size", "40960")); self.host.setText(config.get("host", "0.0.0.0")); self.port.setText(config.get("port", "8080"))
            advanced = config.get("advanced", {})
            for key, w in self.advanced_widgets.items():
                if key in advanced and advanced[key] is not None:
                    w["cb"].setChecked(True)
                    if w["type"] == "flag":
                        continue
                    elif w["type"] in ["int", "float"]: w["value"].setValue(advanced[key])
                    elif w["type"] == "choice": w["value"].setCurrentText(advanced[key])
                    elif w["type"] in ["str", "file"]: w["value"].setText(advanced[key])
                else: w["cb"].setChecked(False)
        
        self.refresh_all_browse_buttons()

    def build_command(self):
        model = self.model_path.text().strip()
        if not model or not os.path.exists(model): return None
        server_exe = self.find_server_exe()
        if not server_exe or not os.path.exists(server_exe): return None
        cmd = [server_exe, "-m", model]
        if self.mmproj_check.isChecked(): cmd.extend(["--mmproj", self.mmproj_path.text().strip()])
        if self.mtp_check.isChecked(): cmd.extend(["--model-draft", self.mtp_path.text().strip(), "--spec-type", "draft-mtp"])
        if self.lora_check.isChecked(): cmd.extend(["--lora", self.lora_path.text().strip()])
        
        for key, w in self.advanced_widgets.items():
            if w["cb"].isChecked():
                param_name = next(p[1] for p in AdvancedParams.PARAMS if p[0] == key)
                ptype = w["type"]
                if ptype == "flag": cmd.append(f"--{param_name}")
                elif ptype in ["int", "float"]: cmd.extend([f"--{param_name}", str(w["value"].value())])
                elif ptype == "choice": cmd.extend([f"--{param_name}", w["value"].currentText()])
                elif ptype == "str" and w["value"].text().strip(): cmd.extend([f"--{param_name}", w["value"].text().strip()])
                
        cmd.extend(["-c", self.ctx_size.text().strip() or "40960", "--host", self.host.text().strip() or "0.0.0.0", "--port", self.port.text().strip() or "8080"])
        return cmd

    def find_server_exe(self):
        # 1. 优先使用固化的路径
        if self.saved_server_path and os.path.exists(self.saved_server_path):
            return self.saved_server_path
        # 2. 同目录
        local_path = os.path.join(os.getcwd(), "llama-server.exe")
        if os.path.exists(local_path):
            return local_path
        # 3. 只返回文件名（让系统在 PATH 里找）
        return "llama-server.exe"

    def open_independent_model_viewer(self):
        m = self.model_path.text().strip()
        if not m or not os.path.exists(m): return
        if os.path.exists("models.exe"): subprocess.Popen([os.path.abspath("models.exe"), m])
        elif os.path.exists("models.pyw"): subprocess.Popen([sys.executable, "models.pyw", m])

    def on_ctrl_click(self):
        if self.ctrl_btn.text() in ["加载中...", "Loading..."]:
            return
        if self.external_server_pid:
            self.stop_external_server()
            return
        if self.ctrl_btn.text() in ["启动", "Start"]: self.start_server()
        else: self.stop_server()

    def start_server(self):
        cmd = self.build_command()
        if not cmd:
            self.statusBar().showMessage("❌ 错误：模型文件不存在或未找到 llama-server.exe" if self.is_zh else "❌ Error: Model file not found or llama-server.exe missing", 3000)
            return
        self.is_disconnecting = False 
        self.ctrl_btn.setText("加载中..." if self.is_zh else "Loading...")
        self.ctrl_btn.setStyleSheet("QPushButton { font-weight: bold; color: white; background-color: #d35400; font-size: 14px; height: 34px; border-radius: 4px; border: none; } QPushButton:hover { background-color: #e67e22; } QPushButton:pressed { background-color: #a04000; }")
        self.ctrl_btn.setEnabled(False)
        self.statusBar().showMessage("⏳ 正在加载模型中，请稍候... / Loading model..." if self.is_zh else "⏳ Loading model, please wait...")
        self.worker = ServerWorker(cmd, self.host.text().strip(), self.port.text().strip())
        self.worker.signals.output.connect(self.log)
        self.worker.signals.finished.connect(self.server_finished)
        self.worker.signals.error.connect(self.on_server_error)
        self.worker.signals.server_ready.connect(self.on_server_ready) 
        self.worker.start()

    def on_server_error(self, error_msg):
        self.log(f"❌ 服务器错误: {error_msg}")
        self.statusBar().showMessage(f"❌ 启动失败: {error_msg}" if self.is_zh else f"❌ Startup failed: {error_msg}", 5000)
        self.server_finished(-1)

    def on_server_ready(self, url):
        self.server_url = url
        self.ctrl_btn.setEnabled(True)
        self.ctrl_btn.setText("停止" if self.is_zh else "Stop")
        self.ctrl_btn.setStyleSheet("QPushButton { font-weight: bold; color: white; background-color: #27ae60; font-size: 14px; height: 34px; border-radius: 4px; border: none; } QPushButton:hover { background-color: #2ecc71; } QPushButton:pressed { background-color: #1e8449; }")
        self.web_btn.setEnabled(True)
        self.chat_btn.setEnabled(True)
        self.chat_btn.setStyleSheet("""
            QPushButton { 
                font-weight: bold; color: white; font-size: 14px; height: 34px; border-radius: 4px; border: none; 
            }
        """)
        self.chat_btn.set_glow_active(True)
        self.blink_timer.start(400)
        self.statusBar().showMessage(f"🔥 Llama 服务已成功运行！地址: {url}" if self.is_zh else f"🔥 Server running at: {url}")
        if self.ball_process is None:
            try: 
                if os.path.exists("HardwareMonitor.exe"): self.ball_process = subprocess.Popen([os.path.abspath("HardwareMonitor.exe")])
                else: self.ball_process = subprocess.Popen([sys.executable, "HardwareMonitor.pyw"])
            except: pass

    def open_llama_web(self):
        if self.server_url: webbrowser.open(self.server_url)

    def stop_server(self):
        self.is_disconnecting = True  
        self.chat_btn.set_glow_active(False)
        self.chat_btn.setEnabled(False)
        self.chat_btn.setStyleSheet("""
            QPushButton { 
                font-weight: bold; color: #888888; font-size: 14px; height: 34px; border-radius: 4px; border: none; 
            }
        """)
        if self.ball_process: QTimer.singleShot(8000, self.delayed_kill_ball)
        if self.worker and self.worker.process:
            try: self.worker._is_running = False; self.worker.process.terminate()
            except: pass
        self.reset_to_initial_ui()
        self.statusBar().showMessage("🛑 服务已停止 / Server stopped" if self.is_zh else "🛑 Server stopped")

    def stop_external_server(self):
        if self.external_server_pid:
            try:
                proc = psutil.Process(self.external_server_pid)
                proc.terminate()
                self.log(f"🛑 已终止外部 llama-server 进程 (PID: {self.external_server_pid})" if self.is_zh else f"🛑 Terminated external llama-server process (PID: {self.external_server_pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                self.log(f"⚠️ 无法终止进程: {e}" if self.is_zh else f"⚠️ Cannot terminate process: {e}")
            finally:
                self.external_server_pid = None
        self.chat_btn.set_glow_active(False)
        self.chat_btn.setEnabled(False)
        self.chat_btn.setStyleSheet("""
            QPushButton { 
                font-weight: bold; color: #888888; font-size: 14px; height: 34px; border-radius: 4px; border: none; 
            }
        """)
        if self.ball_process: QTimer.singleShot(8000, self.delayed_kill_ball)
        self.reset_to_initial_ui()
        self.statusBar().showMessage("🛑 服务已停止 / Server stopped" if self.is_zh else "🛑 Server stopped")

    def delayed_kill_ball(self):
        if self.ball_process:
            try: self.ball_process.terminate()
            except: pass
            self.ball_process = None

    def server_finished(self, exit_code):
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        self.chat_btn.set_glow_active(False)
        self.chat_btn.setEnabled(False)
        self.chat_btn.setStyleSheet("""
            QPushButton { 
                font-weight: bold; color: #888888; font-size: 14px; height: 34px; border-radius: 4px; border: none; 
            }
        """)
        self.reset_to_initial_ui()

    def handle_button_blink(self):
        if self.blink_state: self.web_btn.setStyleSheet("QPushButton { font-weight: bold; color: white; background-color: #007acc; font-size: 14px; height: 34px; border-radius: 4px; }")
        else: self.web_btn.setStyleSheet("QPushButton { font-weight: bold; color: white; background-color: #00bfff; font-size: 14px; height: 34px; border-radius: 4px; }")
        self.blink_state = not self.blink_state

    def browse_file(self, line_edit, title, filter_str):
        file_path, _ = QFileDialog.getOpenFileName(self, title, "", filter_str)
        if file_path: line_edit.setText(file_path)

    def log(self, message):
        if self.log_window: self.log_window.append_log(message)

    def toggle_log_window(self):
        if self.log_window.isHidden(): self.log_window.show()
        else: self.log_window.activateWindow(); self.log_window.raise_()

    def closeEvent(self, event):
        ConfigManager.save_last_session(self.get_current_config())
        self.log_window.close()
        if self.advanced_window:
            self.advanced_window.close()
        if self.help_dialog:
            self.help_dialog.close()
        if self.worker and self.worker.isRunning():
            self.stop_server()
        elif self.external_server_pid:
            self.stop_external_server()
        super().closeEvent(event)

    def reset_to_initial_ui(self):
        self.blink_timer.stop()
        self.chat_btn.set_glow_active(False)
        self.chat_btn.setEnabled(False)
        self.chat_btn.setStyleSheet("""
            QPushButton { 
                font-weight: bold; color: #888888; font-size: 14px; height: 34px; border-radius: 4px; border: none; 
            }
        """)
        self.ctrl_btn.setEnabled(True)
        self.ctrl_btn.setText("启动" if self.is_zh else "Start")
        self.ctrl_btn.setStyleSheet("""
            QPushButton { font-weight: bold; color: white; background-color: #1890ff; font-size: 14px; height: 34px; border-radius: 4px; border: none; } 
            QPushButton:hover { background-color: #40a9ff; }
            QPushButton:pressed { background-color: #096dd9; }
        """)
        self.web_btn.setEnabled(False)
        self.web_btn.setStyleSheet("QPushButton { font-weight: bold; color: #888888; background-color: #333333; font-size: 14px; height: 34px; border-radius: 4px; }")
        self.statusBar().showMessage("🟢 系统就绪 / System Ready" if self.is_zh else "🟢 System Ready")

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__": main()
