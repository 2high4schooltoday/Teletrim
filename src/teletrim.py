import sys
import base64
import os
import asyncio
import threading
import glob
import json
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QDialog, QWidget, QPushButton, QLineEdit, QLabel,
    QVBoxLayout, QHBoxLayout, QMessageBox, QListWidget, QListWidgetItem, QCheckBox,
    QSplitter, QScrollArea, QInputDialog, QFrame
)
from PyQt6.QtGui import QFont, QBrush, QColor, QIcon, QPixmap
from PyQt6.QtCore import Qt, QTimer, QByteArray

from icon_data import ICON_DATA

from telethon import TelegramClient, errors
from telethon.tl.functions.messages import DeleteHistoryRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import User

###############################################################################
# Global Warning Preference Flags
WARN_SESSION_DELETE = True   
WARN_CHANNEL_DELETE = True   
###############################################################################

# Async helper functions.
def start_event_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def safe_disconnect_async(client):
    if client.is_connected():
        await client.disconnect()

def safe_connect(client, loop, retries=3, delay=0.5):
    for attempt in range(retries):
        try:
            fut = asyncio.run_coroutine_threadsafe(client.connect(), loop)
            fut.result(timeout=30)
            return True
        except Exception as e:
            if "database is locked" in str(e):
                print(f"Database is locked, retrying in {delay} seconds... (attempt {attempt+1})")
                time.sleep(delay)
            else:
                raise e
    return False

###############################################################################
# Configuration persistence functions.
###############################################################################

def get_config_path(session_name):
    session_dir = os.path.join(os.getcwd(), "sessions")
    return os.path.join(session_dir, session_name + ".json")

def load_session_config(session_name):
    cfg_path = get_config_path(session_name)
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading session config: {e}")
    return None

def save_session_config(session_name, config):
    session_dir = os.path.join(os.getcwd(), "sessions")
    if not os.path.exists(session_dir):
        os.makedirs(session_dir)
    cfg_path = os.path.join(session_dir, session_name + ".json")
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
    except Exception as e:
        print(f"Error saving session config: {e}")

###############################################################################
# MessageBubble: Displays a single message bubble.
###############################################################################

