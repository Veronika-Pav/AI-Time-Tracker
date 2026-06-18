import sys
import sqlite3
import time
import threading
import win32gui
import win32process
import re
import os
import string
from ctypes import windll
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, 
                             QMainWindow, QVBoxLayout, QWidget, 
                             QLabel, QPushButton, QTableWidget, 
                             QTableWidgetItem, QHeaderView,
                             QTabWidget, QCheckBox, QSpinBox,
                             QListWidget, QListWidgetItem,
                             QMessageBox, QHBoxLayout, QLineEdit, QComboBox, QProgressBar,
                             QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QScrollArea, QFrame, QInputDialog)
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtCore import Qt, QTimer, QDate, pyqtSignal
import ctypes
import winreg

from gigachat_client import get_gigachat_response

import serial
import serial.tools.list_ports

import win32event
import win32api
import winerror

def check_single_instance():
    """Проверяет, что программа запущена только один раз."""
    mutex_name = "AITimeTracker_SingleInstance_Mutex"
    
    try:
        # Создаём мьютекс (если он уже существует, возвращается ERROR_ALREADY_EXISTS)
        mutex = win32event.CreateMutex(None, False, mutex_name)
        error = win32api.GetLastError()
        
        if error == winerror.ERROR_ALREADY_EXISTS:
            # Мьютекс уже существует -> программа уже запущена
            print("[INFO] Программа уже запущена. Активируем существующее окно.")
            
            # Пытаемся найти и показать существующее окно
            try:
                import win32gui
                import win32con
                
                def enum_windows_callback(hwnd, hwnds):
                    if win32gui.IsWindowVisible(hwnd):
                        window_text = win32gui.GetWindowText(hwnd)
                        if any(title in window_text for title in ["ИИ-трекер времени", "Настройки ИИ-трекера", "ИИ-трекер - Статистика"]):
                            hwnds.append(hwnd)
                
                windows = []
                win32gui.EnumWindows(enum_windows_callback, windows)
                
                for hwnd in windows:
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                    break
            except:
                pass
            
            return False  # Завершаем новый экземпляр
        else:
            # Мьютекс создан успешно — первый экземпляр
            return True
            
    except Exception as e:
        print(f"[WARNING] Ошибка при проверке единственного экземпляра: {e}")
        return True  # Если ошибка — разрешаем запуск

def find_esp_port():
    """Находит порт, к которому подключена ESP8266"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        # ESP8266 обычно определяется как USB-SERIAL CH340 или CP210x
        if "CH340" in port.description or "CP210" in port.description or "USB Serial" in port.description:
            return port.device
    return None

def send_to_esp(command):
    """Отправляет команду на ESP8266"""
    try:
        port = find_esp_port()
        if not port:
            print("[ESP] Порт не найден")
            return False
        
        ser = serial.Serial(port, 9600, timeout=2)
        ser.write(f"{command}\n".encode())
        response = ser.readline().decode().strip()
        print(f"[ESP] Команда: {command}, Ответ: {response}")
        ser.close()
        return True
    except Exception as e:
        print(f"[ESP] Ошибка: {e}")
        return False

def add_to_startup():
    """Добавляет программу в автозагрузку Windows"""
    try:
        exe_path = sys.executable
        if exe_path.endswith('.exe'):
            app_path = exe_path
        else:
            app_path = f'"{exe_path}" "{__file__}"'
        
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "AITimeTracker", 0, winreg.REG_SZ, app_path)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Ошибка добавления в автозагрузку: {e}")
        return False

def remove_from_startup():
    """Удаляет программу из автозагрузки Windows"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 
                             0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "AITimeTracker")
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Ошибка удаления из автозагрузки: {e}")
        return False

def is_in_startup():
    """Проверяет, добавлена ли программа в автозагрузку"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 
                             0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "AITimeTracker")
        winreg.CloseKey(key)
        return True
    except:
        return False
        
# НАСТРОЙКИ

NOTIFICATION_THRESHOLD_MINUTES = 30
CHECK_INTERVAL_SECONDS = 3

# ТРЕКЕР

def get_process_id(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except:
        return None

def get_active_window_info():
    try:
        hwnd = win32gui.GetForegroundWindow()
        window_title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return hwnd, window_title, pid
    except:
        return None, "", None

def clean_window_title(title):
    if not title:
        return ""
    title = re.sub(r'^[●◆█■▶►○●•▪▫◊◦♠♣♥♦]+\s*', '', title)
    title = re.sub(r'\s+', ' ', title)
    title = re.sub(r'^\(\d+\)\s+', '', title)
    return title.strip()

def is_system_window(window_title, pid):
    if not window_title:
        return True
    system_patterns = ["Program Manager", "Windows Shell", "Task Switching", "Start"]
    if window_title in system_patterns:
        return True
    if pid:
        system_pids = [0, 4]
        if pid in system_pids:
            return True
    return False

def init_subtasks_table():
    """Создаёт таблицу для подзадач"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            title TEXT NOT NULL,
            is_completed INTEGER DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

