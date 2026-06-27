#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
import re
import math
import psutil

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar, QMenu
)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QAction
)

# ---------- 方形监控悬浮窗 ----------
class MonitorPanel(QWidget):
    def __init__(self, ball_ref=None):
        super().__init__()
        self.ball_ref = ball_ref
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedSize(320, 240)
        self.setStyleSheet("background-color: #1e1e1e; border-radius: 8px;")

        self.drag_pos = QPoint()
        self.gpu_data = None

        self.init_ui()

        self.data_timer = QTimer(self)
        self.data_timer.timeout.connect(self.update_hardware_data)
        self.data_timer.start(1000)

        self.move(1400, 200)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(4)

        title = QLabel("⚡ 实时硬件监控")
        title.setStyleSheet("color: #3498db; font-size: 13pt; font-weight: bold; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.cpu_label = QLabel("CPU 占用: 0%  |  温度: --°C")
        self.cpu_label.setStyleSheet("color: #ffffff; font-size: 10pt; background: transparent;")
        layout.addWidget(self.cpu_label)

        self.cpu_bar = QProgressBar()
        self.cpu_bar.setTextVisible(False)
        self.cpu_bar.setFixedHeight(12)
        self.cpu_bar.setStyleSheet("QProgressBar { background-color: #2d2d2d; border: none; border-radius: 2px; }")
        layout.addWidget(self.cpu_bar)

        self.mem_label = QLabel("内存 占用: 0%  |  已用: -- GB")
        self.mem_label.setStyleSheet("color: #ffffff; font-size: 10pt; background: transparent;")
        layout.addWidget(self.mem_label)

        self.mem_bar = QProgressBar()
        self.mem_bar.setTextVisible(False)
        self.mem_bar.setFixedHeight(12)
        self.mem_bar.setStyleSheet("QProgressBar { background-color: #2d2d2d; border: none; border-radius: 2px; }")
        layout.addWidget(self.mem_bar)

        self.gpu_label = QLabel("GPU 占用: --%  |  温度: --°C")
        self.gpu_label.setStyleSheet("color: #ffffff; font-size: 10pt; background: transparent;")
        layout.addWidget(self.gpu_label)

        self.gpu_vram_label = QLabel("显存 占用: -- / -- MB")
        self.gpu_vram_label.setStyleSheet("color: #aaaaaa; font-size: 9pt; background: transparent;")
        layout.addWidget(self.gpu_vram_label)

        self.gpu_bar = QProgressBar()
        self.gpu_bar.setTextVisible(False)
        self.gpu_bar.setFixedHeight(12)
        self.gpu_bar.setStyleSheet("QProgressBar { background-color: #2d2d2d; border: none; border-radius: 2px; }")
        layout.addWidget(self.gpu_bar)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.switch_to_ball()

    def switch_to_ball(self):
        pos = self.pos()
        self.hide()
        if self.ball_ref:
            self.ball_ref.move(pos)
            self.ball_ref.show()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #252525; color: #ffffff; border: 1px solid #444; }
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background-color: #3498db; }
        """)
        exit_action = QAction("❌ 关闭监控程序", self)
        exit_action.triggered.connect(lambda: QApplication.instance().quit())
        menu.addAction(exit_action)
        menu.exec(event.globalPos())

    def get_gpu_data(self):
        try:
            cmd = ("nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total "
                   "--format=csv,noheader,nounits")
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                output = subprocess.check_output(cmd, shell=True, startupinfo=startupinfo).decode('utf-8').strip()
            else:
                output = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            match = re.search(r"([\d]+),\s+([\d]+),\s+([\d]+),\s+([\d]+)", output)
            if match:
                return int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
        except Exception:
            pass
        return None

    def get_cpu_temp(self):
        """获取CPU温度（Windows用wmi，Linux用psutil），失败返回'N/A'"""
        try:
            if sys.platform == "win32":
                try:
                    import wmi
                    c = wmi.WMI(namespace="root\\wmi")
                    temps = c.MSAcpi_ThermalZoneTemperature()
                    if temps:
                        kelvin_10 = temps[0].CurrentTemperature
                        celsius = (kelvin_10 / 10.0) - 273.15
                        return f"{celsius:.0f}°C"
                except Exception:
                    pass
                try:
                    import wmi
                    c = wmi.WMI(namespace="root\\cimv2")
                    probes = c.Win32_TemperatureProbe()
                    if probes and probes[0].CurrentReading is not None:
                        celsius = probes[0].CurrentReading / 10.0
                        return f"{celsius:.0f}°C"
                except Exception:
                    pass
                return "N/A"
            else:
                temps = psutil.sensors_temperatures()
                if "coretemp" in temps:
                    for entry in temps["coretemp"]:
                        if entry.label in ("Package id 0", "Tctl", "Core 0"):
                            return f"{entry.current:.0f}°C"
                    core_temps = [e.current for e in temps["coretemp"]]
                    if core_temps:
                        return f"{sum(core_temps)/len(core_temps):.0f}°C"
                for sensor_name in ["acpitz", "k10temp", "zenpower"]:
                    if sensor_name in temps:
                        t = temps[sensor_name][0].current
                        return f"{t:.0f}°C"
                return "N/A"
        except Exception:
            return "N/A"

    def get_color(self, pct):
        if pct < 50.0: return "#2ecc71"
        elif pct < 75.0: return "#f1c40f"
        elif pct < 90.0: return "#e67e22"
        else: return "#e74c3c"

    def set_bar_style(self, bar, value, color):
        bar.setValue(int(value))
        bar.setStyleSheet(f"""
            QProgressBar {{ background-color: #2d2d2d; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 2px; }}
        """)

    def update_hardware_data(self):
        gpu = self.get_gpu_data()
        if gpu:
            self.gpu_data = gpu
            # 悬浮球显示显存占用百分比
            _, _, vram_used, vram_total = gpu
            vram_percent = (vram_used / vram_total) * 100
        else:
            # 无GPU数据时回退为内存占用，保证球有数据显示
            vram_percent = psutil.virtual_memory().percent

        if self.ball_ref:
            self.ball_ref.current_vram_percent = vram_percent

        if not self.isVisible():
            return

        cpu_usage = psutil.cpu_percent()
        cpu_temp = self.get_cpu_temp()
        mem = psutil.virtual_memory()
        used_gb = mem.used / (1024 ** 3)
        total_gb = mem.total / (1024 ** 3)

        self.cpu_label.setText(f"CPU 占用: {cpu_usage}%  |  温度: {cpu_temp}")
        self.set_bar_style(self.cpu_bar, cpu_usage, self.get_color(cpu_usage))

        self.mem_label.setText(f"内存 占用: {mem.percent}%  |  已用: {used_gb:.1f} / {total_gb:.1f} GB")
        self.set_bar_style(self.mem_bar, mem.percent, self.get_color(mem.percent))

        if gpu:
            gpu_util, gpu_temp, vram_used, vram_total = gpu
            vram_percent = (vram_used / vram_total) * 100
            self.gpu_label.setText(f"GPU 占用: {gpu_util}%  |  温度: {gpu_temp}°C")
            self.gpu_vram_label.setText(f"显存 占用: {vram_percent:.1f}% ({vram_used} / {vram_total} MB)")
            self.set_bar_style(self.gpu_bar, gpu_util, self.get_color(gpu_util))
        else:
            self.gpu_label.setText("GPU 占用: N/A  |  温度: N/A")
            self.gpu_vram_label.setText("显存 占用: -- / -- MB")
            self.gpu_bar.setValue(0)


# ---------- 圆形悬浮球 (显存占用百分比) ----------
class BallWidget(QWidget):
    def __init__(self, panel_ref):
        super().__init__()
        self.panel_ref = panel_ref
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(90, 90)

        self.drag_pos = QPoint()
        self.wave_shift1 = 0.0
        self.wave_shift2 = 1.5
        self.current_vram_percent = 0.0   # 显存占用百分比

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self.animate_wave)
        self.anim_timer.start(40)

        self.move(1400, 200)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.show_panel()

    def show_panel(self):
        pos = self.pos()
        self.hide()
        self.panel_ref.move(pos)
        self.panel_ref.show()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #252525; color: #ffffff; border: 1px solid #444; }
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background-color: #3498db; }
        """)
        exit_action = QAction("❌ 关闭监控程序", self)
        exit_action.triggered.connect(lambda: QApplication.instance().quit())
        menu.addAction(exit_action)
        menu.exec(event.globalPos())

    def animate_wave(self):
        self.wave_shift1 += 0.08
        self.wave_shift2 -= 0.05
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = 45, 45, 40

        # 1. 深色底壳
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1a1c1e"))
        painter.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)

        # 2. 后层波浪（暗色）
        back_color = self.get_back_color(self.current_vram_percent)
        back_points = self.generate_wave_points(cx, cy, r, self.current_vram_percent, self.wave_shift2, 3, 0.08)
        painter.setBrush(QColor(back_color))
        painter.drawPolygon(back_points)

        # 3. 前层主体波浪（亮色）
        front_color = self.get_color(self.current_vram_percent)
        front_points = self.generate_wave_points(cx, cy, r, self.current_vram_percent, self.wave_shift1, 4, 0.06)
        painter.setBrush(QColor(front_color))
        painter.drawPolygon(front_points)

        # 4. 白金前景圆环
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)

        # 5. 百分比文字（带阴影）
        text = f"{self.current_vram_percent:.1f}%"
        font = QFont("Arial", 10, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#111111"))
        painter.drawText(cx - 20, cy - 8, 40, 16, Qt.AlignCenter, text)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(cx - 21, cy - 9, 40, 16, Qt.AlignCenter, text)

    def generate_wave_points(self, cx, cy, r, pct, wave_shift, wave_amp, wave_freq):
        water_y = cy + r - (2 * r * (pct / 100.0))
        points = []
        for x in range(cx - r, cx + r + 1):
            y = water_y + wave_amp * math.sin((x * wave_freq) + wave_shift)
            dx = x - cx
            dy_max = math.sqrt(max(0, r**2 - dx**2))
            y = max(cy - dy_max, min(y, cy + dy_max))
            points.append(QPoint(x, int(y)))
        for x in range(cx + r, cx - r - 1, -1):
            dx = x - cx
            dy_max = math.sqrt(max(0, r**2 - dx**2))
            points.append(QPoint(x, int(cy + dy_max)))
        return points

    def get_color(self, pct):
        if pct < 50.0: return "#2ecc71"
        elif pct < 75.0: return "#f1c40f"
        elif pct < 90.0: return "#e67e22"
        else: return "#e74c3c"

    def get_back_color(self, pct):
        if pct < 50.0: return "#27ae60"
        elif pct < 75.0: return "#d35400"
        elif pct < 90.0: return "#d35400"
        else: return "#c0392b"


# ---------- 主程序 ----------
class HardwareMonitorApp:
    def __init__(self):
        self.panel = MonitorPanel()
        self.ball = BallWidget(self.panel)
        self.panel.ball_ref = self.ball
        self.panel.hide()
        self.ball.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    monitor = HardwareMonitorApp()
    sys.exit(app.exec())