import sys
import json
import requests
import base64
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QComboBox, 
                             QTextEdit, QPushButton, QVBoxLayout, 
                             QHBoxLayout, QWidget, QLabel, QSplitter,
                             QTabWidget, QGroupBox, QFileDialog, QListWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QTextCursor, QColor, QTextCharFormat, QPalette
from PyPDF2 import PdfReader


class OllamaAPIThread(QThread):
    response_received = pyqtSignal(str)
    models_received = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, api_url="http://localhost:11434/api"):
        super().__init__()
        self.api_url = api_url
        self.action = None
        self.model = None
        self.prompt = None
        self.instructions = None
        self.files = []
        self.chat_history = []
        
    def run(self):
        try:
            if self.action == "generate":
                self._generate_response()
            elif self.action == "list_models":
                self._list_models()
        except Exception as e:
            self.error_occurred.emit(f"Error: {str(e)}")
    
    def _generate_response(self):
        url = f"{self.api_url}/chat"
        
        messages = []
        
        if self.instructions and self.instructions.strip():
            messages.append({"role": "system", "content": self.instructions})
        
        if self.chat_history:
            messages.extend(self.chat_history)
        
        messages.append({"role": "user", "content": self.prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {}
        }
        
        if self.instructions and self.instructions.strip():
            payload["options"]["system"] = self.instructions
        
        if self.files:
            images = []
            text_content = ""
            
            for file_path in self.files:
                try:
                    mime_type = self._get_mime_type(file_path)
                    
                    if mime_type.startswith('image/'):
                        with open(file_path, "rb") as file:
                            file_content = file.read()
                            base64_content = base64.b64encode(file_content).decode('utf-8')
                            images.append(base64_content)
                    
                    elif mime_type == 'text/plain':
                        with open(file_path, "r") as file:
                            file_text = file.read()
                            file_name = os.path.basename(file_path)
                            text_content += f"\n\n--- Content from {file_name} ---\n{file_text}\n"
                    
                    elif mime_type == 'application/pdf':
                        try:
                            reader = PdfReader(file_path)
                            file_name = os.path.basename(file_path)
                            text_content += f"\n\n--- Content from {file_name} ---\n"
                            
                            for page_num, page in enumerate(reader.pages):
                                page_text = page.extract_text()
                                if page_text:
                                    text_content += f"\n-- Page {page_num + 1} --\n{page_text}\n"
                        except ImportError:
                            self.error_occurred.emit("PyPDF2 not installed. Please install it to process PDF files: pip install PyPDF2")
                            return
                    
                except Exception as e:
                    self.error_occurred.emit(f"Error processing file {file_path}: {str(e)}")
                    return
            
            if images:
                payload["images"] = images
            
            if text_content:
                if messages:
                    messages[-1]["content"] += f"\n{text_content}"
        
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json()
            response_content = data.get("message", {}).get("content", "No response")
            
            self.chat_history.append({"role": "user", "content": self.prompt})
            self.chat_history.append({"role": "assistant", "content": response_content})
            
            self.response_received.emit(response_content)
        else:
            try:
                self._fallback_generate()
            except Exception as e:
                self.error_occurred.emit(f"API Error: {response.status_code} - {response.text}")
    
    def _fallback_generate(self):
        """Fallback to the generate endpoint if chat endpoint is not available"""
        url = f"{self.api_url}/generate"
        
        context_prompt = ""
        
        if self.instructions and self.instructions.strip():
            context_prompt = f"System: {self.instructions}\n\n"
        
        for msg in self.chat_history:
            prefix = "User: " if msg["role"] == "user" else "Assistant: "
            context_prompt += f"{prefix}{msg['content']}\n\n"

        if self.instructions and self.instructions.strip():
            context_prompt += f"IMPORTANT INSTRUCTION: {self.instructions}\n\n"
            
        context_prompt += f"User: {self.prompt}\n\nAssistant:"
        
        payload = {
            "model": self.model,
            "prompt": context_prompt,
            "stream": False,
            "options": {}
        }
        
        if self.instructions and self.instructions.strip():
            payload["options"]["system"] = self.instructions
        
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            data = response.json()
            response_content = data.get("response", "No response")
            
            self.chat_history.append({"role": "user", "content": self.prompt})
            self.chat_history.append({"role": "assistant", "content": response_content})
            
            self.response_received.emit(response_content)
        else:
            self.error_occurred.emit(f"API Error: {response.status_code} - {response.text}")
    
    def _list_models(self):
        url = f"{self.api_url}/tags"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            models = [model["name"] for model in data.get("models", [])]
            self.models_received.emit(models)
        else:
            self.error_occurred.emit(f"Failed to fetch models: {response.status_code} - {response.text}")
    
    def _get_mime_type(self, file_path):
        """Determine MIME type based on file extension"""
        extension = os.path.splitext(file_path)[1].lower()
        
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp',
            '.pdf': 'application/pdf',
            '.txt': 'text/plain'
        }
        
        return mime_types.get(extension, 'application/octet-stream')


class OllamaClientApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api_thread = OllamaAPIThread()
        self.file_paths = []
        self.init_ui()
        self.setup_connections()
        self.load_models()
        self.center_on_screen()
        
    def center_on_screen(self):
        """Center the window on the screen"""
        screen = QApplication.primaryScreen().geometry()
        window_size = self.geometry()
        x = (screen.width() - window_size.width()) // 2
        y = (screen.height() - window_size.height()) // 2
        self.move(x, y)
        
    def init_ui(self):
        self.setWindowTitle("Ollama Chat Client")
        self.setGeometry(100, 100, 900, 700)
        
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Select Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        model_layout.addWidget(self.model_combo)
        self.refresh_btn = QPushButton("Refresh Models")
        model_layout.addWidget(self.refresh_btn)
        self.clear_chat_btn = QPushButton("Clear Chat")
        model_layout.addWidget(self.clear_chat_btn)
        model_layout.addStretch()
        main_layout.addLayout(model_layout)
        
        instructions_group = QGroupBox("Model Instructions")
        instructions_layout = QVBoxLayout()
        self.instructions_text = QTextEdit()
        self.instructions_text.setPlaceholderText("Enter model instructions here (system prompt)...")
        self.instructions_text.setMaximumHeight(100)
        instructions_layout.addWidget(self.instructions_text)
        
        self.instructions_warning = QLabel("Note: Some models may not always follow instructions perfectly.")
        self.instructions_warning.setStyleSheet("color: #FFA500;")
        instructions_layout.addWidget(self.instructions_warning)
        
        instructions_group.setLayout(instructions_layout)
        main_layout.addWidget(instructions_group)
        
        file_group = QGroupBox("File Attachments")
        file_layout = QVBoxLayout()
        
        file_buttons_layout = QHBoxLayout()
        self.add_file_btn = QPushButton("Add File")
        self.clear_files_btn = QPushButton("Clear Files")
        file_buttons_layout.addWidget(self.add_file_btn)
        file_buttons_layout.addWidget(self.clear_files_btn)
        file_buttons_layout.addStretch()
        file_layout.addLayout(file_buttons_layout)
        
        self.files_list = QListWidget()
        self.files_list.setMaximumHeight(100)
        file_layout.addWidget(self.files_list)
        
        file_group.setLayout(file_layout)
        main_layout.addWidget(file_group)
        
        chat_splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlaceholderText("Chat history will appear here...")
        chat_splitter.addWidget(self.chat_display)
        
        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("Enter your message here...")
        self.input_text.setMaximumHeight(100)
        
        button_layout = QHBoxLayout()
        self.generate_btn = QPushButton("Send Message")
        self.generate_btn.setFixedHeight(40)
        
        input_widget = QWidget()
        input_layout = QVBoxLayout(input_widget)
        input_layout.addWidget(self.input_text)
        input_layout.addLayout(button_layout)
        button_layout.addWidget(self.generate_btn)
        
        chat_splitter.addWidget(input_widget)
        
        chat_splitter.setSizes([500, 150])
        main_layout.addWidget(chat_splitter)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
    
    def setup_connections(self):
        self.generate_btn.clicked.connect(self.generate_response)
        self.refresh_btn.clicked.connect(self.load_models)
        self.add_file_btn.clicked.connect(self.add_file)
        self.clear_files_btn.clicked.connect(self.clear_files)
        self.clear_chat_btn.clicked.connect(self.clear_chat)
        
        self.input_text.installEventFilter(self)
        
        self.api_thread.response_received.connect(self.handle_response)
        self.api_thread.models_received.connect(self.update_models)
        self.api_thread.error_occurred.connect(self.handle_error)
    
    def eventFilter(self, obj, event):
        if obj is self.input_text and event.type() == event.Type.KeyPress:
            from PyQt6.QtCore import Qt
            
            key = event.key()
            modifiers = event.modifiers()
            
            if key == Qt.Key.Key_Return and not (modifiers & Qt.KeyboardModifier.ShiftModifier):
                self.generate_response()
                return True
        
        return super().eventFilter(obj, event)
    
    def is_dark_theme(self):
        """Determine if the application is using a dark theme based on text/background contrast"""
        app = QApplication.instance()
        palette = app.palette()
        background_color = palette.color(QPalette.ColorRole.Base)
        text_color = palette.color(QPalette.ColorRole.Text)
        
        bg_brightness = (background_color.red() * 299 + background_color.green() * 587 + background_color.blue() * 114) / 1000
        text_brightness = (text_color.red() * 299 + text_color.green() * 587 + text_color.blue() * 114) / 1000
        
        return bg_brightness < text_brightness
    
    def get_text_color(self):
        palette = QApplication.instance().palette()
        return palette.color(QPalette.ColorRole.Text)
    
    def get_theme_color(self, role):
        is_dark = self.is_dark_theme()
        
        palette = QApplication.instance().palette()
        
        if role == "system":
            return palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        elif role == "user":
            return QColor("#2979FF") if is_dark else QColor("#0056D6")
        elif role == "assistant":
            return QColor("#26A69A") if is_dark else QColor("#00796B")
        else:
            return palette.color(QPalette.ColorRole.Text)
    
    def clear_chat(self):
        self.api_thread.chat_history = []
        self.chat_display.clear()
        self.add_system_message("Chat history cleared. Starting a new conversation.")
    
    def add_system_message(self, message):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        format = QTextCharFormat()
        format.setForeground(self.get_theme_color("system"))
        cursor.setCharFormat(format)
        cursor.insertText(f"System: {message}\n\n")
        
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
    
    def add_user_message(self, message):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        prefix_format = QTextCharFormat()
        prefix_format.setForeground(self.get_theme_color("user"))
        cursor.setCharFormat(prefix_format)
        cursor.insertText("You: ")
        
        message_format = QTextCharFormat()
        message_format.setForeground(self.get_text_color())
        cursor.setCharFormat(message_format)
        cursor.insertText(f"{message}\n\n")
        
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
    
    def add_assistant_message(self, message):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        prefix_format = QTextCharFormat()
        prefix_format.setForeground(self.get_theme_color("assistant"))
        cursor.setCharFormat(prefix_format)
        cursor.insertText("AI: ")
        
        message_format = QTextCharFormat()
        message_format.setForeground(self.get_text_color())
        cursor.setCharFormat(message_format)
        cursor.insertText(f"{message}\n\n")
        
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
    
    def load_models(self):
        self.add_system_message("Loading models...")
        self.api_thread.action = "list_models"
        self.api_thread.start()
    
    def update_models(self, models):
        self.model_combo.clear()
        if models:
            self.model_combo.addItems(models)
            self.add_system_message(f"Loaded {len(models)} models.")
        else:
            self.add_system_message("No models found. Make sure Ollama is running.")
    
    def add_file(self):
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("All Supported Files (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.txt *.pdf);;Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;Documents (*.pdf *.txt);;All Files (*)")
        
        if file_dialog.exec():
            selected_files = file_dialog.selectedFiles()
            for file_path in selected_files:
                if file_path not in self.file_paths:
                    mime_type = self.api_thread._get_mime_type(file_path)
                    if mime_type.startswith('image/') or mime_type == 'text/plain' or mime_type == 'application/pdf':
                        self.file_paths.append(file_path)
                        file_name = os.path.basename(file_path)
                        if mime_type.startswith('image/'):
                            display_name = f"📷 {file_name}"
                        elif mime_type == 'text/plain':
                            display_name = f"📄 {file_name}"
                        elif mime_type == 'application/pdf':
                            display_name = f"📑 {file_name}"
                        else:
                            display_name = f"📎 {file_name}"
                        self.files_list.addItem(display_name)
                    else:
                        self.chat_display.setPlainText(f"Unsupported file type: {file_path}")
    
    def clear_files(self):
        self.file_paths.clear()
        self.files_list.clear()
    
    def generate_response(self):
        if not self.model_combo.currentText():
            self.add_system_message("Please select a model first.")
            return
            
        prompt = self.input_text.toPlainText().strip()
        if not prompt:
            self.add_system_message("Please enter a message.")
            return
        
        self.add_user_message(prompt)
        
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Generating...")
        
        self.input_text.clear()
        
        instructions = self.instructions_text.toPlainText()
        if instructions and ("document" in instructions.lower() or "pdf" in instructions.lower()):
            self.add_system_message("Reminder: The model will try to follow your instructions to only use document content, but may not always comply perfectly.")
        
        self.api_thread.action = "generate"
        self.api_thread.model = self.model_combo.currentText()
        self.api_thread.prompt = prompt
        self.api_thread.instructions = instructions
        self.api_thread.files = self.file_paths.copy()
        self.api_thread.start()
    
    def handle_response(self, response):
        self.add_assistant_message(response)
        
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Send Message")
        
        self.clear_files()
    
    def handle_error(self, error_msg):
        self.add_system_message(f"Error: {error_msg}")
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Send Message")

    def refresh_chat_display(self):
        messages = []
        
        doc = self.chat_display.document()
        text = doc.toPlainText()
        
        self.chat_display.clear()
        
        if not text.strip():
            return
            
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            if line.startswith("System:"):
                message = line[7:].strip()
                
                i += 1
                while i < len(lines) and lines[i].strip():
                    message += '\n' + lines[i].strip()
                    i += 1
                    
                self.add_system_message(message)
                
            elif line.startswith("You:"):
                message = line[4:].strip()
                
                i += 1
                while i < len(lines) and lines[i].strip():
                    message += '\n' + lines[i].strip()
                    i += 1
                    
                self.add_user_message(message)
                
            elif line.startswith("AI:"):
                message = line[3:].strip()
                
                i += 1
                while i < len(lines) and lines[i].strip():
                    message += '\n' + lines[i].strip()
                    i += 1
                    
                self.add_assistant_message(message)
                
            else:
                i += 1
        
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def changeEvent(self, event):
        if event.type() == event.Type.PaletteChange:
            self.refresh_chat_display()
        super().changeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OllamaClientApp()
    window.show()
    sys.exit(app.exec())
