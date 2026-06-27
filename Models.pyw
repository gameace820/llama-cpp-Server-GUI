import sys
import os
import struct
import traceback
import re
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLineEdit, QLabel, QFileDialog, QTextEdit, QGroupBox,
                               QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

# GGUF 量化类型映射（常用）
GGUF_QUANT_TYPES = {
    0: "FP32", 1: "FP16", 2: "Q4_0", 3: "Q4_1", 4: "Q5_0", 
    5: "Q5_1", 6: "Q8_0", 7: "Q8_1", 8: "Q2_K", 9: "Q3_K_S", 
    10: "Q3_K_M", 11: "Q3_K_L", 12: "Q4_K_S", 13: "Q4_K_M", 
    14: "Q5_K_S", 15: "Q5_K_M", 16: "Q6_K", 17: "Q8_K"
}

def parse_gguf_metadata_lowmem(file_path):
    info = {
        "file_path": file_path,
        "file_size_bytes": 0,
        "file_size_human": "",
        "model_name": "未知",
        "architecture": "未知",
        "parameters": "未知",
        "quantization": "未知",
        "metadata": {}
    }
    f = None
    try:
        stat = os.stat(file_path)
        info["file_size_bytes"] = stat.st_size
        size = stat.st_size
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024 or unit == 'TB':
                info["file_size_human"] = f"{size:.2f} {unit}"
                break
            size /= 1024

        f = open(file_path, "rb", buffering=4096)
        magic = f.read(4)
        if magic not in (b"GGUF", b"GGUF\n"):
            info["model_name"] = "非 GGUF 文件"
            return info

        version = struct.unpack("<I", f.read(4))[0]
        tensor_count = struct.unpack("<Q", f.read(8))[0]
        metadata_count = struct.unpack("<Q", f.read(8))[0]

        def read_val(v_type):
            if v_type == 0: return struct.unpack("<B", f.read(1))[0]
            elif v_type == 1: return struct.unpack("<b", f.read(1))[0]
            elif v_type == 2: return struct.unpack("<H", f.read(2))[0]
            elif v_type == 3: return struct.unpack("<h", f.read(2))[0]
            elif v_type == 4: return struct.unpack("<I", f.read(4))[0]
            elif v_type == 5: return struct.unpack("<i", f.read(4))[0]
            elif v_type == 6: return struct.unpack("<f", f.read(4))[0]
            elif v_type == 7: return bool(struct.unpack("<B", f.read(1))[0])
            elif v_type == 8:
                s_len = struct.unpack("<Q", f.read(8))[0]
                return f.read(s_len).decode("utf-8", errors="replace")
            elif v_type == 9:
                a_type = struct.unpack("<I", f.read(4))[0]
                a_len = struct.unpack("<Q", f.read(8))[0]
                elem_bytes_map = {0:1, 1:1, 2:2, 3:2, 4:4, 5:4, 6:4, 7:1, 10:8, 11:8, 12:4, 13:4}
                if a_type in elem_bytes_map:
                    f.seek(a_len * elem_bytes_map[a_type], os.SEEK_CUR)
                else:
                    for _ in range(a_len):
                        read_val(a_type)
                return f"Array(type:{a_type}, len:{a_len})"
            elif v_type in (10, 11): return struct.unpack("<Q", f.read(8))[0]
            elif v_type in (12, 13): return struct.unpack("<I", f.read(4))[0]
            return None

        for _ in range(metadata_count):
            key_len = struct.unpack("<Q", f.read(8))[0]
            key = f.read(key_len).decode("utf-8", errors="replace")
            val_type = struct.unpack("<I", f.read(4))[0]
            val = read_val(val_type)
            info["metadata"][key] = val

        meta = info["metadata"]
        info["model_name"] = meta.get("general.name", meta.get("general.architecture", "未知模型"))

        arch = meta.get("general.architecture", "")
        if arch:
            info["architecture"] = arch
        else:
            name_lower = info["model_name"].lower()
            if "gemma" in name_lower: info["architecture"] = "Gemma"
            elif "llama" in name_lower: info["architecture"] = "Llama"
            elif "qwen" in name_lower: info["architecture"] = "Qwen"
            elif "mistral" in name_lower: info["architecture"] = "Mistral"

        size_label = meta.get("general.size_label", "")
        if size_label:
            info["parameters"] = size_label
        else:
            params = meta.get("general.parameters")
            if params:
                info["parameters"] = f"{params / 1e9:.1f}B"
            else:
                fn = os.path.basename(file_path)
                match = re.search(r'(\d+(?:\.\d+)?)B', fn)
                if match: info["parameters"] = f"{match.group(1)}B"

        quant_type = meta.get("general.quantization_version", meta.get("llama.quantization_version"))
        if quant_type in GGUF_QUANT_TYPES:
            info["quantization"] = GGUF_QUANT_TYPES[quant_type]
        else:
            fn_upper = os.path.basename(file_path).upper()
            found_quant = None
            for q in GGUF_QUANT_TYPES.values():
                if q in fn_upper:
                    found_quant = q
                    break
            if not found_quant and "general.tags" in meta and isinstance(meta["general.tags"], str):
                tags_str = meta["general.tags"].upper()
                for q in GGUF_QUANT_TYPES.values():
                    if q in tags_str:
                        found_quant = q
                        break
            if found_quant:
                info["quantization"] = found_quant

    except Exception as e:
        info["model_name"] = f"解析异常: {str(e)}"
        traceback.print_exc()
    finally:
        if f is not None: f.close()
        import gc
        gc.collect()
    return info