def init_database():
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT,
            end_time TEXT,
            window_title TEXT,
            process_id INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS distracting_apps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due_date TEXT,
            is_completed INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    # СОЗДАНИЕ ТАБЛИЦЫ ПОДЗАДАЧ
    init_subtasks_table()

    # Автоматическая очистка записей старше 30 дней
    from datetime import timedelta
    cutoff_date = (datetime.now() - timedelta(days=30)).isoformat()
    cursor.execute("DELETE FROM sessions WHERE start_time < ?", (cutoff_date,))
    deleted = cursor.rowcount
    if deleted > 0:
        print(f"[БД] Автоматически удалено {deleted} записей (старше 30 дней)")
    conn.commit()
    conn.close()

# ДЕЛА

def init_tasks_table():
    """Создаёт таблицу для дел, если её нет"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due_date TEXT,
            is_completed INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_all_tasks():
    """Возвращает все дела"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, due_date, is_completed FROM tasks ORDER BY is_completed ASC, due_date ASC")
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def add_task(title, due_date):
    """Добавляет новое дело"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tasks (title, due_date, created_at)
        VALUES (?, ?, ?)
    """, (title, due_date, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_task_status(task_id, is_completed):
    """Обновляет статус дела (выполнено/не выполнено)"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET is_completed = ? WHERE id = ?", (1 if is_completed else 0, task_id))
    conn.commit()
    conn.close()

def delete_task(task_id):
    """Удаляет дело"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def get_subtasks(task_id):
    """Возвращает все подзадачи для дела"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, is_completed FROM subtasks WHERE task_id = ?", (task_id,))
    subtasks = cursor.fetchall()
    conn.close()
    return subtasks

def add_subtask(task_id, title):
    """Добавляет подзадачу"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO subtasks (task_id, title) VALUES (?, ?)", (task_id, title))
    conn.commit()
    conn.close()

def update_subtask_status(subtask_id, is_completed):
    """Обновляет статус подзадачи"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE subtasks SET is_completed = ? WHERE id = ?", (1 if is_completed else 0, subtask_id))
    conn.commit()
    conn.close()

def delete_subtask(subtask_id):
    """Удаляет подзадачу"""
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))
    conn.commit()
    conn.close()

def save_session_start(window_title, process_id):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessions (start_time, window_title, process_id)
        VALUES (?, ?, ?)
    """, (datetime.now().isoformat(), window_title, process_id))
    conn.commit()
    session_id = cursor.lastrowid
    conn.close()
    return session_id