class MessageBubble(QFrame):
    def __init__(self, message_text=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("""
            QFrame {
                background-color: #3A3A3A;
                border: none;
                border-radius: 10px;
                padding: 8px;
            }
            QLabel {
                font-size: 14px;
                color: #FFFFFF;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)
        label = QLabel(message_text)
        label.setWordWrap(True)
        layout.addWidget(label)

###############################################################################
# PreferencesDialog: Allows toggling warnings for deletion actions.
###############################################################################

class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(300, 150)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.session_warn_cb = QCheckBox("Warn before deleting sessions")
        self.session_warn_cb.setChecked(WARN_SESSION_DELETE)
        self.channel_warn_cb = QCheckBox("Warn before deleting channels")
        self.channel_warn_cb.setChecked(WARN_CHANNEL_DELETE)
        layout.addWidget(self.session_warn_cb)
        layout.addWidget(self.channel_warn_cb)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        for btn in (ok_btn, cancel_btn):
            btn.setStyleSheet("border-radius: 6px; background-color: #555555; color: white; padding: 6px 12px;")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

    def get_preferences(self):
        return (self.session_warn_cb.isChecked(), self.channel_warn_cb.isChecked())

###############################################################################
# SessionManager: Dialog for selecting, creating, and deleting sessions.
###############################################################################

class SessionManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_session = None
        self.setWindowTitle("Session Manager")
        self.resize(400, 300)
        self.setup_ui()
        self.populate_sessions()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        header = QLabel("<b>Select a Session or Create a New One</b>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(header)
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("background-color: #2D2D2D; color: #FFFFFF;")
        layout.addWidget(self.list_widget)
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("Load Session")
        self.new_btn = QPushButton("New Session")
        self.delete_btn = QPushButton("Delete Session")
        for btn in (self.load_btn, self.new_btn, self.delete_btn):
            btn.setStyleSheet("border-radius: 6px; background-color: #555555; color: #FFFFFF; padding: 6px 12px;")
        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.new_btn)
        btn_layout.addWidget(self.delete_btn)
        layout.addLayout(btn_layout)
        self.load_btn.clicked.connect(self.load_session)
        self.new_btn.clicked.connect(self.new_session)
        self.delete_btn.clicked.connect(self.delete_session)
        self.setLayout(layout)
    
    def populate_sessions(self):
        self.list_widget.clear()
        session_dir = os.path.join(os.getcwd(), "sessions")
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
        session_files = glob.glob(os.path.join(session_dir, "*.session"))
        for filepath in session_files:
            name = os.path.splitext(os.path.basename(filepath))[0]
            self.list_widget.addItem(name)
    
    def load_session(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "No Session Selected", "Please select a session.")
            return
        self.selected_session = item.text()
        self.accept()
    
    def new_session(self):
        self.selected_session = None
        self.accept()
    
    def delete_session(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "No Session Selected", "Please select a session to delete.")
            return
        session_name = item.text()
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setText(f"Are you sure you want to delete session '{session_name}'?")
        msg_box.setWindowTitle("Confirm Deletion")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dont_warn_cb = QCheckBox("Don't show this warning again")
        dont_warn_cb.setEnabled(False)
        dont_warn_cb.setStyleSheet("color: #FFFFFF;")
        msg_box.setCheckBox(dont_warn_cb)
        response = msg_box.exec()
        if response != QMessageBox.StandardButton.Yes:
            return
        session_dir = os.path.join(os.getcwd(), "sessions")
        session_path = os.path.join(session_dir, session_name + ".session")
        cfg_path = os.path.join(session_dir, session_name + ".json")
        try:
            if os.path.exists(session_path):
                os.remove(session_path)
            if os.path.exists(cfg_path):
                os.remove(cfg_path)
            QMessageBox.information(self, "Deleted", f"Session '{session_name}' has been deleted.")
            self.populate_sessions()
        except Exception as e:
            QMessageBox.critical(self, "Deletion Error", f"Error deleting session: {e}")

###############################################################################
# LoginDialog: Performs auto-login if an existing session is provided.
###############################################################################

class LoginDialog(QDialog):
    def __init__(self, loop, session_name=None, parent=None):
        super().__init__(parent)
        self.loop = loop
        self.client = None
        self.api_ready = False
        self.session_name = session_name
        self.back_pressed = False
        self.setWindowTitle("Teletrim Login")
        self.resize(450, 500)
        self.setup_styles()
        self.setup_ui()
        if self.session_name is not None:
            config = load_session_config(self.session_name)
            if config:
                self.session_input.setText(self.session_name)
                self.session_input.setEnabled(False)
                self.api_id_input.setText(str(config.get("api_id", "")))
                self.api_hash_input.setText(config.get("api_hash", ""))
                self.phone_input.setText(config.get("phone", ""))
                self.password_input.setText(config.get("twofa", ""))
                self.question_widget.hide()
                self.inst_widget.hide()
                self.creds_widget.hide()
                QTimer.singleShot(100, self.attempt_auto_login)

    def setup_styles(self):
        style = """
            QDialog { background-color: #2D2D2D; }
            QLabel { font-size: 14px; color: #FFFFFF; font-family: 'Segoe UI', sans-serif; }
            QPushButton { background-color: #555555; color: #FFFFFF; border: none; padding: 6px 12px; border-radius: 6px; font-family: 'Segoe UI', sans-serif; }
            QPushButton:hover { background-color: #666666; }
            QLineEdit { padding: 6px; font-size: 14px; background-color: #444444; color: #FFFFFF; border: none; border-radius: 4px; font-family: 'Segoe UI', sans-serif; }
        """
        self.setStyleSheet(style)

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(15)
        # Question widget.
        self.question_widget = QWidget()
        q_layout = QVBoxLayout(self.question_widget)
        q_layout.setSpacing(12)
        self.inst_label = QLabel("Do you have access to Telegram API credentials (API ID and API Hash)?")
        self.inst_label.setWordWrap(True)
        self.inst_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        q_layout.addWidget(self.inst_label)
        btn_layout = QHBoxLayout()
        self.btn_yes = QPushButton("Yes")
        self.btn_no = QPushButton("No")
        btn_layout.addWidget(self.btn_yes)
        btn_layout.addWidget(self.btn_no)
        q_layout.addLayout(btn_layout)
        self.layout.addWidget(self.question_widget)
        self.btn_yes.clicked.connect(self.handle_yes)
        self.btn_no.clicked.connect(self.handle_no)
        # Instructions widget with rich HTML/CSS for circles.
        self.inst_widget = QWidget()
        inst_layout = QVBoxLayout(self.inst_widget)
        inst_layout.setSpacing(10)
        header = QLabel("<b>Obtaining API Credentials</b>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFont(QFont("Segoe UI", 16))
        inst_layout.addWidget(header)
        instructions_html = """
        <div style="font-family: 'Segoe UI', sans-serif; font-size: 14px; color: #FFFFFF; line-height:1.5;">
          <p style="margin: 5px 0;">
            <span style="
              display: inline-block;
              width:32px; 
              height:32px; 
              border:2px solid #FFFFFF; 
              border-radius:50%;
              background-color: transparent; 
              text-align:center; 
              line-height:28px; 
              font-weight:bold; 
              color: #FFFFFF;
              margin-right:10px;
            ">1</span>
            Visit <a href="https://my.telegram.org" style="color: #99CCFF; text-decoration: none;">my.telegram.org</a>.
          </p>
          <p style="margin: 5px 0;">
            <span style="
              display: inline-block;
              width:32px; 
              height:32px; 
              border:2px solid #FFFFFF; 
              border-radius:50%;
              background-color: transparent; 
              text-align:center; 
              line-height:28px; 
              font-weight:bold; 
              color: #FFFFFF;
              margin-right:10px;
            ">2</span>
            Log in with your Telegram account.
          </p>
          <p style="margin: 5px 0;">
            <span style="
              display: inline-block;
              width:32px; 
              height:32px; 
              border:2px solid #FFFFFF; 
              border-radius:50%;
              background-color: transparent; 
              text-align:center; 
              line-height:28px; 
              font-weight:bold; 
              color: #FFFFFF;
              margin-right:10px;
            ">3</span>
            Navigate to the <b>API development tools</b> section.
          </p>
          <p style="margin: 5px 0;">
            <span style="
              display: inline-block;
              width:32px; 
              height:32px; 
              border:2px solid #FFFFFF; 
              border-radius:50%;
              background-color: transparent; 
              text-align:center; 
              line-height:28px; 
              font-weight:bold; 
              color: #FFFFFF;
              margin-right:10px;
            ">4</span>
            Create a new application to obtain your API ID and API Hash.
          </p>
        </div>
        """
        inst_text = QLabel(instructions_html)
        inst_text.setTextFormat(Qt.TextFormat.RichText)
        inst_text.setOpenExternalLinks(True)
        inst_layout.addWidget(inst_text)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.show_credentials_form)
        inst_layout.addWidget(self.next_btn)
        self.layout.addWidget(self.inst_widget)
        self.inst_widget.hide()
        # Credentials widget.
        self.creds_widget = QWidget()
        creds_layout = QVBoxLayout(self.creds_widget)
        creds_layout.setSpacing(10)
        self.session_label = QLabel("Session Name:")
        self.session_input = QLineEdit()
        if self.session_name is not None:
            self.session_input.setText(self.session_name)
            self.session_input.setEnabled(False)
        else:
            self.session_input.setPlaceholderText("Choose a unique session name")
        creds_layout.addWidget(self.session_label)
        creds_layout.addWidget(self.session_input)
        self.api_id_label = QLabel("API ID:")
        self.api_id_input = QLineEdit()
        self.api_id_input.setPlaceholderText("Enter your API ID (integer)")
        creds_layout.addWidget(self.api_id_label)
        creds_layout.addWidget(self.api_id_input)
        self.api_hash_label = QLabel("API Hash:")
        self.api_hash_input = QLineEdit()
        self.api_hash_input.setPlaceholderText("Enter your API Hash")
        creds_layout.addWidget(self.api_hash_label)
        creds_layout.addWidget(self.api_hash_input)
        self.phone_label = QLabel("Phone Number:")
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Enter your phone number (exclude country code)")
        creds_layout.addWidget(self.phone_label)
        creds_layout.addWidget(self.phone_input)
        self.password_label = QLabel("2FA Password (optional):")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter your 2FA password, if any")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        creds_layout.addWidget(self.password_label)
        creds_layout.addWidget(self.password_input)
        self.back_btn = QPushButton("Back to Session Manager")
        self.back_btn.clicked.connect(self.back_to_sessions)
        creds_layout.addWidget(self.back_btn)
        self.login_btn = QPushButton("Log In")
        self.login_btn.clicked.connect(self.do_login)
        creds_layout.addWidget(self.login_btn)
        self.layout.addWidget(self.creds_widget)
        self.creds_widget.hide()

    def handle_yes(self):
        self.question_widget.hide()
        self.inst_widget.hide()
        self.creds_widget.show()

    def handle_no(self):
        self.question_widget.hide()
        self.creds_widget.hide()
        self.inst_widget.show()

    def show_credentials_form(self):
        self.inst_widget.hide()
        self.creds_widget.show()

    def back_to_sessions(self):
        self.back_pressed = True
        self.reject()

    def attempt_auto_login(self):
        try:
            api_id = int(self.api_id_input.text().strip())
            api_hash = self.api_hash_input.text().strip()
        except ValueError:
            return
        phone = self.phone_input.text().strip()
        session_dir = os.path.join(os.getcwd(), "sessions")
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
        session_path = os.path.join("sessions", self.session_name)
        self.client = TelegramClient(session_path, api_id, api_hash, loop=self.loop)
        try:
            if not safe_connect(self.client, self.loop):
                print("Auto-connect failed: database is locked or connection error.")
                self.creds_widget.show()
                return
            fut = asyncio.run_coroutine_threadsafe(self.client.is_user_authorized(), self.loop)
            is_auth = fut.result(timeout=30)
            if is_auth:
                self.api_ready = True
                self.accept()
        except Exception as e:
            print("Auto-login failed:", e)
            self.creds_widget.show()

    def do_login(self):
        session_name = self.session_input.text().strip()
        if not session_name:
            QMessageBox.critical(self, "Input Error", "Please enter a session name.")
            return
        config = load_session_config(session_name)
        if config:
            self.api_id_input.setText(str(config.get("api_id", "")))
            self.api_hash_input.setText(config.get("api_hash", ""))
            self.phone_input.setText(config.get("phone", ""))
            self.password_input.setText(config.get("twofa", ""))
        try:
            api_id = int(self.api_id_input.text().strip())
        except ValueError:
            QMessageBox.critical(self, "Input Error", "API ID must be an integer.")
            return
        api_hash = self.api_hash_input.text().strip()
        phone = self.phone_input.text().strip()
        provided_password = self.password_input.text().strip() or None
        if not (api_hash and phone):
            QMessageBox.critical(self, "Input Error", "Please fill in all required fields.")
            return
        session_dir = os.path.join(os.getcwd(), "sessions")
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
        session_path = os.path.join("sessions", session_name)
        self.client = TelegramClient(session_path, api_id, api_hash, loop=self.loop)
        try:
            if not safe_connect(self.client, self.loop):
                QMessageBox.critical(self, "Connection Failed", "Could not connect: database is locked or error.")
                return
        except Exception as e:
            QMessageBox.critical(self, "Connection Failed", f"Could not connect: {e}")
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.client.is_user_authorized(), self.loop)
            is_auth = fut.result(timeout=30)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Authorization check failed: {e}")
            return
        if is_auth:
            self.api_ready = True
            self.accept()
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.client.send_code_request(phone), self.loop)
            fut.result(timeout=30)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send login code: {e}")
            return
        code, ok = QInputDialog.getText(self, "Enter Code", "Enter the Telegram login code:")
        if not ok or not code:
            QMessageBox.critical(self, "Input Error", "No login code provided.")
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.client.sign_in(phone, code), self.loop)
            fut.result(timeout=30)
        except errors.SessionPasswordNeededError:
            if provided_password:
                pwd = provided_password
            else:
                pwd, ok = QInputDialog.getText(self, "2FA Required", "Enter your 2FA password:", QLineEdit.EchoMode.Password)
                if not ok or not pwd:
                    QMessageBox.critical(self, "Error", "2FA password required.")
                    return
            try:
                fut = asyncio.run_coroutine_threadsafe(self.client.sign_in(password=pwd), self.loop)
                fut.result(timeout=30)
            except Exception as e:
                QMessageBox.critical(self, "Login Failed", f"Could not log in: {e}")
                return
        except Exception as e:
            QMessageBox.critical(self, "Login Failed", f"Could not log in: {e}")
            return
        self.api_ready = True
        cfg = {
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "twofa": provided_password or ""
        }
        save_session_config(session_name, cfg)
        self.accept()

###############################################################################
# MainWindow: The primary window for chats and message history.
###############################################################################

class MainWindow(QMainWindow):
    def __init__(self, client, loop):
        super().__init__()
        self.client = client
        self.loop = loop
        self.suppress_warning = False
        self.session_switch_requested = False
        self.setWindowTitle("Teletrim")
        self.resize(900, 600)
        self.setup_styles()
        self.init_ui()
        self.load_chats()

    def setup_styles(self):
        style = """
            QMainWindow { background-color: #2D2D2D; }
            QListWidget { font-size: 14px; background-color: #2D2D2D; color: #FFFFFF; }
            QPushButton { background-color: #555555; color: #FFFFFF; border: 1px solid #777777; padding: 6px 10px; border-radius: 6px; }
            QPushButton:hover { background-color: #666666; }
            QLabel { font-size: 14px; color: #FFFFFF; }
            QScrollArea { border: none; background-color: #2D2D2D; }
            QLineEdit { background-color: #444444; color: #FFFFFF; border: none; border-radius: 4px; }
        """
        self.setStyleSheet(style)

    def init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.chat_list_widget = QListWidget()
        self.chat_list_widget.itemChanged.connect(self.chat_item_changed)
        self.chat_list_widget.currentItemChanged.connect(self.chat_selection_changed)
        splitter.addWidget(self.chat_list_widget)
        self.message_widget = QWidget()
        self.message_layout = QVBoxLayout(self.message_widget)
        self.message_layout.setContentsMargins(10, 10, 10, 10)
        self.message_layout.setSpacing(10)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: #2D2D2D; border: none;")
        self.scroll.setWidget(self.message_widget)
        splitter.addWidget(self.scroll)
        main_layout.addWidget(splitter)
        btn_layout = QHBoxLayout()
        self.leave_btn = QPushButton("Leave Selected and Delete History")
        self.leave_btn.clicked.connect(self.leave_selected)
        btn_layout.addWidget(self.leave_btn)
        self.session_mgr_btn = QPushButton("Session Manager")
        self.session_mgr_btn.clicked.connect(self.show_session_manager)
        btn_layout.addWidget(self.session_mgr_btn)
        self.pref_btn = QPushButton("Preferences")
        self.pref_btn.clicked.connect(self.show_preferences)
        btn_layout.addWidget(self.pref_btn)
        self.about_btn = QPushButton("About")
        self.about_btn.clicked.connect(self.show_about)
        btn_layout.addWidget(self.about_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        self.setCentralWidget(central_widget)

    def load_chats(self):
        async def get_dialogs():
            return await self.client.get_dialogs()
        me = None
        try:
            me = asyncio.run_coroutine_threadsafe(self.client.get_me(), self.loop).result(timeout=10)
            print("Current user ID:", me.id)
        except Exception as e:
            print("Error getting current user:", e)
        try:
            fut = asyncio.run_coroutine_threadsafe(get_dialogs(), self.loop)
            dialogs = fut.result(timeout=30)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to retrieve chats: {e}")
            return
        self.chat_list_widget.clear()
        for d in dialogs:
            entity = d.entity
            is_saved = False
            # If the entity has an id and it matches the current user's id, it's Saved Messages.
            if hasattr(entity, "id") and me and entity.id == me.id:
                name = "Saved Messages"
                is_saved = True
            else:
                name = d.name.strip() if d.name and d.name.strip() else ""
                if not name and isinstance(entity, User):
                    if (not getattr(entity, "first_name", None) and not getattr(entity, "last_name", None)) or (getattr(entity, "first_name", "") == "Deleted Account"):
                        name = "[Deleted Account]"
                    else:
                        name = "[Unknown]"
                elif not name:
                    name = "[Unknown]"
            item = QListWidgetItem(name)
            item.setForeground(QBrush(QColor("#FFFFFF")))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, entity)
            item.setData(Qt.ItemDataRole.UserRole + 1, is_saved)
            self.chat_list_widget.addItem(item)

    def chat_item_changed(self, item):
        is_saved = item.data(Qt.ItemDataRole.UserRole + 1)
        if is_saved:
            if item.checkState() == Qt.CheckState.Checked:
                reply = QMessageBox.question(
                    self,
                    "Warning: Saved Messages",
                    "You have selected the Saved Messages chat. You cannot leave this chat—you can only clear its history. Do you want to include it for history deletion?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    item.setCheckState(Qt.CheckState.Unchecked)

    def chat_selection_changed(self, current, previous):
        if not current:
            return
        entity = current.data(Qt.ItemDataRole.UserRole)
        async def get_messages():
            return await self.client.get_messages(entity, limit=10)
        try:
            fut = asyncio.run_coroutine_threadsafe(get_messages(), self.loop)
            messages = fut.result(timeout=30)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load messages: {e}")
            return
        while self.message_layout.count():
            child = self.message_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for msg in reversed(messages):
            if msg.photo:
                bubble = MessageBubble("[Image]")
            elif msg.voice:
                bubble = MessageBubble("[Voice Message]")
            elif msg.document:
                bubble = MessageBubble("[File Message]")
            else:
                bubble = MessageBubble(msg.message or "[No Text]")
            self.message_layout.addWidget(bubble)
        self.message_layout.addStretch()

    def leave_selected(self):
        selected = []
        for idx in range(self.chat_list_widget.count()):
            item = self.chat_list_widget.item(idx)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item)
        if not selected:
            QMessageBox.information(self, "No Chats Selected", "Please select at least one chat or channel.")
            return
        global WARN_CHANNEL_DELETE
        if WARN_CHANNEL_DELETE:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setText("The selected chats/channels will be left and their message history deleted permanently.")
            msg_box.setWindowTitle("Confirm Leave")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            check_box = QCheckBox("Don't show this warning again")
            check_box.setStyleSheet("color: #ffffff;")
            msg_box.setCheckBox(check_box)
            response = msg_box.exec()
            if response != QMessageBox.StandardButton.Ok:
                return
            if check_box.isChecked():
                WARN_CHANNEL_DELETE = False
        for item in selected:
            entity = item.data(Qt.ItemDataRole.UserRole)
            is_saved = item.data(Qt.ItemDataRole.UserRole + 1)
            if is_saved:
                reply = QMessageBox.question(
                    self,
                    "Warning: Saved Messages",
                    "Saved Messages cannot be left. Would you like to clear its history instead?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    async def clear_saved():
                        try:
                            await self.client(DeleteHistoryRequest(peer=entity, max_id=0, revoke=True))
                        except Exception as e:
                            print(f"Error clearing history for Saved Messages: {e}")
                    try:
                        asyncio.run_coroutine_threadsafe(clear_saved(), self.loop).result(timeout=30)
                    except Exception as e:
                        print(f"Failed to clear history for Saved Messages: {e}")
                continue
            else:
                async def delete_history(entity):
                    try:
                        await self.client(DeleteHistoryRequest(peer=entity, max_id=0, revoke=True))
                    except Exception as e:
                        print(f"Error deleting history for {entity}: {e}")
                try:
                    asyncio.run_coroutine_threadsafe(delete_history(entity), self.loop).result(timeout=30)
                except Exception as e:
                    print(f"Failed to delete history: {e}")
                async def leave_chat(entity):
                    try:
                        await self.client(LeaveChannelRequest(entity))
                    except Exception as e:
                        print(f"Error leaving channel {entity}: {e}")
                try:
                    asyncio.run_coroutine_threadsafe(leave_chat(entity), self.loop).result(timeout=30)
                except Exception as e:
                    print(f"Failed to leave chat: {e}")
        self.load_chats()
        QMessageBox.information(self, "Operation Completed", "Selected chats/channels have been processed.")

    def show_preferences(self):
        pref_dialog = PreferencesDialog(self)
        if pref_dialog.exec() == QDialog.DialogCode.Accepted:
            global WARN_SESSION_DELETE, WARN_CHANNEL_DELETE
            WARN_SESSION_DELETE, WARN_CHANNEL_DELETE = pref_dialog.get_preferences()

    def show_about(self):
        about_html = """
        <div style="font-family: 'Segoe UI', sans-serif; font-size: 14px; color: #FFFFFF;">
          <p>
            <a href="https://github.com/2high4schooltoday/Teletrim" style="color: #99CCFF; text-decoration:none; font-weight: bold;">Teletrim</a>
            is a desktop tool that helps you quickly leave unwanted Telegram chats and channels — and wipe their message history — in just a few clicks.
          </p>
          <p>
            Created by <a href="https://2high4schooltoday.ru" style="color: #99CCFF; text-decoration:none;">2high4schooltoday</a>.
          </p>
          <p>
            Distributed under <a href="https://www.gnu.org/licenses/gpl-3.0.html" style="color: #99CCFF; text-decoration:none;">GNU GPL v3</a>.
          </p>
        </div>
        """
        about_dialog = QDialog(self)
        about_dialog.setWindowTitle("About Teletrim")
        layout = QVBoxLayout(about_dialog)
        label = QLabel(about_html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)
        layout.addWidget(label)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("border-radius: 6px; background-color: #555555; color: white; padding: 6px 12px;")
        close_btn.clicked.connect(about_dialog.accept)
        layout.addWidget(close_btn)
        about_dialog.exec()

    def show_session_manager(self):
        reply = QMessageBox.question(
            self, "Session Manager",
            "Are you sure you want to return to the session manager?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                asyncio.run_coroutine_threadsafe(safe_disconnect_async(self.client), self.loop).result(timeout=10)
            except Exception as e:
                print("Error during disconnect:", e)
            self.session_switch_requested = True
            self.close()
            QApplication.quit()

###############################################################################
# Main entry point.
###############################################################################

def main():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=start_event_loop, args=(loop,), daemon=True)
    t.start()
    app = QApplication(sys.argv)
    # Convert base64 to QIcon
    icon_bytes = QByteArray.fromBase64(ICON_DATA.encode('utf-8'))
    pixmap = QPixmap()
    pixmap.loadFromData(icon_bytes)
    icon = QIcon(pixmap)
    app.setWindowIcon(icon)
    while True:
        session_mgr = SessionManager()
        if session_mgr.exec() == QDialog.DialogCode.Accepted:
            chosen_session = session_mgr.selected_session
        else:
            sys.exit(0)
        login_dialog = LoginDialog(loop, session_name=chosen_session)
        login_dialog.back_pressed = False
        result = login_dialog.exec()
        if result == QDialog.DialogCode.Accepted and login_dialog.api_ready:
            main_window = MainWindow(login_dialog.client, loop)
            main_window.show()
            ret = app.exec()
            if ret == 42 or main_window.session_switch_requested:
                continue
            else:
                asyncio.run_coroutine_threadsafe(safe_disconnect_async(login_dialog.client), loop)
                sys.exit(ret)
        else:
            if login_dialog.back_pressed:
                continue
            else:
                sys.exit(0)

if __name__ == "__main__":
    main()