class GGUFInfoWindow(QMainWindow):
    def __init__(self, target_path=""):
        super().__init__()
        self.target_path = target_path
        self.all_metadata = {}  # 存放原始KV供搜索过滤
        
        self.setWindowTitle("🔍 GGUF 模型元数据高级看板")
        self.setMinimumSize(850, 500)
        self.init_ui()
        
        # 如果主界面通过传参过来了路径，直接秒级自动解析
        if self.target_path:
            self.load_model_data(self.target_path)

    def init_ui(self):
        # 极客暗黑与工业白相结合的高级主题配置
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI', 'Microsoft YaHei'; }
            QGroupBox { font-weight: bold; border: 1px solid #dcdcdc; border-radius: 6px; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #2980b9; }
            QLineEdit { padding: 4px; border: 1px solid #cccccc; border-radius: 4px; }
            QLineEdit:hover { border: 1px solid #1890ff; background-color: #f0f8ff; }
            QTableWidget { background-color: #ffffff; border: 1px solid #dcdcdc; gridline-color: #f0f0f0; }
            QHeaderView::section { background-color: #f2f2f2; font-weight: bold; border: 1px solid #dcdcdc; color: #333; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # 1. 顶部路径条
        file_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择 GGUF 模型文件...")
        self.path_edit.setReadOnly(True)
        browse_btn = QPushButton("📂 浏览 GGUF")
        browse_btn.setStyleSheet("QPushButton{font-weight:bold;} QPushButton:hover{background-color:#e6f7ff; color:#1890ff;}")
        browse_btn.clicked.connect(self.select_gguf)
        file_layout.addWidget(self.path_edit, 1)
        file_layout.addWidget(browse_btn)
        main_layout.addLayout(file_layout)

        # 2. 核心大排版：双栏左右分流布局
        content_layout = QHBoxLayout()
        
        # 【左侧栏】：卡片看板指标区
        left_panel = QVBoxLayout()
        basic_group = QGroupBox("📊 核心硬核指标")
        form_layout = QFormLayout(basic_group)
        form_layout.setSpacing(12)
        
        def create_bold_label(text="-", color="#333333"):
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl.setStyleSheet(f"color: {color};")
            return lbl

        self.label_model = create_bold_label("未选择模型", "#e67e22")
        self.label_arch = create_bold_label("-", "#2980b9")
        self.label_params = create_bold_label("-", "#27ae60")
        self.label_quant = create_bold_label("-", "#9b59b6")
        self.label_size = create_bold_label("-", "#7f8c8d")
        
        form_layout.addRow("模型名称：", self.label_model)
        form_layout.addRow("模型架构：", self.label_arch)
        form_layout.addRow("预估参数：", self.label_params)
        form_layout.addRow("量化级别：", self.label_quant)
        form_layout.addRow("文件大小：", self.label_size)
        
        left_panel.addWidget(basic_group)
        left_panel.addStretch()  # 让卡片居顶排列
        content_layout.addLayout(left_panel, 2) # 权重占 2
        
        # 【右侧栏】：完整 KV 键值对表，附带实时搜索过滤
        right_panel = QVBoxLayout()
        meta_group = QGroupBox("📋 完整底层 KV 键值对映射表")
        meta_box_layout = QVBoxLayout(meta_group)
        
        # 搜索过滤条
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 实时过滤筛选:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入 Key 或 Value 进行搜索...")
        self.search_edit.textChanged.connect(self.filter_metadata_table)
        search_layout.addWidget(self.search_edit, 1)
        meta_box_layout.addLayout(search_layout)
        
        # 键值对数据表格
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["键 (Key)", "值 (Value)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        meta_box_layout.addWidget(self.table)
        
        right_panel.addWidget(meta_group)
        content_layout.addLayout(right_panel, 3) # 权重占 3
        
        main_layout.addLayout(content_layout)

    def select_gguf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 GGUF 模型", "", "GGUF 模型 (*.gguf);;所有文件 (*.*)")
        if path:
            self.load_model_data(path)

    def load_model_data(self, path):
        try:
            self.path_edit.setText(path)
            info = parse_gguf_metadata_lowmem(path)
            
            # 刷新左侧指标看板
            self.label_model.setText(info["model_name"])
            self.label_arch.setText(info["architecture"])
            self.label_params.setText(info["parameters"])
            self.label_quant.setText(info["quantization"])
            self.label_size.setText(info["file_size_human"])
            
            # 留存完整字典供搜索
            self.all_metadata = info["metadata"]
            
            # 刷新右侧数据表格
            self.populate_table(self.all_metadata)
            
            import gc
            gc.collect()
        except Exception as e:
            print(f"数据装载故障: {e}")

    def populate_table(self, data_dict):
        self.table.setRowCount(0)
        sorted_keys = sorted(data_dict.keys())
        self.table.setRowCount(len(sorted_keys))
        
        for row, k in enumerate(sorted_keys):
            v = str(data_dict[k])
            item_k = QTableWidgetItem(k)
            item_v = QTableWidgetItem(v)
            
            # 给 key 染上高贵的天蓝色，让界面更灵动
            item_k.setForeground(QColor("#2980b9"))
            
            self.table.setItem(row, 0, item_k)
            self.table.setItem(row, 1, item_v)
            
        self.table.resizeColumnToContents(0)
        if self.table.columnWidth(0) > 350:
            self.table.setColumnWidth(0, 350) # 限宽防止撑爆

    def filter_metadata_table(self, text):
        """实时文本框过滤逻辑"""
        text = text.lower().strip()
        for row in range(self.table.rowCount()):
            k = self.table.item(row, 0).text().lower()
            v = self.table.item(row, 1).text().lower()
            if text in k or text in v:
                self.table.setRowHidden(row, False)
            else:
                self.table.setRowHidden(row, True)

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    # 接管外部进程传参
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    window = GGUFInfoWindow(path)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