def update_session_end(session_id):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions SET end_time = ? WHERE id = ?
    """, (datetime.now().isoformat(), session_id))
    conn.commit()
    conn.close()

def delete_session(session_id):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

def get_distracting_apps():
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT app_name FROM distracting_apps")
    apps = [row[0] for row in cursor.fetchall()]
    conn.close()
    return apps

def add_distracting_app(app_name):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO distracting_apps (app_name) VALUES (?)", (app_name,))
    conn.commit()
    conn.close()

def remove_distracting_app(app_name):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM distracting_apps WHERE app_name = ?", (app_name,))
    conn.commit()
    conn.close()

def is_app_distracting(window_title):
    distracting_apps = get_distracting_apps()
    for app in distracting_apps:
        if app.lower() in window_title.lower():
            return True
    return False

def get_notification_threshold():
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM app_settings WHERE key = 'notification_threshold'")
    row = cursor.fetchone()
    conn.close()
    if row:
        return int(row[0])
    return NOTIFICATION_THRESHOLD_MINUTES

def set_notification_threshold(minutes):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('notification_threshold', ?)", (str(minutes),))
    conn.commit()
    conn.close()

def get_notifications_enabled():
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM app_settings WHERE key = 'notifications_enabled'")
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0] == 'True'
    return True

def set_notifications_enabled(enabled):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('notifications_enabled', ?)", (str(enabled),))
    conn.commit()
    conn.close()

last_window_title = None
last_process_id = None
current_session_id = None
session_start_time = None
distracting_start_time = None
last_notification_time = None

def tracker_worker(tray_icon_callback=None):
    global last_window_title, last_process_id, current_session_id, session_start_time
    global distracting_start_time, last_notification_time
    
    init_database()
    print("[Трекер] Запущен в фоновом режиме")
    
    while True:
        try:
            hwnd, window_title, pid = get_active_window_info()
            window_title = clean_window_title(window_title)
            
            # Пропускаем системные окна
            if is_system_window(window_title, pid) or not window_title:
                if current_session_id is not None:
                    if session_start_time:
                        duration = (datetime.now() - session_start_time).total_seconds()
                        if duration < 5:
                            delete_session(current_session_id)
                        else:
                            update_session_end(current_session_id)
                    current_session_id = None
                    session_start_time = None
                    distracting_start_time = None
                time.sleep(1)
                continue
            
            # изменился ли заголовок окна
            if window_title != last_window_title:
                print(f"[Трекер] Переключились на: {window_title[:50]}")
                
                # Закрываем предыдущую сессию
                if current_session_id is not None:
                    if session_start_time:
                        duration = (datetime.now() - session_start_time).total_seconds()
                        if duration < 5:
                            delete_session(current_session_id)
                        else:
                            update_session_end(current_session_id)
                    current_session_id = None
                    session_start_time = None
                    distracting_start_time = None
                
                # Начинаем новую сессию
                current_session_id = save_session_start(window_title, pid)
                session_start_time = datetime.now()
                last_window_title = window_title
                last_process_id = pid
                
                # Проверяем, отвлекающее ли приложение
                if is_app_distracting(window_title):
                    distracting_start_time = datetime.now()
                    last_notification_time = None
                    print(f"[Трекер] ⚠️ Отвлекающее приложение: {window_title[:40]}")
            
            # Проверка уведомлений (если в отвлекающем приложении)
            if distracting_start_time and get_notifications_enabled():
                elapsed = (datetime.now() - distracting_start_time).total_seconds() / 60
                threshold = get_notification_threshold()

                print(f"[ОТЛАДКА] elapsed={elapsed:.1f} мин, threshold={threshold} мин")
                
                if elapsed >= threshold:
                    if last_notification_time is None or (datetime.now() - last_notification_time).total_seconds() > 300:
                        if tray_icon_callback:
                            tray_icon_callback(f"Вы уже {elapsed:.0f} минут в отвлекающем приложении! Пора вернуться к работе.")
                            last_notification_time = datetime.now()
            
            time.sleep(CHECK_INTERVAL_SECONDS)
            
        except Exception as e:
            print(f"[Трекер] Ошибка: {e}")
            time.sleep(5)

def get_total_time_for_window(window_title):
    conn = sqlite3.connect("sessions.db")
    cursor = conn.cursor()
    cursor.execute("SELECT start_time, end_time FROM sessions WHERE window_title = ?", (window_title,))
    rows = cursor.fetchall()
    conn.close()
    
    total_seconds = 0
    for start_str, end_str in rows:
        if start_str and end_str:
            try:
                start = datetime.fromisoformat(start_str)
                end = datetime.fromisoformat(end_str)
                duration = (end - start).total_seconds()
                if duration > 0:
                    total_seconds += duration
            except:
                pass
    return round(total_seconds / 60, 1)

# GUI

def create_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(QColor(0, 120, 215))
    painter.setPen(Qt.white)
    painter.drawEllipse(8, 8, 48, 48)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawEllipse(28, 28, 8, 8)
    painter.end()
    return QIcon(pixmap)

class SettingsWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки ИИ-трекера")
        self.setWindowIcon(QIcon("assets/icon.ico"))
        self.setGeometry(200, 200, 700, 550)
        
        # Стили настроек
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
                border-radius: 15px;
            }
            QTabWidget::pane {
                border: none;
                background-color: rgba(255,255,255,230);
                border-radius: 12px;
            }
            QTabBar::tab {
                background-color: rgba(200, 200, 200, 100);
                padding: 8px 16px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: bold;
                min-width: 180px;
            }
            QTabBar::tab:selected {
                background-color: rgba(255, 255, 255, 200);
                color: #8b0000;
            }
            QPushButton {
                background-color: #8b0000;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #5c0000;
            }
            QListWidget::item:selected {
                background-color: #8b0000;
                color: white;
            }
            QLineEdit {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 6px;
                padding: 6px;
            }
            QCheckBox::indicator:checked {
                background-color: #8b0000;
            }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Заголовок
        title = QLabel("Настройки")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)
        
        # Создаём вкладки
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # Вкладка "Общие"
        general_tab = QWidget()
        tabs.addTab(general_tab, "Общие")
        general_layout = QVBoxLayout(general_tab)
        
        self.autostart_checkbox = QCheckBox("Запускать программу при входе в Windows")
        self.autostart_checkbox.setChecked(is_in_startup())
        self.autostart_checkbox.stateChanged.connect(self.on_autostart_changed)
        general_layout.addWidget(self.autostart_checkbox)
        general_layout.addStretch()
        
        # Вкладка "Отвлекающие приложения"
        distracting_tab = QWidget()
        tabs.addTab(distracting_tab, "Отвлекающие приложения")
        distracting_layout = QVBoxLayout(distracting_tab)
        
        # Поиск
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Поиск:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите название...")
        self.search_input.textChanged.connect(self.refresh_app_list)
        search_layout.addWidget(self.search_input)
        distracting_layout.addLayout(search_layout)
        
        # Статус
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        distracting_layout.addWidget(self.status_label)
        
        # Список
        distracting_layout.addWidget(QLabel("Отвлекающие приложения (отметьте для удаления):"))
        self.distracting_list = QListWidget()
        self.distracting_list.setSelectionMode(QListWidget.MultiSelection)
        distracting_layout.addWidget(self.distracting_list)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        add_file_btn = QPushButton("Добавить .exe файл")
        add_file_btn.clicked.connect(self.add_exe_manually)
        remove_selected_btn = QPushButton("Удалить выбранные")
        remove_selected_btn.clicked.connect(self.remove_selected)
        btn_layout.addWidget(add_file_btn)
        btn_layout.addWidget(remove_selected_btn)
        distracting_layout.addLayout(btn_layout)
        
        # Подсказка
        hint_label = QLabel("Нажмите «Добавить .exe файл» и выберите игру или приложение, которое вас отвлекает")
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: gray; font-size: 11px;")
        distracting_layout.addWidget(hint_label)
        
        # ===== Вкладка "Уведомления" =====
        notifications_tab = QWidget()
        tabs.addTab(notifications_tab, "Уведомления")
        notifications_layout = QVBoxLayout(notifications_tab)
        
        self.notifications_checkbox = QCheckBox("Включить уведомления об отвлекающих приложениях")
        self.notifications_checkbox.setChecked(get_notifications_enabled())
        notifications_layout.addWidget(self.notifications_checkbox)
        
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Время до уведомления (минуты):"))
        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(1, 120)
        self.threshold_spinbox.setValue(get_notification_threshold())
        threshold_layout.addWidget(self.threshold_spinbox)
        notifications_layout.addLayout(threshold_layout)
        
        save_notif_btn = QPushButton("Сохранить настройки уведомлений")
        save_notif_btn.clicked.connect(self.save_notification_settings)
        notifications_layout.addWidget(save_notif_btn)
        notifications_layout.addStretch()
        
        self.refresh_app_list()
    
    def on_autostart_changed(self, state):
        if state == Qt.Checked:
            if add_to_startup():
                QMessageBox.information(self, "Автозапуск", "Программа будет запускаться при входе в Windows")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось добавить программу в автозапуск")
                self.autostart_checkbox.setChecked(False)
        else:
            if remove_from_startup():
                QMessageBox.information(self, "Автозапуск", "Программа удалена из автозапуска")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось удалить программу из автозапуска")
    
    def refresh_app_list(self):
        self.distracting_list.clear()
        distracting_apps = get_distracting_apps()
        search_text = self.search_input.text().lower()
        
        count = 0
        for app_name in distracting_apps:
            if search_text and search_text not in app_name.lower():
                continue
            item = QListWidgetItem(app_name)
            self.distracting_list.addItem(item)
            count += 1
        self.status_label.setText(f"Найдено: {count} приложений")
    
    def add_exe_manually(self):
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите .exe файл", "", "Исполняемые файлы (*.exe)"
        )
        if not file_path:
            return
        app_name = os.path.basename(file_path).replace('.exe', '')
        conn = sqlite3.connect("sessions.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO distracting_apps (app_name) VALUES (?)", (app_name,))
        conn.commit()
        conn.close()
        self.refresh_app_list()
        QMessageBox.information(self, "Добавлено", f"'{app_name}' добавлен в список")
    
    def remove_selected(self):
        selected_items = self.distracting_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Внимание", "Выберите приложения для удаления")
            return
        conn = sqlite3.connect("sessions.db")
        cursor = conn.cursor()
        for item in selected_items:
            cursor.execute("DELETE FROM distracting_apps WHERE app_name = ?", (item.text(),))
        conn.commit()
        conn.close()
        self.refresh_app_list()
        QMessageBox.information(self, "Удалено", f"Удалено {len(selected_items)} приложений")
    
    def save_notification_settings(self):
        set_notifications_enabled(self.notifications_checkbox.isChecked())
        set_notification_threshold(self.threshold_spinbox.value())
        status = "включены" if self.notifications_checkbox.isChecked() else "выключены"
        QMessageBox.information(self, "Сохранено", f"Уведомления {status}.\nПорог: {self.threshold_spinbox.value()} минут.")

class AddTaskDialog(QDialog):
    """Диалог для добавления нового дела"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить дело")
        self.setGeometry(200, 200, 400, 200)
        
        layout = QFormLayout(self)
        
        # Название дела
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Например: Сдать отчёт по ТППО")
        layout.addRow("Название:", self.title_edit)
        
        # Дата сдачи
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        layout.addRow("Дата сдачи:", self.date_edit)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def get_task_data(self):
        """Возвращает введённые данные"""
        title = self.title_edit.text().strip()
        due_date = self.date_edit.date().toString("yyyy-MM-dd")
        return title, due_date

class TaskItemWidget(QWidget):
    def __init__(self, task_id, title, due_date, tasks_widget, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.title = title
        self.due_date = due_date
        self.tasks_widget = tasks_widget
        self.subtasks = []
        self.setup_ui()
        self.load_subtasks()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
    
        top_layout = QHBoxLayout()
    
        self.main_checkbox = QCheckBox()
        self.main_checkbox.setFixedWidth(30)
        self.main_checkbox.stateChanged.connect(self.on_main_changed)
    
        self.title_label = QLabel(self.title)
        self.title_label.setStyleSheet("font-weight: bold;")
    
        due_label = QLabel(f"📅 {self.due_date}" if self.due_date else "📅 нет даты")
        due_label.setStyleSheet("color: gray; font-size: 10px;")
    
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
    
        # Кнопка добавления подзадачи
        self.add_subtask_btn = QPushButton("➕")
        self.add_subtask_btn.setFixedSize(25, 25)
        self.add_subtask_btn.setToolTip("Добавить подзадачу")
        self.add_subtask_btn.clicked.connect(self.add_subtask)
    
        # Кнопка удаления дела
        self.delete_btn = QPushButton("🗑️")
        self.delete_btn.setFixedSize(25, 25)
        self.delete_btn.setToolTip("Удалить дело")
        self.delete_btn.clicked.connect(self.delete_task)
    
        top_layout.addWidget(self.main_checkbox)
        top_layout.addWidget(self.title_label, 1)
        top_layout.addWidget(due_label)
        top_layout.addWidget(self.progress_bar)
        top_layout.addWidget(self.add_subtask_btn)
        top_layout.addWidget(self.delete_btn)
    
        layout.addLayout(top_layout)
    
        # Область для подзадач
        self.subtasks_widget = QWidget()
        self.subtasks_layout = QVBoxLayout(self.subtasks_widget)
        self.subtasks_layout.setContentsMargins(30, 0, 0, 0)
        layout.addWidget(self.subtasks_widget)
    
        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
    
    def load_subtasks(self):
        """Загружает подзадачи из БД"""
        # Очищаем текущие
        for i in reversed(range(self.subtasks_layout.count())):
            widget = self.subtasks_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        self.subtasks = get_subtasks(self.task_id)
        completed = 0
        
        for subtask_id, title, is_completed in self.subtasks:
            subtask_widget = self.create_subtask_widget(subtask_id, title, is_completed)
            self.subtasks_layout.addWidget(subtask_widget)
            if is_completed:
                completed += 1
        
        # Обновляем прогресс
        total = len(self.subtasks)
        if total > 0:
            percent = int((completed / total) * 100)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{percent}%")
            self.progress_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4CAF50, stop:1 #8BC34A);
                }
            """)
        else:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0%")
        
        # Обновляем основной чекбокс (если все подзадачи выполнены)
        if total > 0 and completed == total:
            self.main_checkbox.setChecked(True)
        else:
            self.main_checkbox.setChecked(False)
    
    def create_subtask_widget(self, subtask_id, title, is_completed):
        """Создаёт виджет для подзадачи"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)
        
        checkbox = QCheckBox()
        checkbox.setChecked(is_completed == 1)
        checkbox.stateChanged.connect(lambda state, sid=subtask_id: self.on_subtask_changed(sid, state))
        
        label = QLabel(title)
        if is_completed:
            label.setStyleSheet("text-decoration: line-through; color: gray;")
        
        delete_btn = QPushButton("✖")
        delete_btn.setFixedSize(20, 20)
        delete_btn.setStyleSheet("color: red;")
        delete_btn.clicked.connect(lambda: self.delete_subtask(subtask_id))
        
        layout.addWidget(checkbox)
        layout.addWidget(label, 1)
        layout.addWidget(delete_btn)
        
        return widget
    
    def on_main_changed(self, state):
        """Отметка основного дела (все подзадачи)"""
        is_completed = (state == Qt.Checked)
        for subtask_id, _, _ in self.subtasks:
            update_subtask_status(subtask_id, is_completed)
        self.load_subtasks()
        # Обновляем общий прогресс
        if self.tasks_widget:
            self.tasks_widget.update_total_progress()
    
    def on_subtask_changed(self, subtask_id, state):
        """Изменение статуса подзадачи"""
        print(f"[DEBUG] on_subtask_changed: subtask_id={subtask_id}, state={state}")
    
        # Сохраняем статус в БД
        update_subtask_status(subtask_id, state == Qt.Checked)
    
        # Перезагружаем подзадачи
        self.load_subtasks()
    
        # Обновляем общий прогресс
        if self.tasks_widget and hasattr(self.tasks_widget, 'update_total_progress'):
            print("[DEBUG] Вызываем update_total_progress у родителя")
            self.tasks_widget.update_total_progress()
        else:
            print("[DEBUG] Родитель не имеет update_total_progress")

    def update_parent_progress(self):
        if self.tasks_widget and hasattr(self.tasks_widget, 'update_total_progress'):
            self.tasks_widget.update_total_progress()  
    
    def add_subtask(self):
        """Добавляет подзадачу"""
        from PyQt5.QtWidgets import QInputDialog
        title, ok = QInputDialog.getText(self, "Новая подзадача", "Введите название подзадачи:")
        if ok and title.strip():
            add_subtask(self.task_id, title.strip())
            self.load_subtasks()
            if self.tasks_widget:
                self.tasks_widget.update_total_progress()
    
    def delete_subtask(self, subtask_id):
        """Удаляет подзадачу"""
        reply = QMessageBox.question(self, "Подтверждение", "Удалить подзадачу?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            delete_subtask(subtask_id)
            self.load_subtasks()
            if self.tasks_widget:
                self.tasks_widget.update_total_progress()
    
    def delete_task(self):
        """Удаляет дело целиком"""
        reply = QMessageBox.question(self, "Подтверждение", f"Удалить дело '{self.title}'?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            delete_task(self.task_id)
            if self.tasks_widget:
                self.tasks_widget.refresh_tasks()
                self.tasks_widget.update_total_progress()

class TasksWidget(QWidget):
    """Вкладка с делами и прогресс-баром"""
    def __init__(self):
        super().__init__()
        init_tasks_table()
        init_subtasks_table()
        self.setup_ui()
        self.refresh_tasks()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Общий прогресс
        progress_layout = QHBoxLayout()
        progress_layout.addWidget(QLabel("📊 Общий прогресс по всем делам:"))
        self.total_progress_bar = QProgressBar()
        self.total_progress_bar.setRange(0, 100)
        self.total_progress_bar.setFixedHeight(25)
        self.total_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #2196F3, stop:1 #03A9F4);
                border-radius: 5px;
            }
        """)
        progress_layout.addWidget(self.total_progress_bar)
        layout.addLayout(progress_layout)
        
        # Кнопка добавления дела
        self.add_btn = QPushButton("➕ Добавить дело")
        self.add_btn.clicked.connect(self.add_task)
        layout.addWidget(self.add_btn)
        
        # Скролл-область
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; }")
        
        self.tasks_container = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setAlignment(Qt.AlignTop)
        
        self.scroll_area.setWidget(self.tasks_container)
        layout.addWidget(self.scroll_area)
    
    def update_total_progress(self):
        """Обновляет общий прогресс по всем делам"""
        tasks = get_all_tasks()
        total_subtasks = 0
        completed_subtasks = 0
        
        for task_id, title, due_date, is_completed in tasks:
            subtasks = get_subtasks(task_id)
            for subtask_id, subtask_title, subtask_completed in subtasks:
                total_subtasks += 1
                if subtask_completed:
                    completed_subtasks += 1
        
        if total_subtasks > 0:
            percent = int((completed_subtasks / total_subtasks) * 100)
            self.total_progress_bar.setValue(percent)
            self.total_progress_bar.setFormat(f"Общий прогресс: {percent}% ({completed_subtasks}/{total_subtasks})")
        else:
            self.total_progress_bar.setValue(0)
            self.total_progress_bar.setFormat("Общий прогресс: 0% (нет подзадач)")
    
    def refresh_tasks(self):
        """Обновляет список дел"""
        # Очищаем старые виджеты
        for i in reversed(range(self.tasks_layout.count())):
            widget = self.tasks_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # Загружаем задачи из БД
        tasks = get_all_tasks()
        for task_id, title, due_date, is_completed in tasks:
            task_widget = TaskItemWidget(task_id, title, due_date, self)
            task_widget.main_checkbox.setChecked(is_completed == 1)
            self.tasks_layout.addWidget(task_widget)
        
        # Обновляем общий прогресс
        self.update_total_progress()
    
    def add_task(self):
        """Открывает диалог добавления дела"""
        dialog = AddTaskDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            title, due_date = dialog.get_task_data()
            if title:
                add_task(title, due_date)
                self.refresh_tasks()
            else:
                QMessageBox.warning(self, "Ошибка", "Название дела не может быть пустым")

class StatisticsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ИИ-трекер времени - Статистика")
        self.setGeometry(100, 100, 900, 550)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        title = QLabel("📊 Статистика использования приложений")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # ВЫБОР ПЕРИОДА
        period_layout = QHBoxLayout()
        period_layout.addWidget(QLabel("📅 Период:"))
        
        self.period_combo = QComboBox()
        self.period_combo.addItem("📆 Сегодня")
        self.period_combo.addItem("Неделя (7 дней)")
        self.period_combo.addItem("Месяц (30 дней)")
        self.period_combo.addItem("Всё время")
        self.period_combo.currentIndexChanged.connect(self.load_statistics)
        period_layout.addWidget(self.period_combo)
        
        period_layout.addStretch()
        layout.addLayout(period_layout)
        
        # ТАБЛИЦА
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Приложение / окно", "Время (часы:минуты)", "Доля"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 100)
        layout.addWidget(self.table)
        
        # КНОПКИ
        btn_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 Обновить")
        refresh_btn.clicked.connect(self.load_statistics)
        
        clear_old_btn = QPushButton("🗑️ Очистить данные старше месяца")
        clear_old_btn.clicked.connect(self.clear_old_data)
        
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(clear_old_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # ИТОГО
        self.total_label = QLabel("")
        self.total_label.setStyleSheet("font-weight: bold; padding: 10px;")
        layout.addWidget(self.total_label)
        
        # Таймер автообновления
        self.timer = QTimer()
        self.timer.timeout.connect(self.load_statistics)
        self.timer.start(10000)
        
        self.load_statistics()
    
    def get_date_filter(self):
        """Возвращает SQL фильтр по дате в зависимости от выбранного периода"""
        now = datetime.now()
        
        if self.period_combo.currentIndex() == 0:  # Сегодня
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start_date.isoformat()
        
        elif self.period_combo.currentIndex() == 1:  # Неделя
            from datetime import timedelta
            start_date = now - timedelta(days=7)
            return start_date.isoformat()
        
        elif self.period_combo.currentIndex() == 2:  # Месяц
            from datetime import timedelta
            start_date = now - timedelta(days=30)
            return start_date.isoformat()
        
        else:  # Всё время
            return None
    
    def load_statistics(self):
        try:
            conn = sqlite3.connect("sessions.db")
            cursor = conn.cursor()
            
            date_filter = self.get_date_filter()
            
            if date_filter:
                cursor.execute("""
                    SELECT window_title, 
                           SUM(strftime('%s', end_time) - strftime('%s', start_time)) as seconds
                    FROM sessions 
                    WHERE end_time IS NOT NULL 
                      AND start_time > ?
                    GROUP BY window_title 
                    ORDER BY seconds DESC
                    LIMIT 50
                """, (date_filter,))
            else:
                cursor.execute("""
                    SELECT window_title, 
                           SUM(strftime('%s', end_time) - strftime('%s', start_time)) as seconds
                    FROM sessions 
                    WHERE end_time IS NOT NULL
                    GROUP BY window_title 
                    ORDER BY seconds DESC
                    LIMIT 50
                """)
            
            data = cursor.fetchall()
            conn.close()
            
            self.table.setRowCount(len(data))
            total_seconds = 0
            
            for row, (window_title, seconds) in enumerate(data):
                if not window_title or window_title == "" or not seconds or seconds <= 0:
                    continue
                
                total_seconds += seconds
                
                # Форматируем время
                minutes = seconds / 60
                if minutes >= 60:
                    hours = int(minutes // 60)
                    mins = int(minutes % 60)
                    time_text = f"{hours} ч {mins} мин"
                else:
                    time_text = f"{minutes:.1f} мин"
                
                self.table.setItem(row, 0, QTableWidgetItem(window_title[:70]))
                self.table.setItem(row, 1, QTableWidgetItem(time_text))
                # Доля пустая
                self.table.setItem(row, 2, QTableWidgetItem(""))
            
            # Вторая проходка для долей (нужно знать общее время)
            for row, (window_title, seconds) in enumerate(data):
                if seconds and total_seconds > 0:
                    percent = (seconds / total_seconds) * 100
                    self.table.setItem(row, 2, QTableWidgetItem(f"{percent:.1f}%"))
            
            # Обновляем итого
            total_hours = int(total_seconds // 3600)
            total_mins = int((total_seconds % 3600) // 60)
            
            period_names = ["сегодня", "за неделю", "за месяц", "за всё время"]
            period_name = period_names[self.period_combo.currentIndex()]
            
            if total_hours > 0:
                self.total_label.setText(f"📊 Итого {period_name}: {total_hours} ч {total_mins} мин")
            else:
                self.total_label.setText(f"📊 Итого {period_name}: {total_mins} мин")
            
            # Обновляем заголовок окна
            self.setWindowTitle(f"ИИ-трекер - Статистика ({period_name})")
                
        except Exception as e:
            print(f"Ошибка загрузки статистики: {e}")
    
    def clear_old_data(self):
        """Удаляет записи старше 30 дней"""
        from datetime import timedelta
        
        cutoff_date = (datetime.now() - timedelta(days=30)).isoformat()
        
        reply = QMessageBox.question(
            self, 
            "Подтверждение", 
            f"Удалить все записи старше 30 дней?\n\n"
            f"Эта операция необратима. Статистика за этот период будет потеряна.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect("sessions.db")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE start_time < ?", (cutoff_date,))
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            QMessageBox.information(self, "Готово", f"🗑️ Удалено {deleted} записей старше 30 дней")
            self.load_statistics()

class AIChatWidget(QWidget):
    """Вкладка с ИИ‑чатом на базе GigaChat"""
    # Создаём сигнал для передачи ответа из потока в UI
    response_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.is_loading = False
        self.response_received.connect(self.on_response_received)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Заголовок
        title = QLabel("ИИ‑ассистент по продуктивности (GigaChat)")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Область чата
        self.chat_area = QListWidget()
        self.chat_area.setStyleSheet("""
            QListWidget {
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        layout.addWidget(self.chat_area)
        
        # Статус (показывает, когда ИИ печатает)
        self.status_label = QLabel("💡 Готов к общению")
        self.status_label.setStyleSheet("color: gray; font-size: 10px; padding: 5px;")
        layout.addWidget(self.status_label)
        
        # Поле ввода и кнопка отправки
        input_layout = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Напишите свой вопрос... Например: 'Напомни мои дела' или 'Как не отвлекаться?'")
        self.input_field.returnPressed.connect(self.send_message)
        
        self.send_btn = QPushButton("Отправить")
        self.send_btn.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_btn)
        
        layout.addLayout(input_layout)
        
        # Кнопка очистки чата
        clear_btn = QPushButton("🗑️ Очистить историю чата")
        clear_btn.clicked.connect(self.clear_chat)
        layout.addWidget(clear_btn)
        
        # Приветственное сообщение
        self.add_message("ИИ", "Привет! Я твой ИИ‑ассистент по продуктивности. Могу напомнить о делах, дать совет по тайм-менеджменту или просто поддержать. Спрашивай!")
    
    def get_tasks_list(self):
        """Получает список активных дел из БД"""
        tasks = get_all_tasks()
        task_list = []
        for task_id, title, due_date, is_completed in tasks:
            if not is_completed:  # Только невыполненные
                task_list.append(f"• {title} (до {due_date})" if due_date else f"• {title}")
        return task_list
    
    def add_message(self, sender, message):
        """Добавляет сообщение в чат"""
        item_text = f"{sender}: {message}"
        item = QListWidgetItem(item_text)
        
        # Разный цвет для пользователя и ИИ
        if sender == "Вы":
            item.setBackground(QColor(240, 248, 255))  # Светло-синий
        else:
            item.setBackground(QColor(245, 255, 245))  # Светло-зелёный
        
        self.chat_area.addItem(item)
        self.chat_area.scrollToBottom()
    
    def send_message(self):
        if self.is_loading:
            return
    
        user_message = self.input_field.text().strip()
        if not user_message:
            return
    
        self.add_message("Вы", user_message)
        self.input_field.clear()
    
        self.is_loading = True
        self.status_label.setText("ИИ печатает...")
        self.send_btn.setEnabled(False)
        self.input_field.setEnabled(False)
    
        def fetch_response():
            try:
                tasks = self.get_tasks_list()
                response = get_gigachat_response(user_message, tasks)
            except Exception as e:
                response = f"Ошибка: {str(e)}"
            
            # Отправляем сигнал
            self.response_received.emit(response)
        
        threading.Thread(target=fetch_response, daemon=True).start()
    
    def on_response_received(self, response):
        """Вызывается в основном потоке при получении ответа"""
        self.add_message(" ИИ", response)
        self.status_label.setText("💡 Готов к общению")
        self.is_loading = False
        self.send_btn.setEnabled(True)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()
    
    def clear_chat(self):
        """Очищает историю чата"""
        self.chat_area.clear()
        self.add_message("ИИ", "История чата очищена. Чем могу помочь?")

class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int)
    ]

class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t)
    ]

def enable_acrylic(hwnd):
    accent = ACCENT_POLICY()

    # ACCENT_ENABLE_BLURBEHIND
    accent.AccentState = 3

    # AA BB GG RR
    # AA = прозрачность (00..FF)
    accent.GradientColor = 0xCC202020

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = 19
    data.Data = ctypes.cast(
        ctypes.pointer(accent),
        ctypes.c_void_p
    )
    data.SizeOfData = ctypes.sizeof(accent)

    ctypes.windll.user32.SetWindowCompositionAttribute(
        hwnd,
        ctypes.byref(data)
    )

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("ИИ-трекер времени")
        self.setWindowIcon(QIcon("assets/icon.ico"))
        self.setGeometry(100, 100, 1000, 650)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Заголовок
        header = QLabel("ИИ-трекер времени")
        header.setStyleSheet("font-size: 22px; font-weight: bold; color: white;")
        layout.addWidget(header)
        
        subtitle = QLabel("Контролируй своё время")
        subtitle.setStyleSheet("color: #7f8c8d; margin-bottom: 20px;")
        layout.addWidget(subtitle)
        
        # Вкладки
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                background-color: rgba(255, 255, 255, 200);
                border-radius: 10px;
            }
            QTabBar::tab {
                background-color: rgba(224, 224, 224, 150);
                padding: 8px 20px;
                margin-right: 5px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background-color: #8b0000;
                color: white;
            }
        """)
        layout.addWidget(self.tabs)
        
        self.stats_tab = StatisticsWindow()
        self.tabs.addTab(self.stats_tab, "📊 Статистика")
        
        self.tasks_tab = TasksWidget()
        self.tabs.addTab(self.tasks_tab, "📝 Мои дела")
        
        self.chat_tab = AIChatWidget()
        self.tabs.addTab(self.chat_tab, "🤖 ИИ‑чат")
        
        self.setStyleSheet("""
            QMainWindow {
                background: rgba(255,255,255,180);
            }

            QWidget {
                color: black;
            }
        """)

        QTimer.singleShot(
            100,
            lambda: enable_acrylic(int(self.winId()))
        )

class TrayApp:
    def __init__(self):
        self.app = QApplication(sys.argv)

        app_icon = QIcon("assets/icon.ico")
        self.app.setWindowIcon(app_icon)
        self.app.setQuitOnLastWindowClosed(False)
        
        self.tracker_thread = threading.Thread(target=tracker_worker, args=(self.show_notification,), daemon=True)
        self.tracker_thread.start()
        
        self.tray_icon = QSystemTrayIcon()
        icon = create_icon()
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("ИИ-трекер времени\nТрекер активен")
        
        self.main_window = None
        self.settings_window = None
        
        self.setup_menu()
        self.tray_icon.show()
        
        print("=" * 50)
        print("✅ ИИ-трекер времени запущен!")
        print("Уведомления об отвлекающих приложениях активны")
        print("Нажмите правой кнопкой мыши на иконку → Показать статистику")
        print("=" * 50)
    
    def setup_menu(self):
        menu = QMenu()
        show_stats = menu.addAction("📊 Показать статистику")
        show_stats.triggered.connect(self.show_main_window)  # ✅ исправлено
        show_settings = menu.addAction("⚙️ Настройки")
        show_settings.triggered.connect(self.show_settings)
        menu.addSeparator()
        exit_action = menu.addAction("Выйти")
        exit_action.triggered.connect(self.exit_app)
        self.tray_icon.setContextMenu(menu)
        self.show_main_window()

    def show_notification(self, message):
        self.tray_icon.showMessage("ИИ-трекер времени", message, QSystemTrayIcon.Information, 5000)
        # Отправляем команду на микроконтроллер, чтобы светодиод мигал
        threading.Thread(target=send_to_esp, args=("BLINK",)).start()
        import winsound
        winsound.Beep(1000, 500)

    def show_main_window(self):
        if self.main_window is None:
            self.main_window = MainWindow()

        self.main_window.showNormal()
        self.main_window.activateWindow()
        self.main_window.raise_()

        QTimer.singleShot(
            100,
            lambda: enable_acrylic(int(self.main_window.winId()))
        )
    
    def show_settings(self):
        if self.settings_window is None:
            self.settings_window = SettingsWindow()
        self.settings_window.show()
        self.settings_window.raise_()
    
    def exit_app(self):
        print("Завершение работы...")
        sys.exit(0)
    
    def run(self):
        sys.exit(self.app.exec_())

if __name__ == "__main__":
    # Проверяем, что программа запущена только один раз
    if not check_single_instance():
        sys.exit(0)  # Выходим, если уже запущена
    
    app = TrayApp()
    app.run()