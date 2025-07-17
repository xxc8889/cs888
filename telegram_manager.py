import sys
import os
import json
import asyncio
import random
from datetime import datetime
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import logging
from pathlib import Path
from config_manager import ConfigManager
from device_manager_dialog import DeviceManagerDialog
import shutil
import threading
import queue
# 设置日志
Path('logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class AsyncEventLoopThread(QThread):
    """专门用于运行异步事件循环的线程"""
    def __init__(self):
        super().__init__()
        self.loop = None
        
    def run(self):
        """运行事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        
    def stop(self):
        """停止事件循环"""
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.wait()

class LoginDialog(QDialog):
    """登录对话框"""
    login_success = pyqtSignal(str, str, str)  # phone, code, password
    
    def __init__(self, parent, phone, api_configs, saved_passwords=None):
        super().__init__(parent)
        self.phone = phone
        self.api_configs = api_configs
        self.saved_passwords = saved_passwords or {}
        
        # 解析手机号和API链接
        if '----' in phone:
            parts = phone.split('----')
            self.actual_phone = parts[0]  # +2347046149483
            self.api_url = parts[1]       # API链接
        else:
            self.actual_phone = phone
            self.api_url = None  # 手动添加账号没有API链接
        
        # 只有在有API链接时才设置定时器
        if self.api_url:
            # 定时器（仅API接码时使用）
            self.fetch_code_timer = QTimer()
            self.fetch_code_timer.setSingleShot(True)
            self.fetch_code_timer.timeout.connect(self.fetch_verification_code)
            
            self.fetch_password_timer = QTimer()
            self.fetch_password_timer.setSingleShot(True)
            self.fetch_password_timer.timeout.connect(self.fetch_two_factor_password)
            
            # 重试计数
            self.code_retry = 0
            self.password_retry = 0
            self.max_retries = 1  # 最多重试1次
        
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle(f"添加账号 - {self.actual_phone}")
        self.setModal(True)
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        
        # API选择
        api_group = QGroupBox()
        api_layout = QFormLayout(api_group)

        self.api_combo = QComboBox()

        # 如果只有一个配置，直接使用（自动分配的情况）
        if len(self.api_configs) == 1:
            config = self.api_configs[0]
            text = f"{config['api_id']} - {config['api_hash'][:10]}... (自动分配)"
            self.api_combo.addItem(text, config)
            self.api_combo.setEnabled(False)  # 禁用选择
            self.api_combo.setToolTip("API配置已自动分配")
        else:
            # 多个配置时显示选择界面
            for i, config in enumerate(self.api_configs):
                # 检查是否已被有效账号使用
                valid_statuses = ['在线', '离线', '未检测']
                is_used = any(
                    acc.get('api_id') == config['api_id'] and 
                    acc.get('status', '') in valid_statuses
                    for acc in self.parent().accounts.values()
                )
                
                text = f"{config['api_id']} - {config['api_hash'][:10]}..."
                if is_used:
                    text += " (已使用)"
                    
                self.api_combo.addItem(text, config)
                
                # 如果已使用则设为灰色
                if is_used:
                    item = self.api_combo.model().item(i)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setData(QColor('gray'), Qt.ItemDataRole.ForegroundRole)

        api_layout.addRow("API配置:", self.api_combo)
        layout.addWidget(api_group)
        
        # 验证信息
        verify_group = QGroupBox()
        verify_layout = QFormLayout(verify_group)
        
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("请先获取验证码")
        self.code_input.setEnabled(False)
        verify_layout.addRow("验证码:", self.code_input)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("二次验证密码(如果有)")
        
        # 如果有保存的密码，自动填入
        if self.phone in self.saved_passwords:
            self.password_input.setText(self.saved_passwords[self.phone])
        
        verify_layout.addRow("二次验证密码:", self.password_input)
        layout.addWidget(verify_group)
        
        # 状态显示
        self.status_label = QLabel("点击'获取验证码'开始")
        self.status_label.setStyleSheet("color: blue; padding: 10px;")
        layout.addWidget(self.status_label)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.get_code_btn = QPushButton("获取验证码")
        self.get_code_btn.clicked.connect(self.get_verification_code)
        button_layout.addWidget(self.get_code_btn)
        
        self.login_btn = QPushButton("确认登录")
        self.login_btn.clicked.connect(self.confirm_login)
        self.login_btn.setEnabled(False)
        button_layout.addWidget(self.login_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
    
    def get_verification_code(self):
        """获取验证码"""
        selected_config = self.api_combo.currentData()
        if not selected_config:
            QMessageBox.warning(self, "错误", "请选择API配置")
            return
        
        self.get_code_btn.setEnabled(False)
        self.status_label.setText("正在发送验证码...")
        self.code_retry = 0  # 重置重试计数
        
        # 在异步处理器中发送验证码
        async def send_code():
            try:
                success = await self.parent().async_handler.send_verification_code(
                    self.actual_phone.replace('+', ''), selected_config['api_id'], selected_config['api_hash']
                )
                
                QMetaObject.invokeMethod(
                    self, "on_code_sent",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(bool, success)
                )
            except Exception as e:
                import traceback
                error_msg = f"发送验证码异常: {str(e)}\n详细错误: {traceback.format_exc()}"
                print(error_msg)
                QMetaObject.invokeMethod(
                    self, "on_code_error",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, error_msg)
                )
        
        asyncio.run_coroutine_threadsafe(send_code(), self.parent().event_loop_thread.loop)
    
    @pyqtSlot(bool)
    def on_code_sent(self, success):
        """验证码发送完成"""
        if success:
            if self.api_url:
                # API接码登录：验证码发送成功，等待后获取
                self.status_label.setText("验证码发送成功，8秒后自动获取...")
                self.status_label.setStyleSheet("color: green; padding: 10px;")
                self.code_input.setEnabled(True)
                self.login_btn.setEnabled(False)
                
                # 8秒后开始获取验证码
                self.fetch_code_timer.start(8000)
            else:
                # 手动添加账号：验证码发送成功，等待手动输入
                self.status_label.setText("验证码发送成功，请手动输入")
                self.status_label.setStyleSheet("color: green; padding: 10px;")
                self.code_input.setEnabled(True)
                self.login_btn.setEnabled(True)
                self.code_input.setFocus()
        else:
            # 发送失败
            self.status_label.setText("验证码发送失败，请检查号码或重试")
            self.status_label.setStyleSheet("color: red; padding: 10px;")
            self.get_code_btn.setEnabled(True)

    @pyqtSlot(str)
    def on_code_error(self, error):
        """验证码发送错误"""
        self.status_label.setText(f"错误: {error}")
        self.status_label.setStyleSheet("color: red; padding: 10px;")
        self.get_code_btn.setEnabled(True)

    @pyqtSlot(bool, str, str)
    def on_login_complete(self, success, api_id, api_hash):
        """登录完成"""
        if success:
            self.status_label.setText("登录成功！")
            self.status_label.setStyleSheet("color: green; padding: 10px;")
            
            # 自动保存二次验证密码
            password = self.password_input.text().strip()
            if password:
                self.parent().config_manager.save_password(self.actual_phone.replace('+', ''), password)
                self.parent().log(f"已保存二次验证密码: {self.actual_phone}")
            
            # 添加账号到主程序（使用实际手机号）
            self.parent().add_account_success(self.actual_phone.replace('+', ''), api_id, api_hash)
            QTimer.singleShot(1000, self.accept)
        else:
            # 登录失败处理
            if self.actual_phone.replace('+', '') in self.parent().accounts:
                self.parent().remove_failed_account(self.actual_phone.replace('+', ''), "登录失败")

            self.status_label.setText("登录失败，请检查验证码")
            self.status_label.setStyleSheet("color: red; padding: 10px;")
            self.login_btn.setEnabled(True)

    @pyqtSlot()
    def handle_password_needed(self):
        """处理需要二次验证密码的情况"""
        # 首先检查是否有保存的密码
        saved_password = self.parent().config_manager.get_saved_password(self.actual_phone.replace('+', ''))
        if saved_password:
            self.password_input.setText(saved_password)
            self.status_label.setText("使用已保存的二次验证密码...")
            self.status_label.setStyleSheet("color: blue; padding: 10px;")
            QTimer.singleShot(1000, self.confirm_login)
            return
        
        # 没有保存的密码且有API链接，自动获取
        if self.api_url:
            self.status_label.setText("需要二次验证密码，2秒后自动获取...")
            self.status_label.setStyleSheet("color: orange; padding: 10px;")
            self.password_retry = 0
            self.fetch_password_timer.start(2000)  # 2秒后获取
        else:
            # 没有API链接，手动输入
            self.status_label.setText("需要二次验证密码，请手动输入")
            self.status_label.setStyleSheet("color: orange; padding: 10px;")
            self.login_btn.setEnabled(True)
            self.password_input.setFocus()
    @pyqtSlot(str)
    def on_code_error(self, error):
        """验证码发送错误"""
        self.status_label.setText(f"错误: {error}")
        self.status_label.setStyleSheet("color: red; padding: 10px;")
        self.get_code_btn.setEnabled(True)
    
    def confirm_login(self):
        """确认登录"""
        code = self.code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "错误", "请输入验证码")
            return
        
        password = self.password_input.text().strip()
        selected_config = self.api_combo.currentData()
        
        self.login_btn.setEnabled(False)
        self.status_label.setText("正在登录...")
        
        # 保存密码到内存和配置
        if password:
            self.parent().config_manager.save_password(self.actual_phone.replace('+', ''), password)
        
        # 执行登录
        async def do_login():
            try:
                success = await self.parent().async_handler.complete_login(
                    self.actual_phone.replace('+', ''), selected_config['api_id'], selected_config['api_hash'], 
                    code, password
                )
                
                QMetaObject.invokeMethod(
                    self, "on_login_complete",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(bool, success),
                    Q_ARG(str, selected_config['api_id']),
                    Q_ARG(str, selected_config['api_hash'])
                )
            except Exception as e:
                error_msg = str(e)
                
                # 检查是否需要二次验证密码
                if "SessionPasswordNeededError" in error_msg or "需要两步验证密码" in error_msg:
                    QMetaObject.invokeMethod(
                        self, "handle_password_needed",
                        Qt.ConnectionType.QueuedConnection
                    )
                else:
                    import traceback
                    full_error = f"登录异常: {error_msg}\n详细错误: {traceback.format_exc()}"
                    print(full_error)
                    QMetaObject.invokeMethod(
                        self, "on_login_error", 
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, full_error)
                    )
        
        asyncio.run_coroutine_threadsafe(do_login(), self.parent().event_loop_thread.loop)
    @pyqtSlot()
    def handle_password_needed(self):
        """处理需要二次验证密码的情况"""
        # 首先检查是否有保存的密码
        saved_password = self.parent().config_manager.get_saved_password(self.actual_phone.replace('+', ''))
        if saved_password:
            self.password_input.setText(saved_password)
            self.status_label.setText("使用已保存的二次验证密码...")
            self.status_label.setStyleSheet("color: blue; padding: 10px;")
            QTimer.singleShot(1000, self.confirm_login)
            return
        
        # 没有保存的密码且有API链接，自动获取
        if self.api_url:
            self.status_label.setText("需要二次验证密码，2秒后自动获取...")
            self.status_label.setStyleSheet("color: orange; padding: 10px;")
            self.password_retry = 0
            self.fetch_password_timer.start(2000)  # 2秒后获取
        else:
            # 没有API链接，手动输入
            self.status_label.setText("需要二次验证密码，请手动输入")
            self.status_label.setStyleSheet("color: orange; padding: 10px;")
            self.login_btn.setEnabled(True)
            self.password_input.setFocus()
    
    def fetch_verification_code(self):
        """通过API获取验证码"""
        if not self.api_url:
            # 手动添加账号不使用API获取
            return
        
        self.code_retry += 1
        self.status_label.setText(f"正在获取验证码... (第{self.code_retry}次)")
        
        code = self.call_api_get_code()
        
        if code:
            # 获取成功
            self.code_input.setText(code)
            self.status_label.setText("验证码获取成功，正在自动登录...")
            self.status_label.setStyleSheet("color: green; padding: 10px;")
            self.login_btn.setEnabled(True)
            
            # 自动点击登录按钮
            QTimer.singleShot(1000, self.confirm_login)
            
        else:
            # 获取失败
            if self.code_retry < self.max_retries:
                self.status_label.setText(f"验证码获取失败，60秒后重试... (第{self.code_retry}/{self.max_retries}次)")
                self.status_label.setStyleSheet("color: orange; padding: 10px;")
                
                # 60秒后重试
                retry_timer = QTimer()
                retry_timer.setSingleShot(True)
                retry_timer.timeout.connect(self.fetch_verification_code)
                retry_timer.start(60000)
                
            else:
                # 超过最大重试次数，跳过
                self.status_label.setText("验证码获取失败，已跳过")
                self.status_label.setStyleSheet("color: red; padding: 10px;")
                self.get_code_btn.setEnabled(True)
                self.login_btn.setEnabled(True)

    def fetch_two_factor_password(self):
        """通过API获取二次验证密码"""
        if not self.api_url:
            # 手动添加账号不使用API获取
            return
        
        self.password_retry += 1
        self.status_label.setText(f"正在获取二次验证密码... (第{self.password_retry}次)")
        
        password = self.call_api_get_password()
        
        if password:
            # 获取成功
            self.password_input.setText(password)
            self.status_label.setText("二次验证密码获取成功，正在重新登录...")
            self.status_label.setStyleSheet("color: green; padding: 10px;")
            
            # 重新尝试登录
            QTimer.singleShot(1000, self.confirm_login)
            
        else:
            # 获取失败
            if self.password_retry < self.max_retries:
                self.status_label.setText(f"密码获取失败，60秒后重试... (第{self.password_retry}/{self.max_retries}次)")
                self.status_label.setStyleSheet("color: orange; padding: 10px;")
                
                # 60秒后重试
                retry_timer = QTimer()
                retry_timer.setSingleShot(True)
                retry_timer.timeout.connect(self.fetch_two_factor_password)
                retry_timer.start(60000)
                
            else:
                # 超过重试次数，跳过
                self.status_label.setText("二次验证密码获取失败，已跳过")
                self.status_label.setStyleSheet("color: red; padding: 10px;")
                self.login_btn.setEnabled(True)

    def call_api_get_code(self):
        """调用API获取验证码"""
        if not self.api_url:
            return None
            
        try:
            import requests
            
            response = requests.get(self.api_url, timeout=10)
            
            if response.status_code == 200:
                content = response.text
                self.parent().log(f"API响应内容: {content[:200]}...")
                
                # 尝试提取验证码
                import re
                patterns = [
                    r'验证码[:：]\s*(\d{5,6})',
                    r'code[:：]\s*(\d{5,6})',
                    r'(\d{5,6})',
                    r'验证码.*?(\d{5,6})',
                    r'Telegram.*?(\d{5,6})'
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        code = match.group(1)
                        self.parent().log(f"从API提取到验证码: {code}")
                        return code
                
                self.parent().log("API响应中未找到验证码")
                return None
            else:
                self.parent().log(f"API请求失败，状态码: {response.status_code}")
                return None
                
        except Exception as e:
            self.parent().log(f"调用API获取验证码异常: {e}")
            return None

    def call_api_get_password(self):
        """调用API获取二次验证密码"""
        if not self.api_url:
            return None
            
        try:
            import requests
            
            response = requests.get(self.api_url, timeout=10)
            
            if response.status_code == 200:
                content = response.text
                
                # 从HTML中提取密码
                import re
                
                # 尝试多种密码格式
                patterns = [
                    r'密码[:：]\s*([A-Za-z0-9]+)',
                    r'password[:：]\s*([A-Za-z0-9]+)',
                    r'二次验证[:：]\s*([A-Za-z0-9]+)',
                    r'验证码[:：]\s*([A-Za-z0-9]{8,})',  # 8位以上可能是密码
                    r'([A-Za-z0-9]{8,})'  # 最后尝试8位以上的字母数字组合
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        password = match.group(1)
                        # 验证密码长度（通常二次验证密码较长）
                        if len(password) >= 8:
                            self.parent().log(f"获取到二次验证密码: {password}")
                            return password
                
                self.parent().log(f"未在API响应中找到密码: {content[:200]}...")
                return None
            else:
                self.parent().log(f"API请求失败，状态码: {response.status_code}")
                return None
                
        except Exception as e:
            self.parent().log(f"调用API获取密码失败: {e}")
            return None
    @pyqtSlot(bool, str, str)
    def on_login_complete(self, success, api_id, api_hash):
        """登录完成"""
        if success:
            self.status_label.setText("登录成功！")
            self.status_label.setStyleSheet("color: green; padding: 10px;")
            
            # 自动保存二次验证密码
            password = self.password_input.text().strip()
            if password:
                self.parent().config_manager.save_password(self.actual_phone.replace('+', ''), password)
                self.parent().log(f"已保存二次验证密码: {self.actual_phone}")
            
            # 添加账号到主程序（使用实际手机号）
            self.parent().add_account_success(self.actual_phone.replace('+', ''), api_id, api_hash)
            QTimer.singleShot(1000, self.accept)
        else:
            # 登录失败处理
            if self.actual_phone.replace('+', '') in self.parent().accounts:
                self.parent().remove_failed_account(self.actual_phone.replace('+', ''), "登录失败")

            self.status_label.setText("登录失败，请检查验证码")
            self.status_label.setStyleSheet("color: red; padding: 10px;")
            self.login_btn.setEnabled(True)
    def reject(self):
        """取消登录"""
        # 如果账号已被添加但登录未完成，移除它
        if self.phone in self.parent().accounts:
            self.parent().remove_failed_account(self.phone, "取消登录")
    
        super().reject()

class TaskListDialog(QDialog):
    """任务列表对话框"""
    stop_task = pyqtSignal(str, str)  # phone, task_type
    
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("任务列表")
        self.setModal(False)
        self.setMinimumSize(600, 400)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 任务表格
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(4)
        self.task_table.setHorizontalHeaderLabels(["账号", "任务类型", "状态", "操作"])
        self.task_table.horizontalHeader().setStretchLastSection(True)

        #设置列宽调整行为
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # 账号根据内容调整宽度
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 任务类型自动伸缩
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # 状态根据内容调整宽度
        self.task_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 操作固定宽度
        self.task_table.setColumnWidth(3, 100)  # 设置操作列宽度
        layout.addWidget(self.task_table)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_tasks)
        button_layout.addWidget(refresh_btn)
        
        stop_all_btn = QPushButton("停止所有任务")
        stop_all_btn.clicked.connect(self.stop_all_tasks)
        button_layout.addWidget(stop_all_btn)
        
        layout.addLayout(button_layout)
        
        self.refresh_tasks()
    
    def refresh_tasks(self):
        """刷新任务列表"""
        # 获取主窗口的运行中任务
        main_window = self.parent()
        if not hasattr(main_window, 'running_tasks'):
            main_window.running_tasks = {}
        
        self.task_table.setRowCount(len(main_window.running_tasks))
        
        for row, (task_key, task_info) in enumerate(main_window.running_tasks.items()):
            phone, task_type = task_key.split('_', 1)
            
            self.task_table.setItem(row, 0, QTableWidgetItem(phone))
            self.task_table.setItem(row, 1, QTableWidgetItem(task_info.get('name', task_type)))
            self.task_table.setItem(row, 2, QTableWidgetItem(task_info.get('status', '运行中')))
            
            # 停止按钮
            stop_btn = QPushButton("停止")
            stop_btn.clicked.connect(lambda checked, p=phone, t=task_type: self.stop_task.emit(p, t))
            self.task_table.setCellWidget(row, 3, stop_btn)
    
    def stop_all_tasks(self):
        """停止所有任务"""
        main_window = self.parent()
        if main_window.async_handler:
            asyncio.run_coroutine_threadsafe(
                main_window.async_handler.stop_all_tasks(),
                main_window.event_loop_thread.loop
            )
        main_window.running_tasks.clear()
        self.refresh_tasks()

class APILoginDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.accounts = parent.accounts
        self.config_manager = parent.config_manager
        self.async_handler = parent.async_handler
        self.event_loop_thread = parent.event_loop_thread
        
        # ✅ 关键修复：添加API分配锁和分配记录
        self.api_allocation_lock = threading.Lock()  # 线程锁
        self.allocated_api_ids = set()  # 记录已分配的API ID
        
        self.setupUI()
    
        # 用于存储正在处理的账号和链接
        self.processing_accounts = {}
        self.timers = {}  # 存储轮询计时器
        
    def setupUI(self):
        self.setWindowTitle("API接码登录")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        
        layout = QVBoxLayout(self)
        
        # 账号输入部分
        input_group = QGroupBox()
        input_layout = QVBoxLayout(input_group)
        
        description_label = QLabel("请输入账号和API链接，格式: +手机号----API链接，每行一个")
        description_label.setStyleSheet("color: gray;")
        input_layout.addWidget(description_label)
        
        self.accounts_input = QTextEdit()
        self.accounts_input.setPlaceholderText("+2347044588360----https://tgapi.feijige.shop/tgapi5/9baf59b2-d2c5-4c0c-926d-fe1747faae96/GetHTML\n+2347044639036----https://tgapi.feijige.shop/tgapi5/9ab3302b-e3c9-431d-8dc9-bd11b510a05c/GetHTML")
        input_layout.addWidget(self.accounts_input)
        
        layout.addWidget(input_group)
        
        # 状态显示
        status_group = QGroupBox()
        status_layout = QVBoxLayout(status_group)
        
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(4)
        self.status_table.setHorizontalHeaderLabels(["手机号", "API链接", "状态", "操作"])
        self.status_table.horizontalHeader().setStretchLastSection(True)
        self.status_table.setColumnWidth(0, 150)
        self.status_table.setColumnWidth(1, 300)
        self.status_table.setColumnWidth(2, 150)
        # 设置列宽调整行为
        self.status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # 手机号根据内容调整宽度
        self.status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # API链接自动伸缩
        self.status_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # 状态根据内容调整宽度
        self.status_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 操作固定宽度
        self.status_table.setColumnWidth(3, 100)  # 操作列宽度
        status_layout.addWidget(self.status_table)
        
        layout.addWidget(status_group)
        
        # 按钮部分
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("开始登录")
        self.start_btn.clicked.connect(self.start_login_process)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("停止所有")
        self.stop_btn.clicked.connect(self.stop_all_logins)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)
        
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def parse_accounts(self):
        """解析输入的账号信息"""
        text = self.accounts_input.toPlainText().strip()
        if not text:
            return []
        
        accounts = []
        for line in text.split("\n"):
            line = line.strip()
            if not line or "----" not in line:
                continue
            
            parts = line.split("----", 1)
            if len(parts) != 2:
                continue
            
            phone, api_url = parts
            phone = phone.strip().lstrip("+")
            api_url = api_url.strip()
            
            if phone and api_url:
                accounts.append((phone, api_url))
        
        return accounts
    
    def get_unused_api_config(self):
        """获取未使用的API配置 - 修复并发竞争条件版本"""
        # ✅ 使用线程锁确保API分配的原子性
        with self.api_allocation_lock:
            # 获取所有API配置
            api_configs = self.parent.config_manager.load_api_configs()
            if not api_configs:
                return None
            
            # 获取所有已使用的API ID
            valid_statuses = ['在线', '离线', '未检测', '未登录']
            used_api_ids = set()
            
            # 1. 从已有账号中获取使用的API ID
            for acc in self.accounts.values():
                api_id = acc.get('api_id')
                if api_id:
                    used_api_ids.add(str(api_id))
            
            # 2. 从当前对话框正在处理的账号中获取
            for phone, account_info in self.processing_accounts.items():
                if 'api_id' in account_info:
                    used_api_ids.add(str(account_info['api_id']))
            
            # ✅ 3. 从本次分配记录中获取（关键修复）
            used_api_ids.update(self.allocated_api_ids)
            
            self.parent.log(f"已使用的API ID: {used_api_ids}")
            self.parent.log(f"本次已分配的API ID: {self.allocated_api_ids}")
            
            # 查找未使用的API配置
            for config in api_configs:
                config_id = str(config['api_id'])
                if config_id not in used_api_ids:
                    # ✅ 立即标记为已分配，防止其他并发调用使用相同API
                    self.allocated_api_ids.add(config_id)
                    self.parent.log(f"分配API ID: {config_id} 给新账号")
                    return config
            
            # 如果没有未使用的，返回None
            self.parent.log("警告：没有可用的API配置")
            return None
    
    def start_login_process(self):
        """开始登录流程 - 增强版本"""
        accounts = self.parse_accounts()
        if not accounts:
            QMessageBox.warning(self, "警告", "没有有效的账号信息")
            return
        
        # ✅ 重置分配记录
        with self.api_allocation_lock:
            self.allocated_api_ids.clear()
        
        # 清空状态表格
        self.status_table.setRowCount(0)
        
        # 更新按钮状态
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        # 开始处理每个账号
        for i, (phone, api_url) in enumerate(accounts):
            if phone in self.parent.accounts:
                self.add_status_row(phone, api_url, "账号已存在")
                continue
            
            # 为每个账号选择未使用的API配置
            api_config = self.get_unused_api_config()
            if not api_config:
                self.add_status_row(phone, api_url, "无可用API配置")
                continue
            
            # 添加到状态表格
            row = self.add_status_row(phone, api_url, f"准备中... (API: {api_config['api_id']})")
            
            # 存储账号信息
            self.processing_accounts[phone] = {
                "api_url": api_url,
                "status": "准备中",
                "row": row,
                "api_id": api_config['api_id'],
                "api_hash": api_config['api_hash']
            }
            
            # 延迟启动每个账号的处理，避免同时发送太多请求
            QTimer.singleShot(i * 6000, lambda p=phone: self.process_account(p))
    
    def add_status_row(self, phone, api_url, status):
        """添加状态行到表格"""
        row = self.status_table.rowCount()
        self.status_table.insertRow(row)
        
        self.status_table.setItem(row, 0, QTableWidgetItem(phone))
        self.status_table.setItem(row, 1, QTableWidgetItem(api_url))
        self.status_table.setItem(row, 2, QTableWidgetItem(status))
        
        # 添加停止按钮
        stop_btn = QPushButton("停止")
        stop_btn.clicked.connect(lambda checked=False, p=phone: self.stop_account_login(p))
        self.status_table.setCellWidget(row, 3, stop_btn)
        
        return row
    
    def update_status(self, phone, status):
        """更新账号状态"""
        if phone in self.processing_accounts:
            row = self.processing_accounts[phone]["row"]
            self.status_table.setItem(row, 2, QTableWidgetItem(status))
            self.processing_accounts[phone]["status"] = status
    
    def process_account(self, phone):
        """处理单个账号"""
        if phone not in self.processing_accounts:
            return
        
        self.update_status(phone, "发送验证码...")
        
        # 获取账号信息
        account_info = self.processing_accounts[phone]
        api_id = account_info["api_id"]
        api_hash = account_info["api_hash"]
        
        # 重置重试计数
        self.processing_accounts[phone]["retry_count"] = 0
        
        self.parent.log(f"{phone} 开始发送验证码，API ID: {api_id}")
        
        # 在异步处理器中发送验证码
        async def send_code():
            try:
                self.parent.log(f"{phone} 调用异步发送验证码方法...")
                success = await self.parent.async_handler.send_verification_code(
                    phone, api_id, api_hash
                )
                
                self.parent.log(f"{phone} 验证码发送结果: {success}")
                
                if success:
                    QMetaObject.invokeMethod(
                        self, "on_code_sent",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone)
                    )
                else:
                    QMetaObject.invokeMethod(
                        self, "on_code_send_failed",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone),
                        Q_ARG(str, "发送验证码失败")
                    )
            except Exception as e:
                self.parent.log(f"{phone} 发送验证码异常: {str(e)}")
                import traceback
                self.parent.log(f"详细错误: {traceback.format_exc()}")
                QMetaObject.invokeMethod(
                    self, "on_code_send_failed",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, phone),
                    Q_ARG(str, str(e))
                )
        
        # 创建任务并保存引用，避免被垃圾回收
        task = asyncio.run_coroutine_threadsafe(send_code(), self.parent.event_loop_thread.loop)
        
        # 保存任务引用
        if not hasattr(self, 'running_tasks'):
            self.running_tasks = {}
        self.running_tasks[phone] = task
        
        self.parent.log(f"{phone} 验证码发送任务已提交")
    
    @pyqtSlot(str)
    def on_code_sent(self, phone):
        """验证码发送完成"""
        self.update_status(phone, "验证码已发送，等待获取...")
        self.parent.log(f"{phone} 验证码发送成功，开始轮询API获取")
        
        # 清理重试计时器
        if hasattr(self, 'retry_timers') and phone in self.retry_timers:
            self.retry_timers[phone].stop()
            del self.retry_timers[phone]
        
        # 开始轮询API获取验证码
        self.start_polling_api(phone)
    
    @pyqtSlot(str, str)
    def on_code_error(self, phone, error):
        """验证码发送错误"""
        self.update_status(phone, f"错误: {error}")
        self.stop_account_login(phone)
    
    def start_polling_api(self, phone):
        """开始轮询API获取验证码"""
        if phone not in self.processing_accounts:
            return
        
        # 初始化轮询计数
        self.processing_accounts[phone]["poll_count"] = 0
        self.processing_accounts[phone]["max_polls"] = 24  # 最多轮询24次（2分钟）
        
        # 创建计时器
        timer = QTimer(self)
        timer.timeout.connect(lambda: self.poll_api(phone))
        
        # 存储计时器
        if not hasattr(self, 'timers'):
            self.timers = {}
        self.timers[phone] = timer
        
        # 开始轮询
        timer.start(20000)  # 每20秒轮询一次
        self.parent.log(f"{phone} 开始轮询API获取验证码，最多轮询2分钟")
        self.poll_api(phone)  # 立即开始第一次轮询
    
    def poll_api(self, phone):
        """轮询API获取验证码和密码"""
        if phone not in self.processing_accounts:
            return
        
        account_info = self.processing_accounts[phone]
        api_url = account_info["api_url"]
        
        # 检查轮询次数
        poll_count = account_info.get("poll_count", 0)
        max_polls = account_info.get("max_polls", 24)
        
        if poll_count >= max_polls:
            # 超过最大轮询次数
            self.update_status(phone, "轮询超时，获取验证码失败")
            self.parent.log(f"{phone} 轮询超时，已轮询 {poll_count} 次")
            self.stop_account_login(phone)
            return
        
        # 更新轮询计数
        poll_count += 1
        self.processing_accounts[phone]["poll_count"] = poll_count
        
        self.update_status(phone, f"正在获取验证码... ({poll_count}/{max_polls})")
        
        # 创建网络请求
        import requests
        from threading import Thread
        
        def fetch_api():
            try:
                self.parent.log(f"{phone} 第 {poll_count} 次请求API: {api_url}")
                response = requests.get(api_url, timeout=10)
                
                if response.status_code == 200:
                    # 解析响应获取验证码和密码
                    QMetaObject.invokeMethod(
                        self, "parse_api_response",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone),
                        Q_ARG(str, response.text)
                    )
                else:
                    self.parent.log(f"{phone} API请求失败，状态码: {response.status_code}")
                    QMetaObject.invokeMethod(
                        self, "update_status",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone),
                        Q_ARG(str, f"API请求失败: {response.status_code}")
                    )
            except Exception as e:
                self.parent.log(f"{phone} API请求异常: {str(e)}")
                QMetaObject.invokeMethod(
                    self, "update_status",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, phone),
                    Q_ARG(str, f"API请求错误: {str(e)}")
                )
        
        # 在新线程中执行请求
        Thread(target=fetch_api, daemon=True).start()
    @pyqtSlot(str, str)
    def on_code_send_failed(self, phone, error):
        """验证码发送失败处理"""
        if phone not in self.processing_accounts:
            return
        
        account_info = self.processing_accounts[phone]
        retry_count = account_info.get("retry_count", 0)
        max_retries = 2  # 最多重试2次
        
        self.parent.log(f"{phone} 验证码发送失败: {error}, 重试次数: {retry_count}/{max_retries}")
        
        if retry_count < max_retries:
            # 重试发送验证码
            retry_count += 1
            self.processing_accounts[phone]["retry_count"] = retry_count
            
            self.update_status(phone, f"发送失败，30秒后重试 ({retry_count}/{max_retries})")
            
            # 30秒后重试
            retry_timer = QTimer(self)
            retry_timer.setSingleShot(True)
            retry_timer.timeout.connect(lambda: self.retry_send_code(phone))
            retry_timer.start(30000)  # 30秒
            
            # 保存计时器引用
            if not hasattr(self, 'retry_timers'):
                self.retry_timers = {}
            self.retry_timers[phone] = retry_timer
            
        else:
            # 超过重试次数，标记为失败
            self.update_status(phone, f"发送验证码失败: {error}")
            self.stop_account_login(phone)

    def retry_send_code(self, phone):
        """重试发送验证码"""
        if phone not in self.processing_accounts:
            return
        
        account_info = self.processing_accounts[phone]
        api_id = account_info["api_id"]
        api_hash = account_info["api_hash"]
        retry_count = account_info.get("retry_count", 0)
        
        self.update_status(phone, f"重试发送验证码... ({retry_count}/2)")
        self.parent.log(f"{phone} 开始第 {retry_count} 次重试发送验证码")
        
        # 在异步处理器中重试发送验证码
        async def retry_send():
            try:
                success = await self.parent.async_handler.send_verification_code(
                    phone, api_id, api_hash
                )
                
                if success:
                    QMetaObject.invokeMethod(
                        self, "on_code_sent",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone)
                    )
                else:
                    QMetaObject.invokeMethod(
                        self, "on_code_send_failed",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone),
                        Q_ARG(str, "重试发送验证码失败")
                    )
            except Exception as e:
                QMetaObject.invokeMethod(
                    self, "on_code_send_failed",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, phone),
                    Q_ARG(str, str(e))
                )
        
        # 创建重试任务
        task = asyncio.run_coroutine_threadsafe(retry_send(), self.parent.event_loop_thread.loop)
        if not hasattr(self, 'running_tasks'):
            self.running_tasks = {}
        self.running_tasks[f"{phone}_retry"] = task
    
    @pyqtSlot(str, str)
    def parse_api_response(self, phone, response_text):
        """解析API响应 - 支持纯数字密码"""
        try:
            self.parent.log(f"{phone} 解析API响应，长度: {len(response_text)}")
            
            verification_code = None
            password = None
            
            import re
            
            # 提取所有input元素的value值
            input_values = []
            input_pattern = r'<input[^>]*value="([^"]*)"[^>]*>'
            matches = re.findall(input_pattern, response_text, re.IGNORECASE)
            
            for match in matches:
                value = match.strip()
                if value:  # 只保留非空值
                    input_values.append(value)
            
            self.parent.log(f"{phone} 提取到的所有input value值: {input_values}")
            
            # 分类处理input值
            potential_codes = []
            potential_passwords = []
            
            for value in input_values:
                # 排除明显不相关的值
                if value.lower() in ['viewport', 'charset', 'content', 'device', 'width', 'scale', 
                                'maximum', 'minimum', 'user', 'webkit', 'initial', '1.0']:
                    continue
                
                # 判断是否可能是验证码（4-6位数字）
                if (value.isdigit() and 
                    4 <= len(value) <= 6 and
                    value not in ['0000', '1111', '9999', '2024', '2025']):
                    potential_codes.append(value)
                
                # 判断是否可能是密码（6位以上，可以是纯数字或字母数字混合）
                elif len(value) >= 6:
                    # 密码可能的格式：
                    # 1. 字母数字混合（如ch789789）
                    # 2. 纯数字（如123456789）
                    # 3. 纯字母（如abcdefgh）
                    if (re.match(r'^[a-zA-Z0-9]+$', value) and  # 只包含字母和数字
                        value not in ['000000', '111111', '123456', '654321', '999999']):  # 排除简单密码
                        potential_passwords.append(value)
            
            self.parent.log(f"{phone} 潜在验证码: {potential_codes}")
            self.parent.log(f"{phone} 潜在密码: {potential_passwords}")
            
            # 选择验证码（优先选择5-6位的）
            if potential_codes:
                # 按长度排序，优先选择5-6位的
                potential_codes.sort(key=lambda x: (len(x) in [5, 6], len(x)), reverse=True)
                verification_code = potential_codes[0]
                self.parent.log(f"{phone} 确定验证码: {verification_code}")
            
            # 选择密码（排除已选择的验证码）
            if potential_passwords:
                for pwd in potential_passwords:
                    if pwd != verification_code:  # 确保密码不等于验证码
                        # 额外验证：如果是纯数字密码，长度应该比验证码长
                        if pwd.isdigit() and verification_code:
                            if len(pwd) > len(verification_code):
                                password = pwd
                                self.parent.log(f"{phone} 确定密码（纯数字）: {password}")
                                break
                        else:
                            # 非纯数字密码直接使用
                            password = pwd
                            self.parent.log(f"{phone} 确定密码（混合）: {password}")
                            break
            
            # 如果input解析失败，尝试文本模式解析
            if not verification_code or not password:
                self.parent.log(f"{phone} input解析不完整，尝试文本模式...")
                
                # 备用方案：从整个页面文本中提取
                if not verification_code:
                    # 查找验证码
                    all_numbers = re.findall(r'\b(\d{4,6})\b', response_text)
                    for num in all_numbers:
                        if num not in ['2024', '2025', '0000', '1111', '9999']:
                            verification_code = num
                            self.parent.log(f"{phone} 文本模式找到验证码: {verification_code}")
                            break
                
                if not password:
                    # 查找密码 - 更宽泛的搜索
                    password_patterns = [
                        r'\b(ch\d{6,8})\b',  # ch+数字格式
                        r'\b([a-zA-Z]{2,}[0-9]{3,})\b',  # 字母+数字
                        r'\b([0-9]{6,12})\b',  # 6-12位纯数字（排除验证码）
                        r'\b([a-zA-Z0-9]{8,20})\b'  # 8-20位字母数字混合
                    ]
                    
                    for pattern in password_patterns:
                        matches = re.findall(pattern, response_text, re.IGNORECASE)
                        for match in matches:
                            if (match != verification_code and 
                                match.lower() not in ['viewport', 'charset', 'content'] and
                                len(match) >= 6):
                                password = match
                                self.parent.log(f"{phone} 文本模式找到密码: {password}")
                                break
                        if password:
                            break
            
            # 最终验证和处理
            if verification_code:
                self.update_status(phone, f"获取到验证码: {verification_code}")
                
                if password:
                    # 最后检查：确保密码和验证码不相同
                    if password != verification_code:
                        self.processing_accounts[phone]["password"] = password
                        self.parent.log(f"{phone} 同时获取到密码: {password}")
                    else:
                        self.parent.log(f"{phone} 密码与验证码相同，忽略密码")
                        password = None
                else:
                    self.parent.log(f"{phone} 未找到密码，仅使用验证码登录")
                
                # 停止轮询
                if hasattr(self, 'timers') and phone in self.timers:
                    self.timers[phone].stop()
                    del self.timers[phone]
                
                # 使用验证码和密码登录
                self.complete_login(phone, verification_code, password)
            else:
                self.parent.log(f"{phone} 仍未找到验证码，继续轮询...")
                # 更详细的调试信息
                self.parent.log(f"{phone} 页面预览: {response_text[:200]}...")
                
        except Exception as e:
            self.parent.log(f"{phone} 解析API响应时出错: {str(e)}")
            import traceback
            self.parent.log(f"详细错误: {traceback.format_exc()}")
            self.update_status(phone, f"解析响应错误: {str(e)}")

    def complete_login(self, phone, code, password=None):
        """完成登录"""
        if phone not in self.processing_accounts:
            return
        
        account_info = self.processing_accounts[phone]
        api_id = account_info["api_id"]
        api_hash = account_info["api_hash"]
        
        self.update_status(phone, "正在登录...")
        self.parent.log(f"{phone} 开始登录，API ID: {api_id}")
        
        # 执行登录
        async def do_login():
            try:
                success = await self.parent.async_handler.complete_login(
                    phone, api_id, api_hash, code, password
                )
                
                self.parent.log(f"{phone} 登录结果: {success}")
                
                QMetaObject.invokeMethod(
                    self, "on_login_complete",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, phone),
                    Q_ARG(bool, success)
                )
            except Exception as e:
                error_msg = str(e)
                self.parent.log(f"{phone} 登录异常: {error_msg}")
                
                # 检查是否需要二次验证密码
                if "SessionPasswordNeededError" in error_msg or "需要两步验证密码" in error_msg:
                    QMetaObject.invokeMethod(
                        self, "handle_password_needed",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone)
                    )
                else:
                    import traceback
                    full_error = f"登录异常: {error_msg}\n详细错误: {traceback.format_exc()}"
                    print(full_error)
                    QMetaObject.invokeMethod(
                        self, "on_login_error", 
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone),
                        Q_ARG(str, full_error)
                    )
        
        asyncio.run_coroutine_threadsafe(do_login(), self.parent.event_loop_thread.loop)

    @pyqtSlot(str)
    def handle_password_needed(self, phone):
        """处理需要二次验证密码的情况"""
        self.parent.log(f"{phone} 需要二次验证密码")
        
        # 检查是否有保存的密码
        saved_password = self.parent.config_manager.get_saved_password(phone)
        if saved_password:
            self.parent.log(f"{phone} 使用已保存的二次验证密码")
            # 使用保存的密码重新登录
            if phone in self.processing_accounts:
                code = self.processing_accounts[phone].get("last_code", "")
                if code:
                    self.complete_login(phone, code, saved_password)
                    return
        
        # 如果有API链接，尝试自动获取密码
        if phone in self.processing_accounts:
            api_url = self.processing_accounts[phone].get("api_url", "")
            if api_url:
                self.parent.log(f"{phone} 尝试从API获取二次验证密码")
                # 这里可以添加自动获取密码的逻辑
                # 暂时先标记需要手动处理
                self.update_status(phone, "需要二次验证密码")
            else:
                self.update_status(phone, "需要二次验证密码")
        else:
            self.update_status(phone, "需要二次验证密码")
    
    @pyqtSlot(str, bool)
    def on_login_complete(self, phone, success):
        """登录完成"""
        if phone not in self.processing_accounts:
            return
        
        account_info = self.processing_accounts[phone]
        
        if success:
            self.update_status(phone, "登录成功！")
            self.parent.log(f"{phone} 登录成功，开始添加账号信息")
            
            # 重要：确保账号信息正确添加
            # 这里不需要手动调用add_account_success，因为complete_login中的信号会处理
            
            # 如果有密码，保存密码
            if "password" in account_info and account_info["password"]:
                self.parent.config_manager.save_password(phone, account_info["password"])
                self.parent.config_manager.save_config()
                self.parent.log(f"{phone} 已保存二次验证密码")
            
        else:
            self.update_status(phone, "登录失败")
            self.parent.log(f"{phone} 登录失败")
            
            # 移除可能已添加的账号记录
            if phone in self.parent.accounts:
                self.parent.remove_failed_account(phone, "登录失败")
        
        # 清理资源
        self.stop_account_login(phone, update_ui=False)
        
        # 检查是否所有账号都处理完毕
        self.check_all_completed()
    
    @pyqtSlot(str, str)
    def on_login_error(self, phone, error):
        """登录错误"""
        self.update_status(phone, f"登录错误: {error}")
        
        # 清理资源
        self.stop_account_login(phone, update_ui=False)
        
        # 检查是否所有账号都处理完毕
        self.check_all_completed()
    
    def stop_account_login(self, phone, update_ui=True):
        """停止单个账号的登录 - 增强版本，释放API分配"""
        self.parent.log(f"{phone} 开始停止登录流程...")
        
        # ✅ 释放分配的API ID
        if phone in self.processing_accounts:
            api_id = str(self.processing_accounts[phone].get('api_id', ''))
            if api_id:
                with self.api_allocation_lock:
                    self.allocated_api_ids.discard(api_id)
                    self.parent.log(f"{phone} 释放API ID: {api_id}")
        
        # 1. 停止轮询计时器
        if hasattr(self, 'timers') and phone in self.timers:
            self.timers[phone].stop()
            del self.timers[phone]
            self.parent.log(f"{phone} 停止轮询计时器")
        
        # 2. 停止重试计时器
        if hasattr(self, 'retry_timers') and phone in self.retry_timers:
            self.retry_timers[phone].stop()
            del self.retry_timers[phone]
            self.parent.log(f"{phone} 停止重试计时器")
        
        # 3. 取消运行中的任务
        if hasattr(self, 'running_tasks'):
            for task_key in list(self.running_tasks.keys()):
                if phone in task_key:
                    task = self.running_tasks[task_key]
                    if not task.done():
                        task.cancel()
                    del self.running_tasks[task_key]
                    self.parent.log(f"{phone} 取消任务: {task_key}")
        
        # 4. 正确断开Telethon客户端连接
        if self.async_handler and phone in self.async_handler.temp_clients:
            self.parent.log(f"{phone} 开始断开临时客户端连接...")
            
            # 在异步环境中正确断开连接
            async def disconnect_client():
                try:
                    client = self.async_handler.temp_clients[phone]
                    if client.is_connected():
                        await client.disconnect()
                        self.parent.log(f"{phone} 临时客户端连接已断开")
                    del self.async_handler.temp_clients[phone]
                except Exception as e:
                    self.parent.log(f"{phone} 断开临时客户端时出错: {str(e)}")
            
            # 提交断开任务到事件循环
            try:
                asyncio.run_coroutine_threadsafe(
                    disconnect_client(), 
                    self.event_loop_thread.loop
                )
            except Exception as e:
                self.parent.log(f"{phone} 提交断开任务失败: {str(e)}")
        
        # 5. 移除处理中的账号
        if phone in self.processing_accounts:
            if update_ui:
                self.update_status(phone, "已停止")
            del self.processing_accounts[phone]
            self.parent.log(f"{phone} 移除处理记录")
        
        self.parent.log(f"{phone} 登录流程已完全停止")
    
    def stop_all_logins(self):
        """停止所有登录 - 增强版本"""
        self.parent.log("开始停止所有登录流程...")
        
        # 复制列表避免在迭代时修改
        phones = list(self.processing_accounts.keys())
        
        # 停止所有账号的登录
        for phone in phones:
            self.stop_account_login(phone)
        
        # ✅ 清空所有分配记录
        with self.api_allocation_lock:
            self.allocated_api_ids.clear()
            self.parent.log("已清空所有API分配记录")
        
        # 额外的全局清理
        async def cleanup_all_clients():
            """清理所有临时客户端"""
            try:
                if self.async_handler and self.async_handler.temp_clients:
                    clients_to_disconnect = list(self.async_handler.temp_clients.items())
                    
                    for phone, client in clients_to_disconnect:
                        try:
                            if client.is_connected():
                                await client.disconnect()
                                self.parent.log(f"{phone} 全局清理：客户端已断开")
                        except Exception as e:
                            self.parent.log(f"{phone} 全局清理断开失败: {str(e)}")
                    
                    # 清空临时客户端字典
                    self.async_handler.temp_clients.clear()
                    self.parent.log("所有临时客户端已清理")
                    
            except Exception as e:
                self.parent.log(f"全局清理时出错: {str(e)}")
        
        # 提交全局清理任务
        try:
            asyncio.run_coroutine_threadsafe(
                cleanup_all_clients(), 
                self.event_loop_thread.loop
            )
        except Exception as e:
            self.parent.log(f"提交全局清理任务失败: {str(e)}")
        
        # 更新按钮状态
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        self.parent.log("所有登录流程已停止")

    def closeEvent(self, event):
        """对话框关闭事件 - 确保资源清理"""
        self.parent.log("API登录对话框正在关闭，清理资源...")
        
        # 停止所有登录流程
        self.stop_all_logins()
        
        # 等待一下让清理任务完成
        QTimer.singleShot(500, lambda: super(APILoginDialog, self).closeEvent(event))
    
    def check_all_completed(self):
        """检查是否所有账号都处理完毕"""
        if not self.processing_accounts:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

class AccountManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram 自动化管理器")
        self.setGeometry(100, 100, 1600, 1000)
        
        # 设置图标
        if os.path.exists('logo.ico'):
            self.setWindowIcon(QIcon('logo.ico'))
        
        # 定义按钮样式
        self.setup_styles()
        
        # 初始化属性
        self.accounts = {}
        self.selected_accounts = []
        self.async_handler = None
        self.config_manager = ConfigManager()
        self.event_loop_thread = AsyncEventLoopThread()
        self.running_tasks = {}  # 正在运行的任务 {phone_tasktype: task_info}
        self.program_remark = ""  # 存储程序备注
        # 创建必要的文件夹
        self.create_directories()
        
        # 启动事件循环线程
        self.event_loop_thread.start()
        
        # 初始化UI
        self.init_ui()
        
        # 加载配置
        self.load_config()
        
        # 初始化异步处理器
        QTimer.singleShot(500, self.init_async_handler)
        
        # 加载sessions
       # QTimer.singleShot(1000, self.load_sessions)

        self.stranger_messages_history = []  # 记录陌生人消息历史
    def setup_styles(self):
        """设置UI样式"""
        self.button_styles = {
            'primary': """
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                }
                QPushButton:pressed {
                    background-color: #0D47A1;
                }
                QPushButton:disabled {
                    background-color: #BDBDBD;
                    color: #757575;
                }
            """,
            'success': """
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #388E3C;
                }
                QPushButton:pressed {
                    background-color: #2E7D32;
                }
            """,
            'warning': """
                QPushButton {
                    background-color: #FF9800;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #F57C00;
                }
                QPushButton:pressed {
                    background-color: #E65100;
                }
            """,
            'danger': """
                QPushButton {
                    background-color: #F44336;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #D32F2F;
                }
                QPushButton:pressed {
                    background-color: #C62828;
                }
            """,
            'info': """
                QPushButton {
                    background-color: #00BCD4;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #0097A7;
                }
                QPushButton:pressed {
                    background-color: #00695C;
                }
            """,
            'secondary': """
                QPushButton {
                    background-color: #607D8B;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #455A64;
                }
                QPushButton:pressed {
                    background-color: #37474F;
                }
            """,
            'purple': """
                QPushButton {
                    background-color: #9C27B0;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #7B1FA2;
                }
                QPushButton:pressed {
                    background-color: #6A1B9A;
                }
            """,
            'task': """
                QPushButton {
                    background-color: #E91E63;
                    color: white;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #C2185B;
                }
            """
        }
    
    def create_directories(self):
        """创建必要的文件夹"""
        dirs = [
            'sessions', 'sessions/ok', 'sessions/error', 'backup', 'logs', 
            'resources', 'resources/头像', 'resources/频道头像'
        ]
        for dir_path in dirs:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
        
        # 创建资源文件
        resource_files = {
            'resources/频道名称.txt': '# 每行一个频道名称\n测试频道\n',
            'resources/频道简介.txt': '# 每行一个频道简介\n这是一个测试频道\n',
            'resources/频道公开链接.txt': '# 每行一个频道公开链接（不含@）\ntestchannel\n',
            'resources/自动回复.txt': '# 每行一条自动回复话术\n您好！我现在不在线，稍后回复您。\n感谢您的消息，我会尽快回复。\n',  # 新增
            'resources/通知机器人.txt': '# 每行一个机器人配置，格式: BOT_TOKEN:CHAT_ID\n# 例如: 123456789:ABCDEF:@channel_username\n',  # 新增
        }
        
        for file_path, default_content in resource_files.items():
            if not Path(file_path).exists():
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(default_content)
    
    def init_ui(self):
        """重构后的初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 设置窗口和控件的大小策略
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        central_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 设置主窗口样式 - 保持原有样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f4f8;
            }
            QWidget {
                font-family: 'Microsoft YaHei', Arial, sans-serif;
            }
            QTabWidget::pane {
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                background-color: white;
            }
            QTabWidget::tab-bar {
                alignment: center;
            }
            QTabBar::tab {
                background-color: #F5F5F5;
                border: 1px solid #BDBDBD;
                padding: 8px 16px;
                margin-right: 2px;
                font-weight: bold;
                color: #424242;
            }
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
                border-bottom-color: #2196F3;
            }
            QTabBar::tab:hover {
                background-color: #E3F2FD;
            }
            QGroupBox {
                background-color: rgba(255, 255, 255, 0.7);
                border-radius: 8px;
            }
            QSplitter::handle {
                background-color: #BDBDBD;
                height: 3px;
                border-radius: 1px;
            }
            QSplitter::handle:hover {
                background-color: #2196F3;
            }
            QSplitter::handle:pressed {
                background-color: #1976D2;
            }
        """)
        
        # 主布局 - 垂直布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 工具栏
        toolbar = self.create_toolbar()
        main_layout.addWidget(toolbar)
        
        # 创建主要内容区域的水平分割器
        self.main_horizontal_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_horizontal_splitter.setChildrenCollapsible(False)
        
        # 左侧：任务控制面板
        task_panel = self.create_task_panel()
        task_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_horizontal_splitter.addWidget(task_panel)
        
        # 右侧：账号列表面板
        account_panel = self.create_global_account_panel()
        account_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.main_horizontal_splitter.addWidget(account_panel)
        
        # 设置水平分割器的初始比例 - 左边占2/3，右边占1/3
        self.main_horizontal_splitter.setSizes([800, 400])
        self.main_horizontal_splitter.setStretchFactor(0, 2)  # 任务面板可拉伸优先级高
        self.main_horizontal_splitter.setStretchFactor(1, 1)  # 账号面板拉伸优先级低
        
        # 创建垂直分割器，包含主要内容和日志
        self.main_vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_vertical_splitter.setChildrenCollapsible(False)
        
        # 添加水平分割器到垂直分割器
        self.main_vertical_splitter.addWidget(self.main_horizontal_splitter)
        
        # 日志面板
        log_panel = self.create_log_panel()
        log_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_vertical_splitter.addWidget(log_panel)
        
        # 设置垂直分割器的初始大小比例 - 主要内容900，日志100
        self.main_vertical_splitter.setSizes([900, 100])
        self.main_vertical_splitter.setStretchFactor(0, 1)  # 主要内容可拉伸
        self.main_vertical_splitter.setStretchFactor(1, 0)  # 日志面板固定优先级
        
        main_layout.addWidget(self.main_vertical_splitter)
        
        # 状态栏
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("就绪")
        
        # 设置窗口的最小尺寸
        self.setMinimumSize(1200, 700)  # 增加最小宽度以适应新布局

    def create_global_account_panel(self):
        """创建全局账号面板"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 实际内容面板
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # 标题
        title = QLabel("📱 账号管理")
        title.setStyleSheet("""
            font-size: 16px; 
            font-weight: bold; 
            padding: 8px;
            color: #2196F3;
            background-color: #E3F2FD;
            border-radius: 8px;
            margin-bottom: 5px;
        """)
        layout.addWidget(title)
        
        # 账号表格
        self.account_table = QTableWidget()
        self.account_table.setColumnCount(7)
        self.account_table.setHorizontalHeaderLabels(["选择", "📱 手机号", "👤 名字", "👤 姓氏", "🏷️ 用户名", "🔑 API ID", "📊 状态"])
        self.account_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.account_table.horizontalHeader().setStretchLastSection(True)
        
        # 美化表格
        self.account_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #E0E0E0;
                background-color: white;
                alternate-background-color: #F8F9FA;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                selection-background-color: #E3F2FD;
            }
            QTableWidget::item {
                padding: 6px;
                border-bottom: 1px solid #F0F0F0;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QHeaderView::section {
                background-color: #F5F5F5;
                padding: 6px;
                border: none;
                border-right: 1px solid #D0D0D0;
                font-weight: bold;
                color: #424242;
                font-size: 11px;
            }
        """)
        
        # 设置列宽 - 针对右侧面板优化
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.account_table.setColumnWidth(0, 35)  # 选择列宽度
        
        # 设置表格高度策略
        self.account_table.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.account_table)
        
        # 操作按钮区域
        button_group = QGroupBox("操作")
        button_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                color: #424242;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                margin-top: 5px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px 0 4px;
            }
        """)
        
        button_layout = QVBoxLayout(button_group)
        button_layout.setSpacing(6)
        
        # 选择操作按钮
        select_layout = QHBoxLayout()
        
        self.select_all_btn = QPushButton("✅ 全选")
        self.select_all_btn.setStyleSheet(self.button_styles['success'])
        self.select_all_btn.clicked.connect(self.select_all_accounts)
        select_layout.addWidget(self.select_all_btn)
        
        self.deselect_all_btn = QPushButton("❌ 取消")
        self.deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        self.deselect_all_btn.clicked.connect(self.deselect_all_accounts)
        select_layout.addWidget(self.deselect_all_btn)
        
        button_layout.addLayout(select_layout)
        
        # 账号操作按钮
        self.refresh_profile_btn = QPushButton("🔄 获取资料")
        self.refresh_profile_btn.setStyleSheet(self.button_styles['info'])
        self.refresh_profile_btn.clicked.connect(self.refresh_selected_profiles)
        button_layout.addWidget(self.refresh_profile_btn)
        
        self.delete_account_btn = QPushButton("🗑️ 删除选中")
        self.delete_account_btn.setStyleSheet(self.button_styles['danger'])
        self.delete_account_btn.clicked.connect(self.delete_selected_accounts)
        button_layout.addWidget(self.delete_account_btn)
        
        layout.addWidget(button_group)
        
        # 设置面板的尺寸策略
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        
        # 将面板设置为滚动区域的内容
        scroll_area.setWidget(panel)
        
        return scroll_area
    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #667eea;
                border: none;
                spacing: 8px;
                padding: 8px;
            }
            QToolBar QToolButton {
                background-color: rgba(255, 255, 255, 0.1);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
                margin: 2px;
            }
            QToolBar QToolButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.4);
            }
            QToolBar QToolButton:pressed {
                background-color: rgba(255, 255, 255, 0.3);
            }
        """)
        
        # 添加账号按钮
        add_account_action = QAction("📱 添加账号", self)
        add_account_action.triggered.connect(self.add_account_dialog)
        toolbar.addAction(add_account_action)

        # API接码登录
        api_login_action = QAction("🤖 API接码登录", self)
        api_login_action.triggered.connect(self.show_api_login_dialog)
        toolbar.addAction(api_login_action)
        
        # 检测账号状态
        check_accounts_action = QAction("🔍 检测账号", self)
        check_accounts_action.triggered.connect(self.check_accounts_status)
        toolbar.addAction(check_accounts_action)
        
        # 设备管理按钮
        device_manager_action = QAction("💻 设备管理", self)
        device_manager_action.triggered.connect(self.show_device_manager)
        toolbar.addAction(device_manager_action)
        
        # 任务列表
        task_list_action = QAction("📋 任务列表", self)
        task_list_action.triggered.connect(self.show_task_list)
        toolbar.addAction(task_list_action)
        # 清理异常账号
        clean_accounts_action = QAction("🧹 清理异常", self)
        clean_accounts_action.triggered.connect(self.clean_error_accounts)
        toolbar.addAction(clean_accounts_action)

        toolbar.addSeparator()
        
        # 加载sessions
        load_sessions_action = QAction("💿 加载Sessions", self)
        load_sessions_action.triggered.connect(self.load_sessions)
        toolbar.addAction(load_sessions_action)
        
        # 保存配置
        save_config_action = QAction("💾 保存配置", self)
        save_config_action.triggered.connect(self.save_config)
        toolbar.addAction(save_config_action)
        
        toolbar.addSeparator()
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid rgba(255, 255, 255, 0.3);
                border-radius: 8px;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 6px;
            }
        """)
        toolbar.addWidget(self.progress_bar)
        
        # 任务状态标签
        self.task_status_label = QLabel("🎯 当前无任务运行")
        self.task_status_label.setStyleSheet("color: white; font-weight: bold; padding: 0 10px;")
        toolbar.addWidget(self.task_status_label)
        
        # 👇 添加程序备注标签
        self.program_remark_label = QLabel("📝 未命名设备")
        self.program_remark_label.setStyleSheet("""
            color: #FFE082; 
            font-weight: bold; 
            padding: 0 10px;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 4px;
            background-color: rgba(255, 255, 255, 0.1);
        """)
        self.program_remark_label.setToolTip("双击编辑程序备注")
        self.program_remark_label.mouseDoubleClickEvent = self.edit_program_remark
        toolbar.addWidget(self.program_remark_label)

        return toolbar
    
    def create_task_panel(self):
        """修改后的任务控制面板 - 移除账号列表标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 实际内容面板
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 标题
        title = QLabel("任务控制")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 5px;")
        layout.addWidget(title)
        
        # 标签页 - 移除"账号列表"标签页
        self.task_tabs = QTabWidget()
        
        # 资料修改标签页
        profile_tab = self.create_profile_tab()
        self.task_tabs.addTab(profile_tab, "资料修改")
        
        # 加群任务标签页
        join_group_tab = self.create_join_group_tab()
        self.task_tabs.addTab(join_group_tab, "加群任务")
        
        # 陌生人消息标签页
        stranger_message_tab = self.create_stranger_message_tab()
        self.task_tabs.addTab(stranger_message_tab, "陌生人消息")

        # 联系人消息标签页
        contact_message_tab = self.create_contact_message_tab()
        self.task_tabs.addTab(contact_message_tab, "联系人消息")

        # 群发消息标签页
        broadcast_message_tab = self.create_broadcast_message_tab()
        self.task_tabs.addTab(broadcast_message_tab, "群发消息")
        
        # 群管理标签页
        group_manage_tab = self.create_group_manage_tab()
        self.task_tabs.addTab(group_manage_tab, "群管理")
        
        # 创建频道标签页
        channel_tab = self.create_channel_tab()
        self.task_tabs.addTab(channel_tab, "创建频道")
        
        # 账号安全标签页
        security_tab = self.create_security_tab()
        self.task_tabs.addTab(security_tab, "账号安全")
        
        # 隐私设置标签页
        privacy_tab = self.create_privacy_tab()
        self.task_tabs.addTab(privacy_tab, "隐私设置")

        layout.addWidget(self.task_tabs)

        # 设置面板的尺寸策略
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 将面板设置为滚动区域的内容
        scroll_area.setWidget(panel)
        
        return scroll_area

    def create_account_list_tab(self):
        """创建账号列表标签页"""
        tab = QWidget()
        main_layout = QHBoxLayout(tab)  # 改为水平布局
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(10)
        
        # 左侧：账号表格
        table_layout = QVBoxLayout()
        
        self.account_table = QTableWidget()
        self.account_table.setColumnCount(7)
        self.account_table.setHorizontalHeaderLabels(["选择", "📱 手机号", "👤 名字", "👤 姓氏", "🏷️ 用户名", "🔑 API ID", "📊 状态"])
        self.account_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.account_table.horizontalHeader().setStretchLastSection(True)
        
        # 美化表格
        self.account_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #E0E0E0;
                background-color: white;
                alternate-background-color: #F8F9FA;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                selection-background-color: #E3F2FD;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #F0F0F0;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QHeaderView::section {
                background-color: #F5F5F5;
                padding: 8px;
                border: none;
                border-right: 1px solid #D0D0D0;
                font-weight: bold;
                color: #424242;
            }
        """)
        
        # 设置列宽
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.account_table.setColumnWidth(0, 45)
        
        table_layout.addWidget(self.account_table)
        main_layout.addLayout(table_layout, 1)  # 表格占主要空间
        
        # 右侧：操作按钮 - 竖着排列
        button_group = QGroupBox("操作")
        button_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                color: #424242;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                margin-top: 5px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        button_group.setFixedWidth(160)  # 固定按钮区域宽度
        
        button_layout = QVBoxLayout(button_group)
        button_layout.setSpacing(8)  # 按钮间距
        
        self.select_all_btn = QPushButton("✅ 全选")
        self.select_all_btn.setStyleSheet(self.button_styles['success'])
        self.select_all_btn.clicked.connect(self.select_all_accounts)
        button_layout.addWidget(self.select_all_btn)
        
        self.deselect_all_btn = QPushButton("❌ 取消全选")
        self.deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        self.deselect_all_btn.clicked.connect(self.deselect_all_accounts)
        button_layout.addWidget(self.deselect_all_btn)
        
        self.refresh_profile_btn = QPushButton("🔄 获取账号资料")
        self.refresh_profile_btn.setStyleSheet(self.button_styles['info'])
        self.refresh_profile_btn.clicked.connect(self.refresh_selected_profiles)
        button_layout.addWidget(self.refresh_profile_btn)
        
        self.delete_account_btn = QPushButton("🗑️ 删除选中")
        self.delete_account_btn.setStyleSheet(self.button_styles['danger'])
        self.delete_account_btn.clicked.connect(self.delete_selected_accounts)
        button_layout.addWidget(self.delete_account_btn)
        
        # 添加弹性空间，让按钮靠上排列
        button_layout.addStretch()
        
        main_layout.addWidget(button_group, 0)  # 按钮区域不拉伸
        
        return tab

    def create_profile_tab(self):
        """创建资料修改标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #2196F3;
                border: 2px solid #E3F2FD;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.profile_account_list = QListWidget()
        self.profile_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.profile_account_list.setMaximumHeight(100)
        self.profile_account_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
                selection-background-color: #E3F2FD;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #F0F0F0;
            }
            QListWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
        """)
        account_layout.addWidget(self.profile_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.profile_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.profile_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 资料选项
        profile_group = QGroupBox("⚙️ 选择要修改的资料")
        profile_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #FF9800;
                border: 2px solid #FFF3E0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        profile_layout = QVBoxLayout(profile_group)
        
        self.profile_checkboxes = {
            'first_name': QCheckBox("📝 名字"),
            'last_name': QCheckBox("📝 姓氏"),
            'bio': QCheckBox("💭 简介"),
            'username': QCheckBox("🏷️ 用户名"),
            'avatar': QCheckBox("🖼️ 头像")
        }
        
        checkbox_style = """
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #424242;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 2px solid #BDBDBD;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border: 2px solid #4CAF50;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #2196F3;
            }
        """
        
        for checkbox in self.profile_checkboxes.values():
            checkbox.setStyleSheet(checkbox_style)
            profile_layout.addWidget(checkbox)
        
        layout.addWidget(profile_group)
        
        # 执行按钮
        self.update_profile_btn = QPushButton("🚀 更新选中账号资料")
        self.update_profile_btn.setStyleSheet(self.button_styles['task'])
        self.update_profile_btn.clicked.connect(self.update_profiles)
        layout.addWidget(self.update_profile_btn)
        
        layout.addStretch()
        
        return tab
    def refresh_selected_profiles(self):
        """获取选中账号的资料"""
        selected_accounts = []
        for row in range(self.account_table.rowCount()):
            checkbox = self.account_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                phone = self.account_table.item(row, 1).text()
                selected_accounts.append(phone)
        
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择要获取资料的账号")
            return
        
        self.log(f"开始获取 {len(selected_accounts)} 个账号的资料")
        
        # 在事件循环中执行任务
        async def do_refresh_profiles():
            success_count = 0
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'refresh_profile', '获取资料')
                    
                    success = await self.async_handler.refresh_account_profile(phone)
                    if success:
                        success_count += 1
                        self.log(f"{phone} 资料获取成功")
                        
                        # 立即更新这个账号的表格行
                        QMetaObject.invokeMethod(
                            self, "update_single_account_row",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, phone)
                        )
                    else:
                        self.log(f"{phone} 资料获取失败")
                    
                    self.remove_running_task(phone, 'refresh_profile')
                    
                except Exception as e:
                    self.log(f"{phone} 获取资料时发生错误: {str(e)}")
                    self.remove_running_task(phone, 'refresh_profile')
            
            self.log(f"资料获取完成，成功: {success_count}/{len(selected_accounts)}")
        
        asyncio.run_coroutine_threadsafe(do_refresh_profiles(), self.event_loop_thread.loop)

    @pyqtSlot(int, int)
    def on_refresh_profiles_finished(self, success_count, total_count):
        """获取资料完成"""
        self.log(f"资料获取完成，成功: {success_count}/{total_count}")
        QMessageBox.information(
            self, "完成", 
            f"账号资料获取完成\n\n"
            f"成功：{success_count} 个账号\n"
            f"失败：{total_count - success_count} 个账号\n"
            f"总计：{total_count} 个账号"
        )
    def create_join_group_tab(self):
        """创建加群任务标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #9C27B0;
                border: 2px solid #F3E5F5;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.join_account_list = QListWidget()
        self.join_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.join_account_list.setMaximumHeight(100)
        self.join_account_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
            }
            QListWidget::item:selected {
                background-color: #9C27B0;
                color: white;
            }
        """)
        account_layout.addWidget(self.join_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.join_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.join_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 加群设置
        settings_group = QGroupBox("⚙️ 加群设置")
        settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #4CAF50;
                border: 2px solid #E8F5E8;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        settings_layout = QFormLayout(settings_group)
        
        self.join_interval_spin = QSpinBox()
        self.join_interval_spin.setRange(1, 3600)
        self.join_interval_spin.setValue(60)
        self.join_interval_spin.setSuffix(" 秒")
        self.join_interval_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #2196F3;
            }
        """)
        settings_layout.addRow("⏰ 加群间隔:", self.join_interval_spin)
        
        self.auto_join_checkbox = QCheckBox("🔄 自动定时加群")
        self.auto_join_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #4CAF50;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
            }
        """)
        settings_layout.addRow("", self.auto_join_checkbox)
        
        layout.addWidget(settings_group)
        
        # 进度显示
        progress_group = QGroupBox("📊 加群进度")
        progress_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #FF9800;
                border: 2px solid #FFF3E0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        progress_layout = QVBoxLayout(progress_group)
        
        self.join_progress_label = QLabel("⏳ 等待开始...")
        self.join_progress_label.setStyleSheet("font-size: 13px; color: #666; padding: 5px;")
        progress_layout.addWidget(self.join_progress_label)
        
        self.join_progress_bar = QProgressBar()
        self.join_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                text-align: center;
                font-weight: bold;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 6px;
            }
        """)
        progress_layout.addWidget(self.join_progress_bar)
        
        layout.addWidget(progress_group)
        
        # 执行按钮
        self.join_group_btn = QPushButton("🚀 立即加群")
        self.join_group_btn.setStyleSheet(self.button_styles['task'])
        self.join_group_btn.clicked.connect(self.join_groups)
        layout.addWidget(self.join_group_btn)
        
        layout.addStretch()
        
        return tab
    
    def create_stranger_message_tab(self):
        """创建陌生人消息标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #E91E63;
                border: 2px solid #FCE4EC;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.stranger_account_list = QListWidget()
        self.stranger_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.stranger_account_list.setMaximumHeight(100)
        account_layout.addWidget(self.stranger_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.stranger_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.stranger_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)

        # 控制按钮 - 合并监听设置和控制按钮
        control_group = QGroupBox("🎛️ 监听控制")
        control_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #673AB7;
                border: 2px solid #F3E5F5;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        control_layout = QVBoxLayout(control_group)
        
        # 功能选项 - 水平布局
        options_layout = QHBoxLayout()
        
        self.auto_reply_checkbox = QCheckBox("🤖 启用自动回复")
        self.auto_reply_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #4CAF50;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
            }
        """)
        options_layout.addWidget(self.auto_reply_checkbox)
        
        self.bot_notify_checkbox = QCheckBox("📢 启用机器人通知")
        self.bot_notify_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #2196F3;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
            }
        """)
        options_layout.addWidget(self.bot_notify_checkbox)
        
        control_layout.addLayout(options_layout)
        
        # 控制按钮 - 水平布局
        button_layout = QHBoxLayout()
        
        self.start_monitor_btn = QPushButton("🚀 开始监听陌生人消息")
        self.start_monitor_btn.setStyleSheet(self.button_styles['task'])
        self.start_monitor_btn.clicked.connect(self.start_stranger_monitoring)
        button_layout.addWidget(self.start_monitor_btn)
        
        self.stop_monitor_btn = QPushButton("⏹️ 停止监听")
        self.stop_monitor_btn.setStyleSheet(self.button_styles['danger'])
        self.stop_monitor_btn.clicked.connect(self.stop_stranger_monitoring)
        self.stop_monitor_btn.setEnabled(False)
        button_layout.addWidget(self.stop_monitor_btn)
        
        control_layout.addLayout(button_layout)
        layout.addWidget(control_group)
        
        # 陌生人消息显示区域
        message_group = QGroupBox("📨 收到的陌生人消息")
        message_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #795548;
                border: 2px solid #EFEBE9;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        message_layout = QVBoxLayout(message_group)
        
        self.stranger_message_display = QTextEdit()
        self.stranger_message_display.setMaximumHeight(450)
        self.stranger_message_display.setReadOnly(True)
        self.stranger_message_display.setPlaceholderText("📱 陌生人消息将在这里显示...")
        self.stranger_message_display.setStyleSheet("""
            QTextEdit {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
                font-family: Arial, sans-serif;
                font-size: 11px;
                padding: 8px;
            }
        """)
        # 设置为富文本模式以支持HTML
        self.stranger_message_display.setHtml("")
        message_layout.addWidget(self.stranger_message_display)
        
        # 清空消息按钮
        clear_stranger_btn = QPushButton("🗑️ 清空陌生人消息")
        clear_stranger_btn.setStyleSheet(self.button_styles['warning'])
        clear_stranger_btn.clicked.connect(self.clear_stranger_messages)
        message_layout.addWidget(clear_stranger_btn)
        
        layout.addWidget(message_group)
        
        # 手动回复区域
        reply_group = QGroupBox("💬 手动回复")
        reply_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #673AB7;
                border: 2px solid #F3E5F5;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        reply_layout = QVBoxLayout(reply_group)
        
        # 回复输入框 - 改为 QTextEdit 支持多行
        self.reply_input = QTextEdit()
        self.reply_input.setPlaceholderText("输入要回复的消息.....按 Ctrl+Enter 发送")
        self.reply_input.setMaximumHeight(41)  # 限制高度
        self.reply_input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
                background-color: white;
                font-family: Arial, sans-serif;
            }
            QTextEdit:focus {
                border: 2px solid #673AB7;
            }
        """)
        
        # 添加快捷键支持
        self.reply_input.installEventFilter(self)
        
        reply_layout.addWidget(self.reply_input)
        
        # 回复按钮布局
        reply_button_layout = QHBoxLayout()
        
        self.reply_to_last_btn = QPushButton("📤 回复最后一条消息")
        self.reply_to_last_btn.setStyleSheet(self.button_styles['primary'])
        self.reply_to_last_btn.clicked.connect(self.reply_to_last_message)
        reply_button_layout.addWidget(self.reply_to_last_btn)
        
        self.select_reply_btn = QPushButton("🎯 选择回复")
        self.select_reply_btn.setStyleSheet(self.button_styles['info'])
        self.select_reply_btn.clicked.connect(self.select_message_to_reply)
        reply_button_layout.addWidget(self.select_reply_btn)
        
        reply_layout.addLayout(reply_button_layout)
        layout.addWidget(reply_group)
        
        layout.addStretch()
        
        return tab
    def create_contact_message_tab(self):
        """创建联系人消息标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #1976D2;
                border: 2px solid #E3F2FD;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.contact_account_list = QListWidget()
        self.contact_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.contact_account_list.setMaximumHeight(100)
        self.contact_account_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.contact_account_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
                selection-background-color: #E3F2FD;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #F0F0F0;
            }
            QListWidget::item:selected {
                background-color: #1976D2;
                color: white;
            }
        """)
        account_layout.addWidget(self.contact_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.contact_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.contact_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 联系人管理
        contact_manage_group = QGroupBox("📱 联系人管理")
        contact_manage_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #009688;
                border: 2px solid #E0F2F1;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        contact_manage_layout = QVBoxLayout(contact_manage_group)
        
        # 添加联系人按钮
        self.add_contact_btn = QPushButton("👤 添加联系人")
        self.add_contact_btn.setStyleSheet(self.button_styles['primary'])
        self.add_contact_btn.clicked.connect(self.add_contacts)
        contact_manage_layout.addWidget(self.add_contact_btn)
        
        # 联系人文件说明
        contact_info = QLabel("📋 联系人列表文件: resources/联系人.txt\n🔹 每行一个联系人（手机号或@用户名）")
        contact_info.setStyleSheet("""
            color: #757575; 
            font-size: 12px; 
            padding: 8px;
            background-color: #F5F5F5;
            border-radius: 6px;
            border-left: 4px solid #009688;
        """)
        contact_manage_layout.addWidget(contact_info)
        
        layout.addWidget(contact_manage_group)
        
        # 消息设置
        message_settings_group = QGroupBox("⚙️ 消息发送设置")
        message_settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #FF5722;
                border: 2px solid #FBE9E7;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        message_settings_layout = QFormLayout(message_settings_group)
        
        self.contact_msg_interval_spin = QSpinBox()
        self.contact_msg_interval_spin.setRange(1, 3600)
        self.contact_msg_interval_spin.setValue(60)
        self.contact_msg_interval_spin.setSuffix(" 秒")
        self.contact_msg_interval_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #FF5722;
            }
        """)
        message_settings_layout.addRow("⏱️ 发送间隔:", self.contact_msg_interval_spin)
        
        self.contact_msg_round_spin = QSpinBox()
        self.contact_msg_round_spin.setRange(1, 86400)
        self.contact_msg_round_spin.setValue(3600)
        self.contact_msg_round_spin.setSuffix(" 秒")
        self.contact_msg_round_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #FF5722;
            }
        """)
        message_settings_layout.addRow("🔄 轮次间隔:", self.contact_msg_round_spin)
        
        self.auto_contact_msg_checkbox = QCheckBox("🤖 自动定时发送")
        self.auto_contact_msg_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #FF5722;
            }
            QCheckBox::indicator:checked {
                background-color: #FF5722;
            }
        """)
        message_settings_layout.addRow("", self.auto_contact_msg_checkbox)
        
        layout.addWidget(message_settings_group)
        
        # 执行按钮
        self.send_contact_msg_btn = QPushButton("🚀 开始发送联系人消息")
        self.send_contact_msg_btn.setStyleSheet(self.button_styles['task'])
        self.send_contact_msg_btn.clicked.connect(self.send_contact_messages)
        layout.addWidget(self.send_contact_msg_btn)
        
        layout.addStretch()
        
        return tab
    def create_broadcast_message_tab(self):
        """创建群发消息标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #009688;
                border: 2px solid #E0F2F1;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.broadcast_account_list = QListWidget()
        self.broadcast_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.broadcast_account_list.setMaximumHeight(100)
        account_layout.addWidget(self.broadcast_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.broadcast_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.broadcast_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 群发设置
        broadcast_settings_group = QGroupBox("⚙️ 群发设置")
        broadcast_settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #FF5722;
                border: 2px solid #FBE9E7;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        broadcast_settings_layout = QFormLayout(broadcast_settings_group)
        
        self.broadcast_interval_spin = QSpinBox()
        self.broadcast_interval_spin.setRange(1, 3600)
        self.broadcast_interval_spin.setValue(180)
        self.broadcast_interval_spin.setSuffix(" 秒")
        self.broadcast_interval_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #FF5722;
            }
        """)
        broadcast_settings_layout.addRow("⏰ 群发间隔:", self.broadcast_interval_spin)
        
        self.broadcast_round_spin = QSpinBox()
        self.broadcast_round_spin.setRange(1, 86400)
        self.broadcast_round_spin.setValue(3600)
        self.broadcast_round_spin.setSuffix(" 秒")
        self.broadcast_round_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #FF5722;
            }
        """)
        broadcast_settings_layout.addRow("🔄 轮次间隔:", self.broadcast_round_spin)
        
        self.auto_broadcast_checkbox = QCheckBox("🤖 自动定时群发")
        self.auto_broadcast_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #FF5722;
            }
            QCheckBox::indicator:checked {
                background-color: #FF5722;
            }
        """)
        broadcast_settings_layout.addRow("", self.auto_broadcast_checkbox)
        
        layout.addWidget(broadcast_settings_group)
        
        # 群组说明
        group_info_group = QGroupBox("📋 群发对象")
        group_info_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #3F51B5;
                border: 2px solid #E8EAF6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        group_info_layout = QVBoxLayout(group_info_group)
        
        group_info = QLabel("📢 群发将使用已加入的群组记录\n"
                        "🔍 如果没有群组记录，请先执行加群任务\n"
                        "⚙️ 或在群管理页面点击'检测已加入的群'")
        group_info.setStyleSheet("""
            color: #3F51B5; 
            font-size: 12px; 
            padding: 8px;
            background-color: #F3F4F6;
            border-radius: 6px;
            border-left: 4px solid #3F51B5;
        """)
        group_info_layout.addWidget(group_info)
        
        layout.addWidget(group_info_group)

        # 执行按钮
        self.broadcast_btn = QPushButton("🚀 开始群发消息")
        self.broadcast_btn.setStyleSheet(self.button_styles['task'])
        self.broadcast_btn.clicked.connect(self.start_broadcast)
        layout.addWidget(self.broadcast_btn)
        
        layout.addStretch()
        
        return tab
    
    def create_group_manage_tab(self):
        """创建群管理标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #2196F3;
                border: 2px solid #E3F2FD;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.group_account_list = QListWidget()
        self.group_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.group_account_list.setMaximumHeight(100)
        self.group_account_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.group_account_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
                selection-background-color: #E3F2FD;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #F0F0F0;
            }
            QListWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
        """)
        account_layout.addWidget(self.group_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.group_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.group_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 群列表
        self.group_table = QTableWidget()
        self.group_table.setColumnCount(4)
        self.group_table.setHorizontalHeaderLabels(["📱 账号", "👥 群名称", "🔢 群ID", "🔒 禁言状态"])
        self.group_table.horizontalHeader().setStretchLastSection(True)
        self.group_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.group_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #E0E0E0;
                background-color: white;
                alternate-background-color: #F8F9FA;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                selection-background-color: #E3F2FD;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #F0F0F0;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QHeaderView::section {
                background-color: #F5F5F5;
                padding: 8px;
                border: none;
                border-right: 1px solid #D0D0D0;
                font-weight: bold;
                color: #424242;
            }
        """)
        # 设置列宽调整行为
        self.group_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # 账号根据内容调整宽度
        self.group_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 群名称自动伸缩
        self.group_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # 群ID根据内容调整宽度
        self.group_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # 禁言状态根据内容调整宽度
        layout.addWidget(self.group_table)
        
        # 群管理操作
        manage_group = QGroupBox("⚙️ 群管理操作")
        manage_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #4CAF50;
                border: 2px solid #E8F5E9;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        manage_layout = QHBoxLayout(manage_group)
        
        self.reload_groups_btn = QPushButton("🔄 重新加载群组记录")
        self.reload_groups_btn.setStyleSheet(self.button_styles['primary'])
        self.reload_groups_btn.clicked.connect(self.reload_group_records)
        manage_layout.addWidget(self.reload_groups_btn)
        
        self.check_groups_btn = QPushButton("🔍 检测已加入的群")
        self.check_groups_btn.setStyleSheet(self.button_styles['info'])
        self.check_groups_btn.clicked.connect(self.check_joined_groups)
        manage_layout.addWidget(self.check_groups_btn)
        
        self.check_mute_btn = QPushButton("🔇 检测禁言状态")
        self.check_mute_btn.setStyleSheet(self.button_styles['secondary'])
        self.check_mute_btn.clicked.connect(self.check_mute_status)
        manage_layout.addWidget(self.check_mute_btn)
        
        self.leave_all_groups_btn = QPushButton("🚪 退出所有群")
        self.leave_all_groups_btn.setStyleSheet(self.button_styles['danger'])
        self.leave_all_groups_btn.clicked.connect(self.leave_all_groups)
        manage_layout.addWidget(self.leave_all_groups_btn)
        
        layout.addWidget(manage_group)
        
        # 禁言管理
        mute_group = QGroupBox("🔇 禁言管理")
        mute_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #FF9800;
                border: 2px solid #FFF3E0;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        mute_layout = QFormLayout(mute_group)
        
        self.unmute_interval_spin = QSpinBox()
        self.unmute_interval_spin.setRange(1, 3600)
        self.unmute_interval_spin.setValue(60)
        self.unmute_interval_spin.setSuffix(" 秒")
        self.unmute_interval_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #FF9800;
            }
        """)
        mute_layout.addRow("⏱️ 解禁间隔:", self.unmute_interval_spin)
        
        self.unmute_round_spin = QSpinBox()
        self.unmute_round_spin.setRange(1, 86400)
        self.unmute_round_spin.setValue(3600)
        self.unmute_round_spin.setSuffix(" 秒")
        self.unmute_round_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #FF9800;
            }
        """)
        mute_layout.addRow("🔄 轮次间隔:", self.unmute_round_spin)
        
        self.auto_unmute_checkbox = QCheckBox("🤖 自动定时解禁")
        self.auto_unmute_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #FF9800;
            }
            QCheckBox::indicator:checked {
                background-color: #FF9800;
            }
        """)
        mute_layout.addRow("", self.auto_unmute_checkbox)
        
        layout.addWidget(mute_group)
        
        # 执行按钮
        self.unmute_btn = QPushButton("🚀 开始解禁")
        self.unmute_btn.setStyleSheet(self.button_styles['task'])
        self.unmute_btn.clicked.connect(self.start_unmute)
        layout.addWidget(self.unmute_btn)
        
        layout.addStretch()
        
        return tab
    
    def create_channel_tab(self):
        """创建频道标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #3F51B5;
                border: 2px solid #E8EAF6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.channel_account_list = QListWidget()
        self.channel_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.channel_account_list.setMaximumHeight(100)
        self.channel_account_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.channel_account_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
                selection-background-color: #E8EAF6;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #F0F0F0;
            }
            QListWidget::item:selected {
                background-color: #3F51B5;
                color: white;
            }
        """)
        account_layout.addWidget(self.channel_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.channel_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.channel_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 创建设置
        settings_group = QGroupBox("⚙️ 创建设置")
        settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #9C27B0;
                border: 2px solid #F3E5F5;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        settings_layout = QFormLayout(settings_group)
        
        # 创建数量
        self.channel_count_spin = QSpinBox()
        self.channel_count_spin.setRange(1, 100)
        self.channel_count_spin.setValue(1)
        self.channel_count_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #9C27B0;
            }
        """)
        settings_layout.addRow("🔢 创建数量:", self.channel_count_spin)
        
        # 创建间隔
        self.channel_interval_spin = QSpinBox()
        self.channel_interval_spin.setRange(1, 86400)
        self.channel_interval_spin.setValue(7560)
        self.channel_interval_spin.setSuffix(" 秒")
        self.channel_interval_spin.setStyleSheet("""
            QSpinBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #9C27B0;
            }
        """)
        settings_layout.addRow("⏱️ 创建间隔:", self.channel_interval_spin)
        
        layout.addWidget(settings_group)
        
        # 管理员设置
        admin_group = QGroupBox("👑 管理员设置")
        admin_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #FF5722;
                border: 2px solid #FBE9E7;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        admin_layout = QFormLayout(admin_group)
        
        self.add_admins_checkbox = QCheckBox("👥 添加管理员")
        self.add_admins_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #FF5722;
            }
            QCheckBox::indicator:checked {
                background-color: #FF5722;
            }
        """)
        admin_layout.addRow("", self.add_admins_checkbox)
        
        self.channel_admin_input = QLineEdit()
        self.channel_admin_input.setPlaceholderText("管理员用户名，多个用逗号分隔")
        self.channel_admin_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #FF5722;
            }
        """)
        admin_layout.addRow("👤 管理员用户名:", self.channel_admin_input)
        
        self.add_bots_checkbox = QCheckBox("🤖 添加机器人管理员")
        self.add_bots_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 13px;
                font-weight: bold;
                color: #FF5722;
            }
            QCheckBox::indicator:checked {
                background-color: #FF5722;
            }
        """)
        admin_layout.addRow("", self.add_bots_checkbox)
        
        self.channel_bot_input = QLineEdit()
        self.channel_bot_input.setPlaceholderText("机器人用户名，多个用逗号分隔")
        self.channel_bot_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #FF5722;
            }
        """)
        admin_layout.addRow("🤖 机器人用户名:", self.channel_bot_input)
        
        layout.addWidget(admin_group)

        # 执行按钮
        self.create_channel_btn = QPushButton("🚀 开始创建频道")
        self.create_channel_btn.setStyleSheet(self.button_styles['task'])
        self.create_channel_btn.clicked.connect(self.start_create_channels)
        layout.addWidget(self.create_channel_btn)
        
        layout.addStretch()
        
        return tab
    
    def create_security_tab(self):
        """创建账号安全标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #D32F2F;
                border: 2px solid #FFEBEE;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.security_account_list = QListWidget()
        self.security_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.security_account_list.setMaximumHeight(100)
        account_layout.addWidget(self.security_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.security_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.security_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 密码管理
        password_group = QGroupBox("🔐 二次验证密码管理")
        password_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #1976D2;
                border: 2px solid #E3F2FD;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        password_layout = QFormLayout(password_group)

        self.old_password_input = QLineEdit()
        self.old_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.old_password_input.setPlaceholderText("🔑 可手动输入或点击下方按钮自动填入")
        self.old_password_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #1976D2;
            }
        """)
        password_layout.addRow("🔐 当前密码:", self.old_password_input)

        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password_input.setPlaceholderText("🆕 输入新的二次验证密码")
        self.new_password_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #4CAF50;
            }
        """)
        password_layout.addRow("🆕 新密码:", self.new_password_input)

        # 自动填入密码按钮
        auto_fill_btn = QPushButton("🤖 自动填入已保存密码")
        auto_fill_btn.setStyleSheet(self.button_styles['info'])
        auto_fill_btn.clicked.connect(self.auto_fill_saved_passwords)
        password_layout.addRow("", auto_fill_btn)

        self.change_password_btn = QPushButton("🔄 更改密码")
        self.change_password_btn.setStyleSheet(self.button_styles['warning'])
        self.change_password_btn.clicked.connect(self.change_two_factor_passwords)
        password_layout.addRow("", self.change_password_btn)

        layout.addWidget(password_group)
        
        # 会话管理
        session_group = QGroupBox("💻 设备会话管理")
        session_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #7B1FA2;
                border: 2px solid #F3E5F5;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        session_layout = QVBoxLayout(session_group)
        
        # 会话信息显示
        self.session_table = QTableWidget()
        self.session_table.setColumnCount(6)
        self.session_table.setHorizontalHeaderLabels(["📱 账号", "📱 设备型号", "⚙️ 平台", "📱 应用", "🌍 国家", "✅ 当前"])
        self.session_table.horizontalHeader().setStretchLastSection(True)
        self.session_table.setMaximumHeight(200)
        self.session_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #E0E0E0;
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #F5F5F5;
                padding: 6px;
                border: none;
                font-weight: bold;
            }
        """)
        # 设置列宽调整行为
        self.session_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # 账号根据内容调整宽度
        self.session_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 设备型号自动伸缩
        self.session_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # 平台根据内容调整宽度
        self.session_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # 应用根据内容调整宽度
        self.session_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # 国家根据内容调整宽度
        self.session_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # 当前固定宽度
        self.session_table.setColumnWidth(5, 60)  # 当前列宽度
        session_layout.addWidget(self.session_table)
        
        # 会话操作按钮
        session_button_layout = QHBoxLayout()
        
        self.refresh_sessions_btn = QPushButton("🔄 刷新会话信息")
        self.refresh_sessions_btn.setStyleSheet(self.button_styles['primary'])
        self.refresh_sessions_btn.clicked.connect(self.refresh_session_info)
        session_button_layout.addWidget(self.refresh_sessions_btn)
        
        self.terminate_sessions_btn = QPushButton("🚫 踢出其他设备")
        self.terminate_sessions_btn.setStyleSheet(self.button_styles['danger'])
        self.terminate_sessions_btn.clicked.connect(self.terminate_other_sessions)
        session_button_layout.addWidget(self.terminate_sessions_btn)
        
        session_layout.addLayout(session_button_layout)
        layout.addWidget(session_group)
        
        layout.addStretch()
        
        return tab

    def auto_fill_saved_passwords(self):
        """自动填入已保存的密码"""
        selected_accounts = self.get_selected_from_list(self.security_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        # 先重置输入框状态（替代清空方法）
        self.old_password_input.setReadOnly(False)
        
        # 检查所有选中账号是否都有保存的密码
        accounts_with_password = []
        accounts_without_password = []
        password_summary = []  # 用于显示密码摘要
        
        for phone in selected_accounts:
            saved_password = self.config_manager.get_saved_password(phone)
            if saved_password:
                accounts_with_password.append(phone)
                # 显示密码前3位和后2位，中间用*代替
                masked_password = saved_password[:3] + "*" * (len(saved_password) - 5) + saved_password[-2:] if len(saved_password) > 5 else "*" * len(saved_password)
                password_summary.append(f"{phone}: {masked_password}")
            else:
                accounts_without_password.append(phone)
        
        if not accounts_with_password:
            QMessageBox.warning(
                self, "警告", 
                f"所有选中的账号都没有保存的密码：\n{', '.join(accounts_without_password)}\n\n"
                f"请手动输入密码或先为账号保存密码"
            )
            return
        
        # 显示将要使用的密码信息
        if accounts_without_password:
            result = QMessageBox.question(
                self, "部分账号无保存密码", 
                f"有保存密码的账号：\n{chr(10).join(password_summary)}\n\n"
                f"没有保存密码的账号：\n{', '.join(accounts_without_password)}\n\n"
                f"是否继续？（没有保存密码的账号将使用手动输入的密码）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        
        if len(selected_accounts) == 1 and accounts_with_password:
            # 单个账号且有保存密码，直接填入
            phone = selected_accounts[0]
            saved_password = self.config_manager.get_saved_password(phone)
            self.old_password_input.setText(saved_password)
            self.old_password_input.setReadOnly(True)
            self.old_password_input.setPlaceholderText(f"已自动填入 {phone} 的保存密码")
            self.log(f"已自动填入 {phone} 的保存密码")
        else:
            # 多个账号或混合模式，启用智能模式
            self.old_password_input.setText("【智能模式】")
            self.old_password_input.setReadOnly(True)
            self.old_password_input.setPlaceholderText("智能模式：自动使用各账号对应的密码")
            self.log(f"已启用智能模式，{len(accounts_with_password)} 个账号使用保存密码，{len(accounts_without_password)} 个账号需手动输入")
        
        QMessageBox.information(
            self, "成功", 
            f"密码填入完成！\n\n"
            f"使用保存密码：{len(accounts_with_password)} 个账号\n"
            f"需手动输入：{len(accounts_without_password)} 个账号\n\n"
            f"请输入新密码，然后点击'更改密码'"
        )

    def change_two_factor_passwords(self):
        """更改二次验证密码"""
        selected_accounts = self.get_selected_from_list(self.security_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        old_password = self.old_password_input.text().strip()
        new_password = self.new_password_input.text().strip()
        
        # 检查是否为智能模式
        smart_mode = (old_password == "【智能模式】")
        
        if not smart_mode and not old_password:
            QMessageBox.warning(self, "警告", "请输入当前密码或点击'自动填入已保存密码'")
            return
        
        if not new_password:
            QMessageBox.warning(self, "警告", "请输入新密码")
            return
        
        if len(new_password) < 8:
            QMessageBox.warning(self, "警告", "新密码长度至少8位")
            return
        
        # 准备密码更改计划
        change_plan = []
        manual_input_accounts = []
        
        for phone in selected_accounts:
            if smart_mode:
                saved_password = self.config_manager.get_saved_password(phone)
                if saved_password:
                    change_plan.append(f"{phone}: 使用保存密码")
                else:
                    change_plan.append(f"{phone}: 使用手动输入密码")
                    manual_input_accounts.append(phone)
            else:
                change_plan.append(f"{phone}: 使用统一密码")
        
        # 如果有需要手动输入密码的账号，获取手动密码
        manual_password = None
        if manual_input_accounts:
            manual_password, ok = QInputDialog.getText(
                self, "手动输入密码", 
                f"以下账号没有保存密码，请输入当前密码：\n{', '.join(manual_input_accounts)}",
                QLineEdit.EchoMode.Password
            )
            if not ok or not manual_password:
                QMessageBox.warning(self, "取消", "已取消密码更改操作")
                return
        
        mode_text = "智能模式" if smart_mode else "统一模式"
        reply = QMessageBox.question(
            self, "确认更改密码", 
            f"确定要更改密码吗？\n\n"
            f"模式：{mode_text}\n"
            f"账号数量：{len(selected_accounts)}\n"
            f"新密码长度：{len(new_password)} 位\n\n"
            f"更改计划：\n{chr(10).join(change_plan)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.log(f"开始为 {len(selected_accounts)} 个账号更改二次验证密码（{mode_text}）")
        
        # 在事件循环中执行任务
        async def do_change_passwords():
            success_count = 0
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'change_password', '更改密码')
                    
                    # 确定使用的旧密码
                    if smart_mode:
                        # 智能模式：优先使用保存密码，否则使用手动输入密码
                        saved_password = self.config_manager.get_saved_password(phone)
                        actual_old_password = saved_password if saved_password else manual_password
                        
                        if not actual_old_password:
                            self.log(f"{phone} ❌ 没有可用的旧密码，跳过")
                            self.remove_running_task(phone, 'change_password')
                            continue
                            
                        password_source = "保存密码" if saved_password else "手动输入密码"
                        self.log(f"{phone} 使用{password_source}作为当前密码")
                    else:
                        # 统一模式：使用输入的密码
                        actual_old_password = old_password
                        self.log(f"{phone} 使用统一密码作为当前密码")
                    
                    self.log(f"{phone} 开始更改密码... (密码长度: 当前{len(actual_old_password)}位, 新{len(new_password)}位)")
                    
                    success = await self.async_handler.change_two_factor_password(
                        phone, actual_old_password, new_password
                    )
                    
                    if success:
                        # 更新保存的密码
                        self.config_manager.save_password(phone, new_password)
                        success_count += 1
                        self.log(f"{phone} ✅ 密码更改成功，已更新保存的密码")
                    else:
                        self.log(f"{phone} ❌ 密码更改失败，请检查日志获取详细错误信息")
                    
                    self.remove_running_task(phone, 'change_password')
                    
                except Exception as e:
                    self.log(f"{phone} ❌ 更改密码时发生异常: {str(e)}")
                    import traceback
                    self.log(f"{phone} 详细错误信息: {traceback.format_exc()}")
                    self.remove_running_task(phone, 'change_password')
            
            # 保存配置
            self.config_manager.save_config()
            
            QMetaObject.invokeMethod(
                self, "on_password_change_finished",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, success_count),
                Q_ARG(int, len(selected_accounts))
            )
        
        asyncio.run_coroutine_threadsafe(do_change_passwords(), self.event_loop_thread.loop)

    def execute_smart_password_change(self, selected_accounts, new_password):
        """执行智能批量密码更改"""
        self.log(f"开始智能批量更改 {len(selected_accounts)} 个账号的密码")
    
        async def do_smart_change():
            success_count = 0
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'change_password', '智能更改密码')
                
                    # 使用该账号保存的密码作为旧密码
                    old_password = self.config_manager.get_saved_password(phone)
                
                    success = await self.async_handler.change_two_factor_password(
                        phone, old_password, new_password
                    )
                
                    if success:
                        # 更新保存的密码
                        self.config_manager.save_password(phone, new_password)
                        success_count += 1
                        self.log(f"{phone} 智能密码更改成功")
                
                    self.remove_running_task(phone, 'change_password')
                
                except Exception as e:
                    self.log(f"{phone} 智能更改密码错误: {str(e)}")
                    self.remove_running_task(phone, 'change_password')
        
            # 保存配置
            self.config_manager.save_config()
        
            QMetaObject.invokeMethod(
                self, "on_password_change_finished",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, success_count),
                Q_ARG(int, len(selected_accounts))
            )
    
        asyncio.run_coroutine_threadsafe(do_smart_change(), self.event_loop_thread.loop)

    def execute_unified_password_change(self, selected_accounts, old_password, new_password):
        """执行统一批量密码更改"""
        self.log(f"开始统一批量更改 {len(selected_accounts)} 个账号的密码")
    
        async def do_unified_change():
            success_count = 0
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'change_password', '统一更改密码')
                
                    success = await self.async_handler.change_two_factor_password(
                        phone, old_password, new_password
                    )
                
                    if success:
                        # 更新保存的密码
                        self.config_manager.save_password(phone, new_password)
                        success_count += 1
                        self.log(f"{phone} 统一密码更改成功")
                
                    self.remove_running_task(phone, 'change_password')
                
                except Exception as e:
                    self.log(f"{phone} 统一更改密码错误: {str(e)}")
                    self.remove_running_task(phone, 'change_password')
        
            # 保存配置
            self.config_manager.save_config()
        
            QMetaObject.invokeMethod(
                self, "on_password_change_finished",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, success_count),
                Q_ARG(int, len(selected_accounts))
            )
    
        asyncio.run_coroutine_threadsafe(do_unified_change(), self.event_loop_thread.loop)

    def refresh_session_info(self):
        """刷新会话信息"""
        selected_accounts = self.get_selected_from_list(self.security_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
    
        self.log("开始获取会话信息")
        self.session_table.setRowCount(0)
    
        # 在事件循环中执行任务
        async def do_refresh_sessions():
            all_sessions = []
            for phone in selected_accounts:
                try:
                    sessions = await self.async_handler.get_active_sessions(phone)
                    for session in sessions:
                        session['phone'] = phone
                    all_sessions.extend(sessions)
                
                except Exception as e:
                    self.log(f"获取 {phone} 会话信息错误: {str(e)}")
        
            # 更新会话表格
            QMetaObject.invokeMethod(
                self, "update_session_table",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, all_sessions)
            )
    
        asyncio.run_coroutine_threadsafe(do_refresh_sessions(), self.event_loop_thread.loop)

    def terminate_other_sessions(self):
        """踢出其他设备"""
        selected_accounts = self.get_selected_from_list(self.security_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
    
        reply = QMessageBox.question(
            self, "确认", 
            f"确定要踢出选中 {len(selected_accounts)} 个账号的所有其他设备吗？\n"
            f"这将终止除当前设备外的所有会话。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
    
        if reply != QMessageBox.StandardButton.Yes:
            return
    
        self.log(f"开始踢出 {len(selected_accounts)} 个账号的其他设备")
    
        # 在事件循环中执行任务
        async def do_terminate_sessions():
            success_count = 0
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'terminate_sessions', '踢出设备')
                
                    success = await self.async_handler.terminate_other_sessions(phone)
                    if success:
                        success_count += 1
                
                    self.remove_running_task(phone, 'terminate_sessions')
                
                except Exception as e:
                    self.log(f"{phone} 踢出设备错误: {str(e)}")
                    self.remove_running_task(phone, 'terminate_sessions')
        
            QMetaObject.invokeMethod(
                self, "on_terminate_sessions_finished",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, success_count),
                Q_ARG(int, len(selected_accounts))
            )
    
        asyncio.run_coroutine_threadsafe(do_terminate_sessions(), self.event_loop_thread.loop)

    @pyqtSlot(list)
    def update_session_table(self, sessions):
        """更新会话表格"""
        self.session_table.setRowCount(len(sessions))
    
        for i, session in enumerate(sessions):
            self.session_table.setItem(i, 0, QTableWidgetItem(session.get('phone', '')))
            self.session_table.setItem(i, 1, QTableWidgetItem(session.get('device_model', '未知')))
            self.session_table.setItem(i, 2, QTableWidgetItem(session.get('platform', '未知')))
            self.session_table.setItem(i, 3, QTableWidgetItem(session.get('app_name', '未知')))
            self.session_table.setItem(i, 4, QTableWidgetItem(session.get('country', '未知')))
        
            # 当前会话标识
            current_text = "是" if session.get('current', False) else "否"
            current_item = QTableWidgetItem(current_text)
            if session.get('current', False):
                current_item.setForeground(QColor('green'))
            self.session_table.setItem(i, 5, current_item)

    @pyqtSlot(int, int)
    def on_password_change_finished(self, success_count, total_count):
        """密码更改完成"""
        self.log(f"密码更改完成，成功: {success_count}/{total_count}")
        
        # 直接重置输入框状态（不调用清空方法）
        self.old_password_input.clear()
        self.old_password_input.setReadOnly(False)
        self.old_password_input.setPlaceholderText("可手动输入或点击下方按钮自动填入")
        self.new_password_input.clear()
        
        QMessageBox.information(
            self, "完成", 
            f"密码更改完成\n\n"
            f"成功：{success_count} 个账号\n"
            f"失败：{total_count - success_count} 个账号\n"
            f"总计：{total_count} 个账号"
        )

    @pyqtSlot(int, int)
    def on_terminate_sessions_finished(self, success_count, total_count):
        """踢出设备完成"""
        self.log(f"踢出设备完成，成功: {success_count}/{total_count}")
        QMessageBox.information(
            self, "完成", 
            f"踢出设备完成\n成功: {success_count}/{total_count}"
        )
    def create_privacy_tab(self):
        """创建隐私设置标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账号选择
        account_group = QGroupBox("👥 选择账号")
        account_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #D32F2F;
                border: 2px solid #FFEBEE;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        account_layout = QVBoxLayout(account_group)
        
        self.privacy_account_list = QListWidget()
        self.privacy_account_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.privacy_account_list.setMaximumHeight(100)
        self.privacy_account_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.privacy_account_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
                selection-background-color: #FFEBEE;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #F0F0F0;
            }
            QListWidget::item:selected {
                background-color: #D32F2F;
                color: white;
            }
        """)
        account_layout.addWidget(self.privacy_account_list)
        
        # 快速选择按钮
        quick_select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("✅ 全选")
        select_all_btn.setStyleSheet(self.button_styles['success'])
        select_all_btn.clicked.connect(lambda: self.select_all_in_list(self.privacy_account_list))
        quick_select_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("❌ 取消全选")
        deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        deselect_all_btn.clicked.connect(lambda: self.deselect_all_in_list(self.privacy_account_list))
        quick_select_layout.addWidget(deselect_all_btn)
        
        account_layout.addLayout(quick_select_layout)
        layout.addWidget(account_group)
        
        # 隐私设置配置
        privacy_settings_group = QGroupBox("🔒 隐私设置配置")
        privacy_settings_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #1976D2;
                border: 2px solid #E3F2FD;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        privacy_settings_layout = QVBoxLayout(privacy_settings_group)
        
        # 隐私设置选项表单
        privacy_options_layout = QFormLayout()
        
        # 手机号码隐私
        self.phone_privacy_combo = QComboBox()
        self.phone_privacy_combo.addItems([
            "所有人可见",
            "仅联系人可见", 
            "任何人都不可见"
        ])
        self.phone_privacy_combo.setCurrentIndex(2)  # 默认选择"任何人都不可见"
        self.phone_privacy_combo.setStyleSheet("""
            QComboBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QComboBox:focus {
                border: 2px solid #1976D2;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #E0E0E0;
            }
        """)
        privacy_options_layout.addRow("📱 手机号码:", self.phone_privacy_combo)
        
        # 最后上线时间隐私
        self.lastseen_privacy_combo = QComboBox()
        self.lastseen_privacy_combo.addItems([
            "所有人可见",
            "仅联系人可见",
            "任何人都不可见"
        ])
        self.lastseen_privacy_combo.setCurrentIndex(2)  # 默认选择"任何人都不可见"
        self.lastseen_privacy_combo.setStyleSheet("""
            QComboBox {
                border: 2px solid #E0E0E0;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: white;
            }
            QComboBox:focus {
                border: 2px solid #1976D2;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #E0E0E0;
            }
        """)
        privacy_options_layout.addRow("⏰ 最后上线时间:", self.lastseen_privacy_combo)
        
        privacy_settings_layout.addLayout(privacy_options_layout)
        layout.addWidget(privacy_settings_group)
        
        # 隐私设置操作
        privacy_actions_group = QGroupBox("⚙️ 隐私设置操作")
        privacy_actions_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #4CAF50;
                border: 2px solid #E8F5E9;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        privacy_actions_layout = QVBoxLayout(privacy_actions_group)
        
        # 主要操作按钮
        main_actions_layout = QHBoxLayout()
        
        self.set_privacy_btn = QPushButton("🚀 应用隐私设置")
        self.set_privacy_btn.setStyleSheet(self.button_styles['task'])
        self.set_privacy_btn.clicked.connect(self.set_privacy_settings)
        main_actions_layout.addWidget(self.set_privacy_btn)
        
        self.get_privacy_btn = QPushButton("🔍 获取当前设置")
        self.get_privacy_btn.setStyleSheet(self.button_styles['info'])
        self.get_privacy_btn.clicked.connect(self.get_privacy_settings)
        main_actions_layout.addWidget(self.get_privacy_btn)
        
        privacy_actions_layout.addLayout(main_actions_layout)
        
        layout.addWidget(privacy_actions_group)
        
        # 隐私设置状态显示
        privacy_status_group = QGroupBox("📊 隐私设置状态")
        privacy_status_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #673AB7;
                border: 2px solid #EDE7F6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
            }
        """)
        privacy_status_layout = QVBoxLayout(privacy_status_group)
        
        self.privacy_status_text = QTextEdit()
        self.privacy_status_text.setMaximumHeight(150)
        self.privacy_status_text.setReadOnly(True)
        self.privacy_status_text.setPlaceholderText("隐私设置状态和结果将在这里显示...")
        self.privacy_status_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                background-color: #FAFAFA;
                font-family: Consolas, monospace;
                font-size: 12px;
                padding: 8px;
            }
        """)
        privacy_status_layout.addWidget(self.privacy_status_text)
        
        # 清空状态按钮
        clear_status_btn = QPushButton("🗑️ 清空状态")
        clear_status_btn.setStyleSheet(self.button_styles['warning'])
        clear_status_btn.clicked.connect(self.clear_privacy_status)
        privacy_status_layout.addWidget(clear_status_btn)
        
        layout.addWidget(privacy_status_group)
        
        layout.addStretch()
        
        return tab

    def clear_privacy_status(self):
        """清空隐私状态显示"""
        self.privacy_status_text.clear()
        self.log("隐私状态显示已清空")

    def set_privacy_settings(self):
        """设置隐私设置"""
        selected_accounts = self.get_selected_from_list(self.privacy_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        # 获取隐私设置选项
        privacy_settings = {
            'phone_privacy': self.phone_privacy_combo.currentIndex(),
            'lastseen_privacy': self.lastseen_privacy_combo.currentIndex(),
        }
        
        # 显示确认对话框
        privacy_names = ["所有人可见", "仅联系人可见", "任何人都不可见"]
        
        settings_text = f"""即将为 {len(selected_accounts)} 个账号设置隐私:

    📱 手机号码: {privacy_names[privacy_settings['phone_privacy']]}
    ⏰ 最后上线时间: {privacy_names[privacy_settings['lastseen_privacy']]}

    确定要应用这些设置吗？"""
        
        reply = QMessageBox.question(
            self, "确认隐私设置", settings_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.log(f"开始为 {len(selected_accounts)} 个账号设置隐私")
        self.privacy_status_text.append(f"🔄 开始为 {len(selected_accounts)} 个账号设置隐私...")
        
        # 在事件循环中执行任务
        async def do_set_privacy():
            success_count = 0
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'set_privacy', '设置隐私')
                    
                    # 在状态显示中添加进度信息
                    QMetaObject.invokeMethod(
                        self.privacy_status_text, "append",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, f"📱 {phone}: 开始设置隐私...")
                    )
                    
                    success = await self.async_handler.set_privacy_settings(phone, privacy_settings)
                    if success:
                        success_count += 1
                        self.log(f"{phone} 隐私设置成功")
                        QMetaObject.invokeMethod(
                            self.privacy_status_text, "append",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, f"✅ {phone}: 隐私设置成功")
                        )
                    else:
                        self.log(f"{phone} 隐私设置失败")
                        QMetaObject.invokeMethod(
                            self.privacy_status_text, "append",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, f"❌ {phone}: 隐私设置失败")
                        )
                    
                    self.remove_running_task(phone, 'set_privacy')
                    
                except Exception as e:
                    self.log(f"{phone} 设置隐私时发生错误: {str(e)}")
                    QMetaObject.invokeMethod(
                        self.privacy_status_text, "append",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, f"❌ {phone}: 设置异常 - {str(e)}")
                    )
                    self.remove_running_task(phone, 'set_privacy')
            
            QMetaObject.invokeMethod(
                self, "on_privacy_settings_finished",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, success_count),
                Q_ARG(int, len(selected_accounts))
            )
        
        asyncio.run_coroutine_threadsafe(do_set_privacy(), self.event_loop_thread.loop)

    def get_privacy_settings(self):
        """获取当前隐私设置"""
        selected_accounts = self.get_selected_from_list(self.privacy_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        self.log(f"开始获取 {len(selected_accounts)} 个账号的隐私设置")
        self.privacy_status_text.append(f"🔍 开始获取 {len(selected_accounts)} 个账号的隐私设置...")
        
        # 在事件循环中执行任务
        async def do_get_privacy():
            all_privacy_info = []
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'get_privacy', '获取隐私设置')
                    
                    QMetaObject.invokeMethod(
                        self.privacy_status_text, "append",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, f"📱 {phone}: 获取隐私设置...")
                    )
                    
                    privacy_info = await self.async_handler.get_privacy_settings(phone)
                    if privacy_info:
                        privacy_info['phone'] = phone
                        all_privacy_info.append(privacy_info)
                        self.log(f"{phone} 隐私设置获取成功")
                        QMetaObject.invokeMethod(
                            self.privacy_status_text, "append",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, f"✅ {phone}: 隐私设置获取成功")
                        )
                    else:
                        self.log(f"{phone} 隐私设置获取失败")
                        QMetaObject.invokeMethod(
                            self.privacy_status_text, "append",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, f"❌ {phone}: 隐私设置获取失败")
                        )
                    
                    self.remove_running_task(phone, 'get_privacy')
                    
                except Exception as e:
                    self.log(f"{phone} 获取隐私设置时发生错误: {str(e)}")
                    QMetaObject.invokeMethod(
                        self.privacy_status_text, "append",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, f"❌ {phone}: 获取异常 - {str(e)}")
                    )
                    self.remove_running_task(phone, 'get_privacy')
            
            QMetaObject.invokeMethod(
                self, "show_privacy_info",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, all_privacy_info)
            )
        
        asyncio.run_coroutine_threadsafe(do_get_privacy(), self.event_loop_thread.loop)

    @pyqtSlot(int, int)
    def on_privacy_settings_finished(self, success_count, total_count):
        """隐私设置完成"""
        self.log(f"隐私设置完成，成功: {success_count}/{total_count}")
        
        # 在状态显示中添加完成信息
        if success_count == total_count:
            self.privacy_status_text.append(f"🎉 隐私设置全部完成！成功: {success_count}/{total_count}")
        else:
            self.privacy_status_text.append(f"⚠️ 隐私设置部分完成。成功: {success_count}/{total_count}")
        
        # 滚动到底部
        scrollbar = self.privacy_status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        QMessageBox.information(
            self, "完成", 
            f"隐私设置完成\n\n"
            f"成功：{success_count} 个账号\n"
            f"失败：{total_count - success_count} 个账号\n"
            f"总计：{total_count} 个账号"
        )
    
    @pyqtSlot(list)
    def show_privacy_info(self, all_privacy_info):
        """显示隐私信息"""
        if not all_privacy_info:
            self.privacy_status_text.append("❌ 没有获取到任何隐私信息")
            return
        
        privacy_names = ["所有人可见", "仅联系人可见", "任何人都不可见", "未知"]
        
        self.privacy_status_text.append("📊 隐私设置查询结果：")
        self.privacy_status_text.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        for privacy_info in all_privacy_info:
            phone = privacy_info.get('phone', '未知')
            phone_privacy = privacy_info.get('phone_privacy', -1)
            lastseen_privacy = privacy_info.get('lastseen_privacy', -1)
            
            phone_privacy_name = privacy_names[phone_privacy] if 0 <= phone_privacy <= 2 else privacy_names[3]
            lastseen_privacy_name = privacy_names[lastseen_privacy] if 0 <= lastseen_privacy <= 2 else privacy_names[3]
            
            self.privacy_status_text.append(f"📱 账号: {phone}")
            self.privacy_status_text.append(f"  📞 手机号码: {phone_privacy_name}")
            self.privacy_status_text.append(f"  ⏰ 最后上线: {lastseen_privacy_name}")
            self.privacy_status_text.append("")
        
        # 滚动到底部
        scrollbar = self.privacy_status_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def create_account_panel(self):
        """创建账号面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 标题
        title = QLabel("📱 账号列表")
        title.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            padding: 10px;
            color: #2196F3;
            background-color: #E3F2FD;
            border-radius: 8px;
            margin-bottom: 10px;
        """)
        layout.addWidget(title)
        
        # 账号表格
        self.account_table = QTableWidget()
        self.account_table.setColumnCount(7)
        self.account_table.setHorizontalHeaderLabels(["选择", "📱 手机号", "👤 名字", "👤 姓氏", "🏷️ 用户名", "🔑 API ID", "📊 状态"])
        self.account_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.account_table.horizontalHeader().setStretchLastSection(True)
        
        # 美化表格
        self.account_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #E0E0E0;
                background-color: white;
                alternate-background-color: #F8F9FA;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                selection-background-color: #E3F2FD;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #F0F0F0;
            }
            QTableWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QHeaderView::section {
                background-color: #F5F5F5;
                padding: 8px;
                border: none;
                border-right: 1px solid #D0D0D0;
                font-weight: bold;
                color: #424242;
            }
        """)
        
        # 设置列宽
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # 选择列固定宽度
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # 手机号自适应内容
        self.account_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # 名字自适应内容
        self.account_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # 姓氏拉伸
        self.account_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # 用户名拉伸
        self.account_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # API ID自适应内容
        self.account_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # 状态拉伸
        # 设置固定宽度的列
        self.account_table.setColumnWidth(0, 45)  # 选择列宽度
        layout.addWidget(self.account_table)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        self.select_all_btn = QPushButton("✅ 全选")
        self.select_all_btn.setStyleSheet(self.button_styles['success'])
        self.select_all_btn.clicked.connect(self.select_all_accounts)
        button_layout.addWidget(self.select_all_btn)
        
        self.deselect_all_btn = QPushButton("❌ 取消全选")
        self.deselect_all_btn.setStyleSheet(self.button_styles['secondary'])
        self.deselect_all_btn.clicked.connect(self.deselect_all_accounts)
        button_layout.addWidget(self.deselect_all_btn)
        
        # 获取账号资料按钮
        self.refresh_profile_btn = QPushButton("🔄 获取账号资料")
        self.refresh_profile_btn.setStyleSheet(self.button_styles['info'])
        self.refresh_profile_btn.clicked.connect(self.refresh_selected_profiles)
        button_layout.addWidget(self.refresh_profile_btn)
        
        self.delete_account_btn = QPushButton("🗑️ 删除选中")
        self.delete_account_btn.setStyleSheet(self.button_styles['danger'])
        self.delete_account_btn.clicked.connect(self.delete_selected_accounts)
        button_layout.addWidget(self.delete_account_btn)
        
        layout.addLayout(button_layout)
        
        return panel
    
    def create_log_panel(self):
        """创建日志面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 3, 5, 3)
        layout.setSpacing(3)
        
        # 标题和控制按钮在同一行
        header_layout = QHBoxLayout()
        
        title = QLabel("📜 操作日志")
        title.setStyleSheet("""
            font-size: 13px; 
            font-weight: bold; 
            padding: 2px;
            color: #795548;
        """)
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # 按钮样式保持不变
        self.clear_log_btn = QPushButton("🗑️ 清空")
        self.clear_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 3px 6px;
                border-radius: 3px;
                font-weight: bold;
                font-size: 10px;
                min-width: 40px;
                max-height: 24px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """)
        self.clear_log_btn.clicked.connect(self.clear_log)
        header_layout.addWidget(self.clear_log_btn)
        
        self.export_log_btn = QPushButton("💾 导出")
        self.export_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: white;
                border: none;
                padding: 3px 6px;
                border-radius: 3px;
                font-weight: bold;
                font-size: 10px;
                min-width: 40px;
                max-height: 24px;
            }
            QPushButton:hover {
                background-color: #0097A7;
            }
            QPushButton:pressed {
                background-color: #00695C;
            }
        """)
        self.export_log_btn.clicked.connect(self.export_log)
        header_layout.addWidget(self.export_log_btn)
        
        layout.addLayout(header_layout)
        
        # 日志显示区域 - 移除高度限制，让分割器控制大小
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        # 移除 setMaximumHeight，让分割器控制大小
        self.log_text.setMinimumHeight(80)  # 设置最小高度，防止完全缩小
        self.log_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_text.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, monospace; 
                font-size: 10px;
                background-color: #263238;
                color: #B0BEC5;
                border: 1px solid #37474F;
                border-radius: 4px;
                padding: 4px;
                selection-background-color: #455A64;
            }
        """)
        layout.addWidget(self.log_text)
        
        return panel
    
    def select_all_in_list(self, list_widget):
        """在列表中全选"""
        for i in range(list_widget.count()):
            list_widget.item(i).setSelected(True)
    
    def deselect_all_in_list(self, list_widget):
        """在列表中取消全选"""
        list_widget.clearSelection()
    
    def get_selected_from_list(self, list_widget):
        """从列表获取选中的账号"""
        selected_items = list_widget.selectedItems()
        return [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
    
    def update_account_lists(self):
        """更新所有账号列表"""
        lists = [
            self.profile_account_list,
            self.join_account_list,
            self.stranger_account_list,
            self.contact_account_list,
            self.broadcast_account_list,
            self.group_account_list,
            self.security_account_list,
            self.channel_account_list
        ]
        
        for list_widget in lists:
            list_widget.clear()
        
            for row in range(self.account_table.rowCount()):
                checkbox = self.account_table.cellWidget(row, 0)
                if checkbox and checkbox.isChecked():
                    phone = self.account_table.item(row, 1).text()
                    name = self.account_table.item(row, 2).text()
                    surname = self.account_table.item(row, 3).text()
                
                    display_text = f"{phone} - {name} {surname}".strip()
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, phone)
                    list_widget.addItem(item)
    
    def show_task_list(self):
        """显示任务列表"""
        if not hasattr(self, 'task_list_dialog'):
            self.task_list_dialog = TaskListDialog(self)
            self.task_list_dialog.stop_task.connect(self.stop_single_task)
        
        self.task_list_dialog.refresh_tasks()
        self.task_list_dialog.show()
    
    def stop_single_task(self, phone, task_type):
        """停止单个任务"""
        task_key = f"{phone}_{task_type}"
        if task_key in self.running_tasks:
            # 通过异步处理器停止任务
            if self.async_handler:
                asyncio.run_coroutine_threadsafe(
                    self.async_handler.stop_single_task(phone, task_type),
                    self.event_loop_thread.loop
                )
            
            del self.running_tasks[task_key]
            self.log(f"停止任务: {phone} - {task_type}")
            
            # 刷新任务列表对话框
            if hasattr(self, 'task_list_dialog') and self.task_list_dialog.isVisible():
                self.task_list_dialog.refresh_tasks()
    
    def add_running_task(self, phone, task_type, task_name):
        """添加运行中的任务"""
        task_key = f"{phone}_{task_type}"
        self.running_tasks[task_key] = {
            'name': task_name,
            'status': '运行中',
            'start_time': datetime.now()
        }
    
    def remove_running_task(self, phone, task_type):
        """移除运行中的任务"""
        task_key = f"{phone}_{task_type}"
        if task_key in self.running_tasks:
            del self.running_tasks[task_key]
    
    def start_stranger_monitoring(self):
        """开始陌生人消息监听"""
        selected_accounts = self.get_selected_from_list(self.stranger_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择要监听的账号")
            return
        
        auto_reply = self.auto_reply_checkbox.isChecked()
        bot_notify = self.bot_notify_checkbox.isChecked()
        
        self.log(f"开始监听 {len(selected_accounts)} 个账号的陌生人消息")
        
        # 在事件循环中启动监听
        async def start_monitoring():
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'stranger_monitor', '陌生人消息监听')
                    
                    success = await self.async_handler.start_stranger_message_monitor(
                        phone, auto_reply, bot_notify
                    )
                    
                    if success:
                        self.log(f"{phone} 陌生人消息监听启动成功")
                    else:
                        self.remove_running_task(phone, 'stranger_monitor')
                        
                except Exception as e:
                    self.log(f"{phone} 启动陌生人消息监听失败: {str(e)}")
                    self.remove_running_task(phone, 'stranger_monitor')
        
        asyncio.run_coroutine_threadsafe(start_monitoring(), self.event_loop_thread.loop)
        
        # 更新按钮状态
        self.start_monitor_btn.setEnabled(False)
        self.stop_monitor_btn.setEnabled(True)
    
    def stop_stranger_monitoring(self):
        """停止陌生人消息监听"""
        selected_accounts = self.get_selected_from_list(self.stranger_account_list)
        
        # 在事件循环中停止监听
        async def stop_monitoring():
            for phone in selected_accounts:
                try:
                    await self.async_handler.stop_stranger_message_monitor(phone)
                    self.remove_running_task(phone, 'stranger_monitor')
                    self.log(f"{phone} 陌生人消息监听已停止")
                except Exception as e:
                    self.log(f"{phone} 停止陌生人消息监听失败: {str(e)}")
        
        asyncio.run_coroutine_threadsafe(stop_monitoring(), self.event_loop_thread.loop)
        
        # 更新按钮状态
        self.start_monitor_btn.setEnabled(True)
        self.stop_monitor_btn.setEnabled(False)
    
    def on_stranger_message_received(self, message_data):
        """处理接收到的陌生人消息 - 添加联系人过滤"""
        phone = message_data['phone']
        sender_id = message_data['sender_id']
        sender_name = message_data['sender_name']
        
        # 在这里添加联系人检查
        if self.async_handler:
            # 通过异步处理器检查是否为联系人
            async def check_contact():
                try:
                    client = await self.async_handler.ensure_client_connected(phone)
                    if client:
                        # 使用正确的方法获取联系人
                        from telethon.tl.functions.contacts import GetContactsRequest
                        from telethon.tl.types import InputPeerEmpty
                        
                        result = await client(GetContactsRequest(hash=0))
                        contacts = result.users
                        
                        is_contact = any(contact.id == sender_id for contact in contacts)
                        
                        if is_contact:
                            self.log(f"👥 {phone} 跳过联系人消息 - {sender_name}")
                            return True
                        else:
                            self.log(f"👤 {phone} 确认为非联系人消息 - {sender_name}")
                            return False
                except Exception as e:
                    self.log(f"⚠️ {phone} 检查联系人失败: {str(e)}")
                    return False  # 出错时当作非联系人处理
            
            # 由于这是同步方法，我们需要异步执行检查
            import asyncio
            try:
                future = asyncio.run_coroutine_threadsafe(check_contact(), self.event_loop_thread.loop)
                is_contact = future.result(timeout=5)  # 5秒超时
                if is_contact:
                    return  # 如果是联系人，直接返回不处理
            except Exception as e:
                self.log(f"⚠️ {phone} 联系人检查超时或失败: {str(e)}")
                # 继续处理
        
        # 格式化显示消息
        display_text = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 账号: {message_data['phone']}   ⏰ {message_data['timestamp']}   
👤 发送者: {message_data['sender_name']}   🆔 用户名: @{message_data['sender_username']}   📞 手机号: {message_data['sender_phone']}
💬 消息: {message_data['message']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
        
        # 添加到显示区域
        self.stranger_message_display.append(display_text)
        
        # 滚动到底部
        scrollbar = self.stranger_message_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # 记录到日志
        self.log(f"收到非联系人消息 - {message_data['phone']}: {message_data['sender_name']} - {message_data['message'][:50]}...")
        # 记录消息到历史
        self.stranger_messages_history.append(message_data)
        # 只保留最近500条消息
        if len(self.stranger_messages_history) > 500:
            self.stranger_messages_history.pop(0)

    def clear_stranger_messages(self):
        """清空陌生人消息显示"""
        self.stranger_message_display.clear()
        self.log("陌生人消息显示已清空")
    
    def add_account_dialog(self):
        """添加账号对话框 - 修复API分配"""
        self.log("开始添加账号...")
        
        # 获取API配置
        api_configs = self.config_manager.load_api_configs()
        self.log(f"加载到 {len(api_configs)} 个API配置")
        
        if not api_configs:
            self.log("错误: 没有找到API配置")
            QMessageBox.warning(self, "错误", "请先在 resources/API配置.txt 中配置API")
            return
        
        # 输入手机号
        phone, ok = QInputDialog.getText(self, "添加账号", "请输入手机号（不含+号）:")
        if not ok or not phone:
            return
        
        phone = phone.replace('+', '').strip()
        if phone in self.accounts:
            QMessageBox.warning(self, "错误", "该账号已存在")
            return
        
        # 修复API分配逻辑
        used_api_ids = set()
        valid_statuses = ['在线', '离线', '未检测', '未登录']
        
        # 获取已使用的API ID - 包括所有有效状态的账号
        for acc in self.accounts.values():
            status = acc.get('status', '')
            if status in valid_statuses or status not in ['已停用', '已封禁', '号码被禁', '授权失效', '未授权', '会话撤销']:
                api_id = acc.get('api_id')
                if api_id:
                    used_api_ids.add(str(api_id))  # 确保转换为字符串
        
        self.log(f"已使用的API ID: {used_api_ids}")
        
        # 查找未使用的API配置
        selected_config = None
        for config in api_configs:
            config_id = str(config['api_id'])  # 确保转换为字符串
            if config_id not in used_api_ids:
                selected_config = config
                self.log(f"为账号 {phone} 分配可用的API ID: {config_id}")
                break
        
        if not selected_config:
            # 显示详细的分配情况
            self.log(f"API分配失败详情:")
            self.log(f"总API配置数: {len(api_configs)}")
            self.log(f"已使用API数: {len(used_api_ids)}")
            for i, config in enumerate(api_configs):
                config_id = str(config['api_id'])
                status = "已使用" if config_id in used_api_ids else "可用"
                self.log(f"API {i+1}: {config_id} - {status}")
            
            QMessageBox.warning(self, "API配置不足", 
                            f"没有可用的API配置\n"
                            f"总配置数: {len(api_configs)}\n"
                            f"已使用: {len(used_api_ids)}")
            return
        
        self.log(f"成功为账号 {phone} 分配API ID: {selected_config['api_id']}")
        
        # 获取保存的密码
        saved_passwords = self.config_manager.get_all_saved_passwords()
        
        # 显示登录对话框
        login_dialog = LoginDialog(self, phone, [selected_config], saved_passwords)
        login_dialog.exec()
    
    def add_account_success(self, phone, api_id, api_hash):
        """账号添加成功"""
        self.accounts[phone] = {
            'api_id': api_id,
            'api_hash': api_hash,
            'first_name': '',
            'last_name': '',
            'status': '在线'
        }
        
        # 保存到配置
        self.config_manager.add_account(phone, self.accounts[phone])
        self.config_manager.save_config()
        
        # 更新表格
        self.update_account_table()
        
        self.log(f"账号添加成功: +{phone}")
    
    def update_profiles(self):
        """更新账号资料 - 使用全局选择"""
        selected_accounts = self.get_selected_accounts_from_table()
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择要更新资料的账号")
            return
        
        selected_profiles = {}
        for key, checkbox in self.profile_checkboxes.items():
            if checkbox.isChecked():
                selected_profiles[key] = True
        
        if not selected_profiles:
            QMessageBox.warning(self, "警告", "请选择要更新的资料项")
            return
        
        self.log(f"开始更新 {len(selected_accounts)} 个账号的资料")
        
        # 为每个账号分配不同的资料数据
        profile_data_list = self.prepare_profile_data(selected_accounts, selected_profiles)
        
        # 在事件循环中执行任务
        async def update_all():
            for i, (phone, profile_data) in enumerate(zip(selected_accounts, profile_data_list)):
                try:
                    # 添加到运行任务
                    self.add_running_task(phone, 'update_profile', '更新资料')
                    
                    success = await self.async_handler.update_profile(phone, profile_data)
                    if success:
                        self.log(f"{phone} 资料更新成功")
                    
                    # 移除运行任务
                    self.remove_running_task(phone, 'update_profile')
                    
                except Exception as e:
                    self.log(f"更新资料错误 {phone}: {str(e)}")
                    self.remove_running_task(phone, 'update_profile')
            
            self.log("资料更新完成")
        
        asyncio.run_coroutine_threadsafe(update_all(), self.event_loop_thread.loop)
    
    def remove_failed_account(self, phone, reason):
        """移除失败的账号并移动session到error文件夹"""
        try:
            # 从accounts中移除
            if phone in self.accounts:
                del self.accounts[phone]
        
            # 从配置中移除
            self.config_manager.remove_account(phone)
        
            # 移动session文件到error文件夹
            session_file = Path(f'sessions/{phone}.session')
            if session_file.exists():
                error_dir = Path('sessions/error')
                error_dir.mkdir(exist_ok=True)
                error_file = error_dir / f'{phone}_{reason}.session'
            
                # 剪切文件（移动）
                shutil.move(str(session_file), str(error_file))
                self.log(f"账号 {phone} 因 {reason} 已移动到error文件夹")
        
            # 清理临时客户端
            if self.async_handler and phone in self.async_handler.temp_clients:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.async_handler.temp_clients[phone].disconnect(),
                        self.event_loop_thread.loop
                    )
                except:
                    pass
                del self.async_handler.temp_clients[phone]
        
            # 更新界面
            self.update_account_table()
        
        except Exception as e:
            self.log(f"移除失败账号 {phone} 时出错: {str(e)}")

    def prepare_profile_data(self, accounts, selected_profiles):
        """为每个账号准备不同的资料数据"""
        profile_data_list = []
        
        # 加载所有资源
        resources = {}
        if 'first_name' in selected_profiles:
            resources['first_name'] = self.load_resource_file('名字.txt')
        if 'last_name' in selected_profiles:
            resources['last_name'] = self.load_resource_file('姓氏.txt')
        if 'bio' in selected_profiles:
            resources['bio'] = self.load_resource_file('简介.txt')
        if 'username' in selected_profiles:
            resources['username'] = self.load_resource_file('用户名.txt')
        if 'avatar' in selected_profiles:
            avatar_dir = Path('resources/头像')
            if avatar_dir.exists():
                resources['avatar'] = list(avatar_dir.glob('*.*'))
            else:
                resources['avatar'] = []
        
        # 为每个账号分配数据
        for i, phone in enumerate(accounts):
            profile_data = {}
            
            for key in selected_profiles:
                if key == 'avatar':
                    if resources.get('avatar'):
                        avatar_list = resources['avatar']
                        selected_avatar = avatar_list[i % len(avatar_list)]
                        profile_data['avatar'] = str(selected_avatar)
                else:
                    resource_list = resources.get(key, [])
                    if resource_list:
                        selected_resource = resource_list[i % len(resource_list)]
                        profile_data[key] = selected_resource
            
            profile_data_list.append(profile_data)
        
        return profile_data_list
    
    def join_groups(self):
        """开始加群 - 使用全局选择"""
        selected_accounts = self.get_selected_accounts_from_table()
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择要加群的账号")
            return
    
        # 加载群组
        groups = self.load_resource_file('群组.txt')
        if not groups:
            QMessageBox.warning(self, "警告", "群组列表为空")
            return
    
        interval = self.join_interval_spin.value()
    
        # 更新进度显示
        total_tasks = len(selected_accounts) * len(groups)
        self.join_progress_bar.setMaximum(total_tasks)
        self.join_progress_bar.setValue(0)
        self.join_progress_label.setText(f"准备加入 {len(groups)} 个群组...")
    
        self.log(f"开始加群任务，间隔: {interval}秒，共 {total_tasks} 个任务")
    
        # 打乱账号和群组的组合，确保分布均匀
        import itertools
        account_group_pairs = list(itertools.product(selected_accounts, groups))
        random.shuffle(account_group_pairs)
    
        # 在事件循环中执行任务
        async def do_join(selected_accounts_param, account_group_pairs_param, total_tasks_param, interval_param, main_window_ref):
            # 在开始时为所有选中账号添加任务
            for phone in selected_accounts_param:
                main_window_ref.add_running_task(phone, 'join_group', '加群任务')
        
            completed = 0
            stopped_accounts = set()  # 记录已停止的账号
        
            for phone, group in account_group_pairs_param:
                # 如果账号已停止，跳过
                if phone in stopped_accounts:
                    completed += 1
                    continue
                
                try:
                    success = await main_window_ref.async_handler.join_group(phone, group)
                    completed += 1
                
                    # 更新进度
                    QMetaObject.invokeMethod(
                        main_window_ref, "update_join_progress",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(int, completed),
                        Q_ARG(int, total_tasks_param)
                    )
                
                    # 检查停止标志
                    if hasattr(main_window_ref.async_handler, 'stop_flags') and \
                       phone in main_window_ref.async_handler.stop_flags and \
                       main_window_ref.async_handler.stop_flags[phone].get('join_group', False):
                        stopped_accounts.add(phone)
                        main_window_ref.remove_running_task(phone, 'join_group')  # 只移除停止的账号
                        continue
                
                    if not main_window_ref.async_handler.stop_flags.get(phone, {}).get('join_group', False):
                        await asyncio.sleep(interval_param)
                    
                except Exception as e:
                    main_window_ref.log(f"加群错误 {phone}: {str(e)}")
                    completed += 1
                
                    # 检查是否是账号状态异常，如果是则停止该账号的任务
                    if main_window_ref.async_handler and phone in main_window_ref.async_handler.clients:
                        account = main_window_ref.accounts.get(phone, {})
                        status = account.get('status', '')
                        if status in ['已停用', '已封禁', '号码被禁', '授权失效', '未授权', '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', '账号受限', '操作过于频繁']:
                            stopped_accounts.add(phone)
                            main_window_ref.remove_running_task(phone, 'join_group')
                            main_window_ref.log(f"{phone} 因账号状态异常停止加群任务")
                            continue
        
            # 任务完成后移除所有剩余的运行任务
            for phone in selected_accounts_param:
                if phone not in stopped_accounts:
                    main_window_ref.remove_running_task(phone, 'join_group')
        
            # 任务完成
            QMetaObject.invokeMethod(
                main_window_ref, "on_join_finished",
                Qt.ConnectionType.QueuedConnection
            )
    
        asyncio.run_coroutine_threadsafe(
            do_join(selected_accounts, account_group_pairs, total_tasks, interval, self), 
            self.event_loop_thread.loop
        )        
    
    @pyqtSlot(int, int)
    def update_join_progress(self, completed, total):
        """更新加群进度"""
        self.join_progress_bar.setValue(completed)
        self.join_progress_label.setText(f"已完成 {completed}/{total} 个加群任务")
    
    @pyqtSlot()
    def on_join_finished(self):
        """加群任务完成"""
        self.join_progress_label.setText("加群任务完成")
        self.log("加群任务完成")
    
    def start_create_channels(self):
        """开始创建频道"""
        selected_accounts = self.get_selected_from_list(self.channel_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择要创建频道的账号")
            return
        
        count = self.channel_count_spin.value()
        interval = self.channel_interval_spin.value()
        
        # 管理员设置
        add_admins = self.add_admins_checkbox.isChecked()
        add_bots = self.add_bots_checkbox.isChecked()
        admins = [admin.strip() for admin in self.channel_admin_input.text().split(',') if admin.strip()] if add_admins else []
        bots = [bot.strip() for bot in self.channel_bot_input.text().split(',') if bot.strip()] if add_bots else []
        
        self.log(f"开始创建频道任务，每个账号创建 {count} 个频道")
        
        # 准备频道数据
        channel_data_list = self.prepare_channel_data(selected_accounts, count)
        
        # 在事件循环中执行任务
        async def do_create():
            for account in selected_accounts:
                try:
                    # 添加到运行任务
                    self.add_running_task(account, 'create_channel', '创建频道')
                    
                    await self.async_handler.create_channels(
                        account, count, interval, channel_data_list, admins, bots, add_admins, add_bots
                    )
                    
                except Exception as e:
                    self.log(f"创建频道错误 {account}: {str(e)}")
                finally:
                    # 移除运行任务
                    self.remove_running_task(account, 'create_channel')
            
            self.log("创建频道任务完成")
        
        asyncio.run_coroutine_threadsafe(do_create(), self.event_loop_thread.loop)
    
    def prepare_channel_data(self, accounts, count_per_account):
        """准备频道数据"""
        # 加载频道资源
        names = self.load_resource_file('频道名称.txt')
        descriptions = self.load_resource_file('频道简介.txt')
        usernames = self.load_resource_file('频道公开链接.txt')
        
        # 计算总需求
        total_needed = len(accounts) * count_per_account
        
        # 扩展资源以满足需求
        def extend_list(source_list, needed_count):
            if not source_list:
                return [''] * needed_count
            
            result = []
            while len(result) < needed_count:
                result.extend(source_list)
            return result[:needed_count]
        
        extended_names = extend_list(names, total_needed)
        extended_descriptions = extend_list(descriptions, total_needed)
        extended_usernames = extend_list(usernames, total_needed)
        
        # 打乱顺序确保不重复
        random.shuffle(extended_names)
        random.shuffle(extended_descriptions)
        random.shuffle(extended_usernames)
        
        # 分配给每个账号
        channel_data = []
        index = 0
        for account in accounts:
            account_data = []
            for i in range(count_per_account):
                account_data.append({
                    'name': extended_names[index],
                    'description': extended_descriptions[index],
                    'username': extended_usernames[index]
                })
                index += 1
            channel_data.append(account_data)
        
        return channel_data
    
    def add_contacts(self):
        """添加联系人"""
        selected_accounts = self.get_selected_from_list(self.contact_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        contacts = self.load_resource_file('联系人.txt')
        if not contacts:
            QMessageBox.warning(self, "警告", "联系人列表为空")
            return
        
        self.log(f"开始为 {len(selected_accounts)} 个账号添加 {len(contacts)} 个联系人")
        
        # 在事件循环中执行任务
        async def do_add_contacts():
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'add_contact', '添加联系人')
                    
                    for contact in contacts:
                        success = await self.async_handler.add_contact(phone, contact)
                        if success:
                            self.log(f"{phone} 添加联系人成功: {contact}")
                        
                        await asyncio.sleep(2)  # 添加联系人间隔
                        
                except Exception as e:
                    self.log(f"添加联系人错误 {phone}: {str(e)}")
                finally:
                    self.remove_running_task(phone, 'add_contact')
            
            self.log("添加联系人任务完成")
        
        asyncio.run_coroutine_threadsafe(do_add_contacts(), self.event_loop_thread.loop)
    
    def send_contact_messages(self):
        """发送联系人消息"""
        selected_accounts = self.get_selected_from_list(self.contact_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        messages = self.load_resource_file('联系人消息.txt')
        if not messages:
            QMessageBox.warning(self, "警告", "消息列表为空")
            return
        
        interval = self.contact_msg_interval_spin.value()
        round_interval = self.contact_msg_round_spin.value()
        
        self.log(f"开始发送联系人消息，间隔: {interval}秒")
        
        # 在事件循环中执行任务
        async def do_send_messages():
            tasks = []
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'contact_message', '联系人消息')
                    
                    # 启动任务但不等待完成
                    task = asyncio.create_task(self.async_handler.run_contact_message_task(
                        phone, interval, round_interval, messages
                    ))
                    tasks.append(task)
                    
                except Exception as e:
                    self.log(f"联系人消息错误 {phone}: {str(e)}")
                    self.remove_running_task(phone, 'contact_message')
        
        asyncio.run_coroutine_threadsafe(do_send_messages(), self.event_loop_thread.loop)
    
    def start_broadcast(self):
        """开始群发"""
        selected_accounts = self.get_selected_from_list(self.broadcast_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        interval = self.broadcast_interval_spin.value()
        round_interval = self.broadcast_round_spin.value()
        
        self.log(f"开始群发任务，间隔: {interval}秒")
        
        # 在事件循环中执行任务
        async def do_broadcast():
            tasks = []
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'broadcast', '群发消息')
                    
                    # 启动任务但不等待完成
                    task = asyncio.create_task(self.async_handler.run_broadcast_task(
                        phone, interval, round_interval
                    ))
                    tasks.append(task)
                    
                except Exception as e:
                    self.log(f"群发错误 {phone}: {str(e)}")
                    self.remove_running_task(phone, 'broadcast')
        
        asyncio.run_coroutine_threadsafe(do_broadcast(), self.event_loop_thread.loop)
    
    def reload_group_records(self):
        """重新加载群组记录"""
        if not self.async_handler:
            QMessageBox.warning(self, "警告", "异步处理器未初始化")
            return
        
        self.log("重新加载群组记录...")
        
        try:
            # 重新加载群组记录
            self.async_handler.load_group_records()
            
            # 显示加载的群组统计
            total_accounts = len(self.async_handler.account_groups)
            total_groups = sum(len(groups) for groups in self.async_handler.account_groups.values())
            
            self.log(f"群组记录加载完成：{total_accounts} 个账号，共 {total_groups} 个群组记录")
            
            # 清空表格，提示用户点击检测按钮
            self.group_table.setRowCount(0)
            
            QMessageBox.information(
                self, "成功", 
                f"群组记录已重新加载\n"
                f"账号数: {total_accounts}\n"
                f"群组记录数: {total_groups}\n\n"
                f"请点击'检测禁言状态'或'检测已加入的群'查看详情"
            )
            
        except Exception as e:
            self.log(f"重新加载群组记录失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"重新加载群组记录失败:\n{str(e)}")
    
    def check_joined_groups(self):
        """检测已加入的群"""
        selected_accounts = self.get_selected_from_list(self.group_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        self.log("开始检测已加入的群")
        self.group_table.setRowCount(0)
        
        # 在事件循环中执行任务
        async def do_check_groups():
            all_groups = []
            for phone in selected_accounts:
                try:
                    # 首先确保加载了群组记录
                    self.async_handler.load_group_records()
                    
                    # 获取当前所有群组
                    current_groups = await self.async_handler.get_groups_only(phone)
                    
                    # 获取记录的群组状态
                    recorded_groups = await self.async_handler.get_recorded_groups_status(phone)
                    
                    # 合并当前群组和记录的群组
                    all_account_groups = []
                    
                    # 添加当前群组
                    for group in current_groups:
                        group['phone'] = phone
                        group['source'] = 'current'
                        all_account_groups.append(group)
                    
                    # 添加记录的群组（如果不在当前群组中）
                    current_group_ids = {str(g['id']) for g in current_groups}
                    for group in recorded_groups:
                        if str(group['id']) not in current_group_ids:
                            group['phone'] = phone
                            group['source'] = 'recorded'
                            all_account_groups.append(group)
                    
                    all_groups.extend(all_account_groups)
                    self.log(f"{phone} 获取到 {len(all_account_groups)} 个群组（当前: {len(current_groups)}, 记录: {len(recorded_groups)}）")
                    
                except Exception as e:
                    self.log(f"获取群组错误 {phone}: {str(e)}")
            
            # 更新群组表格
            QMetaObject.invokeMethod(
                self, "update_group_table",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, all_groups)
            )
            self.log(f"检测完成，共获取 {len(all_groups)} 个群组")
        
        asyncio.run_coroutine_threadsafe(do_check_groups(), self.event_loop_thread.loop)
    
    def check_mute_status(self):
        """检测禁言状态"""
        selected_accounts = self.get_selected_from_list(self.group_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        self.log("开始检测群禁言状态")
        self.group_table.setRowCount(0)
        
        # 在事件循环中执行任务
        async def do_check_mute():
            all_groups = []
            for phone in selected_accounts:
                try:
                    # 首先确保加载了群组记录
                    self.async_handler.load_group_records()
                    
                    # 获取记录的群组状态
                    groups = await self.async_handler.get_recorded_groups_status(phone)
                    
                    # 如果没有记录的群组，尝试获取当前所有群组
                    if not groups:
                        self.log(f"{phone} 没有记录的群组，尝试获取当前群组...")
                        current_groups = await self.async_handler.get_groups_only(phone)
                        groups = current_groups
                    
                    for group in groups:
                        group['phone'] = phone
                    all_groups.extend(groups)
                    
                    self.log(f"{phone} 获取到 {len(groups)} 个群组")
                    
                except Exception as e:
                    self.log(f"获取群组错误 {phone}: {str(e)}")
            
            # 更新群组表格
            QMetaObject.invokeMethod(
                self, "update_group_table",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, all_groups)
            )
            self.log(f"检测完成，共获取 {len(all_groups)} 个群组")
        
        asyncio.run_coroutine_threadsafe(do_check_mute(), self.event_loop_thread.loop)
    
    def leave_all_groups(self):
        """退出所有群组"""
        selected_accounts = self.get_selected_from_list(self.group_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        reply = QMessageBox.question(
            self, "确认", 
            f"确定要让选中的 {len(selected_accounts)} 个账号退出所有群组吗？\n注意：这将退出所有群组（不包括频道）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.log("开始退出所有群组")
        
        # 在事件循环中执行任务
        async def do_leave_groups():
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'leave_groups', '退出群组')
                    
                    success = await self.async_handler.leave_all_groups(phone)
                    if success:
                        self.log(f"{phone} 退出所有群组完成")
                    
                    self.remove_running_task(phone, 'leave_groups')
                    
                except Exception as e:
                    self.log(f"退出群组错误 {phone}: {str(e)}")
                    self.remove_running_task(phone, 'leave_groups')
            
            self.log("退出群组任务完成")
        
        asyncio.run_coroutine_threadsafe(do_leave_groups(), self.event_loop_thread.loop)
    
    @pyqtSlot(list)
    def update_group_table(self, groups):
        """更新群组表格"""
        self.group_table.setRowCount(len(groups))
        
        for i, group in enumerate(groups):
            # 账号
            self.group_table.setItem(i, 0, QTableWidgetItem(group.get('phone', '')))
            
            # 群名称
            title = group.get('title', '')
            if group.get('source') == 'recorded':
                title += " (记录)"
            elif group.get('status') == '已退出':
                title += " (已退出)"
            self.group_table.setItem(i, 1, QTableWidgetItem(title))
            
            # 群ID
            self.group_table.setItem(i, 2, QTableWidgetItem(str(group.get('id', ''))))
            
            # 禁言状态
            status = ""
            if group.get('status') == '已退出':
                status = "已退出"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor('gray'))
            elif group.get('status') == '群组私有':
                status = "群组私有"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor('orange'))
            elif group.get('status') == '连接失败':
                status = "连接失败"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor('red'))
            elif group.get('is_muted', False):
                status = "已禁言"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor('red'))
            else:
                status = "正常"
                status_item = QTableWidgetItem(status)
                status_item.setForeground(QColor('green'))
            
            self.group_table.setItem(i, 3, status_item)
    
    def start_unmute(self):
        """开始解禁"""
        selected_accounts = self.get_selected_from_list(self.group_account_list)
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择账号")
            return
        
        interval = self.unmute_interval_spin.value()
        round_interval = self.unmute_round_spin.value()
        
        self.log(f"开始解禁任务，间隔: {interval}秒")
        
        # 在事件循环中执行任务
        async def do_unmute():
            tasks = []
            for phone in selected_accounts:
                try:
                    self.add_running_task(phone, 'unmute', '解禁任务')
                    
                    # 启动任务但不等待完成
                    task = asyncio.create_task(self.async_handler.run_unmute_task(
                        phone, interval, round_interval
                    ))
                    tasks.append(task)
                    
                except Exception as e:
                    self.log(f"解禁错误 {phone}: {str(e)}")
                    self.remove_running_task(phone, 'unmute')
        
        asyncio.run_coroutine_threadsafe(do_unmute(), self.event_loop_thread.loop)
    
    def check_accounts_status(self):
        """检测选中账号的状态"""
        # 获取选中的账号
        selected_accounts = []
        for row in range(self.account_table.rowCount()):
            checkbox = self.account_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                phone = self.account_table.item(row, 1).text()
                selected_accounts.append(phone)
        
        if not selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择要检测的账号")
            return
        
        self.log(f"开始检测 {len(selected_accounts)} 个选中账号的状态")
        self.show_progress(0, len(selected_accounts))
        
        # 在事件循环中执行任务
        async def do_check_status():
            try:
                checked = 0
                for phone in selected_accounts:
                    try:
                        self.log(f"正在检测账号: {phone}")
                        status = await self.async_handler.check_account_status(phone)
                        
                        if status:
                            self.log(f"{phone} 状态正常")
                        else:
                            self.log(f"{phone} 状态异常")
                        
                        # 只更新这个账号的行
                        QMetaObject.invokeMethod(
                            self, "update_single_account_row",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, phone)
                        )
                        
                        checked += 1
                        QMetaObject.invokeMethod(
                            self, "show_progress",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(int, checked),
                            Q_ARG(int, len(selected_accounts))
                        )
                        
                    except Exception as e:
                        self.log(f"检测账号 {phone} 错误: {str(e)}")
                        checked += 1
                        QMetaObject.invokeMethod(
                            self, "show_progress",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(int, checked),
                            Q_ARG(int, len(selected_accounts))
                        )
                
                # 隐藏进度条
                QMetaObject.invokeMethod(
                    self, "hide_progress",
                    Qt.ConnectionType.QueuedConnection
                )
                
                self.log(f"选中账号状态检测完成，共检测 {len(selected_accounts)} 个账号")
                
            except Exception as e:
                self.log(f"检测账号状态时发生错误: {str(e)}")
                QMetaObject.invokeMethod(
                    self, "hide_progress",
                    Qt.ConnectionType.QueuedConnection
                )
        
        asyncio.run_coroutine_threadsafe(do_check_status(), self.event_loop_thread.loop)
    
    def load_sessions(self):
        """加载sessions文件"""
        self.log("开始加载sessions文件")
        sessions_dir = Path('sessions')
        
        if not sessions_dir.exists():
            self.log("sessions文件夹不存在")
            return
            
        session_files = list(sessions_dir.glob('*.session'))
        
        if not session_files:
            self.log("未找到任何session文件")
            return
        
        loaded_count = 0
        for session_file in session_files:
            phone = session_file.stem
            
            if session_file.parent.name in ['ok', 'error']:
                continue
                
            if phone not in self.accounts:
                api_config = self.config_manager.get_next_api_config()
                if api_config:
                    self.accounts[phone] = {
                        'api_id': api_config['api_id'],
                        'api_hash': api_config['api_hash'],
                        'first_name': '',
                        'last_name': '',
                        'status': '未检测'
                    }
                    self.config_manager.add_account(phone, self.accounts[phone])
                    loaded_count += 1
                    self.log(f"加载session: {phone}")
        
        self.update_account_table()
        self.log(f"加载了 {loaded_count} 个session文件")
    
    def load_resource_file(self, filename):
        """加载资源文件 - 支持多种编码"""
        file_path = Path(f'resources/{filename}')
        if not file_path.exists():
            self.log(f"⚠️ 文件不存在: {filename}")
            return []
    
        # 尝试多种编码
        encodings = ['utf-8', 'gbk', 'gb2312', 'utf-8-sig', 'latin1']
    
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    lines = [line.strip() for line in f.readlines() if line.strip() and not line.strip().startswith('#')]
                    self.log(f"✅ 使用 {encoding} 编码成功读取 {filename}，共 {len(lines)} 行")
                    return lines
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception as e:
                self.log(f"❌ 读取文件 {filename} 时出错 ({encoding}): {str(e)}")
                continue
    
        self.log(f"❌ 无法使用任何编码读取文件: {filename}")
        return []
    
    @pyqtSlot()
    def update_account_table(self):
        """更新账号表格"""
        self.log(f"开始更新账号表格，当前账号数: {len(self.accounts)}")
        
        # 打印所有账号信息用于调试
        for phone, info in self.accounts.items():
            self.log(f"账号 {phone}: 名字={info.get('first_name', '')}, 姓氏={info.get('last_name', '')}, 用户名={info.get('username', '')}, 状态={info.get('status', '')}")
        
        # 保存当前选中状态
        current_selected = []
        for row in range(self.account_table.rowCount()):
            checkbox = self.account_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                phone = self.account_table.item(row, 1).text()
                current_selected.append(phone)
        
        # 清空并重新填充表格
        self.account_table.setRowCount(len(self.accounts))
        
        for row, (phone, info) in enumerate(self.accounts.items()):
            # 复选框 - 默认选中
            checkbox = QCheckBox()
            checkbox.setChecked(True)  # 👈 默认选中
            checkbox.stateChanged.connect(lambda state, p=phone: self.on_account_selected(p, state))
            
            self.account_table.setCellWidget(row, 0, checkbox)
            
            # 恢复选中状态
            if phone in current_selected:
                checkbox.setChecked(True)
            
            self.account_table.setCellWidget(row, 0, checkbox)
            
            # 账号信息
            self.account_table.setItem(row, 1, QTableWidgetItem(phone))
            
            # 名字
            first_name = info.get('first_name', '')
            self.account_table.setItem(row, 2, QTableWidgetItem(first_name))
            
            # 姓氏
            last_name = info.get('last_name', '')
            self.account_table.setItem(row, 3, QTableWidgetItem(last_name))
            
            # 用户名 - 新增列
            username = info.get('username', '')
            username_display = f"@{username}" if username else ""
            username_item = QTableWidgetItem(username_display)
            if username:
                username_item.setToolTip(f"用户名: @{username}")
            self.account_table.setItem(row, 4, username_item)
            
            # API ID
            api_id = info.get('api_id', '')
            self.account_table.setItem(row, 5, QTableWidgetItem(str(api_id)))
            
            # 状态 - 列索引改为6
            status = info.get('status', '未知')
            status_item = QTableWidgetItem(status)
            
            # 根据状态设置颜色
            if status == '在线':
                status_item.setForeground(QColor('green'))
            elif status == '离线':
                status_item.setForeground(QColor('orange'))
            elif status in ['已停用', '已封禁', '号码被禁', '授权失效', '未授权', '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', '账号受限', '操作过于频繁']:
                status_item.setForeground(QColor('red'))
                status_item.setToolTip(f"账号状态异常: {status}")
            elif 'SpamBot检测' in status:
                status_item.setForeground(QColor('red'))
                status_item.setToolTip(f"SpamBot检测结果: {status}")
            elif '限流' in status:
                status_item.setForeground(QColor('orange'))
                status_item.setToolTip(f"账号被限流: {status}")
            else:
                status_item.setForeground(QColor('gray'))
            
            self.account_table.setItem(row, 6, status_item)
        
        # 强制刷新表格显示
        self.account_table.viewport().update()
        
        # 更新任务面板的账号列表
       # self.update_account_lists()
       # 自动全选后更新选中状态
        self.update_selected_accounts()
        self.update_account_lists()  # 👈 添加这行
        self.log(f"账号表格更新完成，共 {len(self.accounts)} 个账号，已自动全选")
    
    @pyqtSlot(str)
    def update_single_account_row(self, phone):
        """更新单个账号的表格行"""
        if phone not in self.accounts:
            return
        
        # 查找对应的表格行
        for row in range(self.account_table.rowCount()):
            if self.account_table.item(row, 1).text() == phone:
                account = self.accounts[phone]
                
                # 更新名字
                first_name = account.get('first_name', '')
                self.account_table.setItem(row, 2, QTableWidgetItem(first_name))
                
                # 更新姓氏
                last_name = account.get('last_name', '')
                self.account_table.setItem(row, 3, QTableWidgetItem(last_name))
                
                # 更新用户名
                username = account.get('username', '')
                username_display = f"@{username}" if username else ""
                username_item = QTableWidgetItem(username_display)
                if username:
                    username_item.setToolTip(f"用户名: @{username}")
                self.account_table.setItem(row, 4, username_item)
                
                # 更新状态
                status = account.get('status', '未知')
                status_item = QTableWidgetItem(status)
                
                # 根据状态设置颜色
                if status == '在线':
                    status_item.setForeground(QColor('green'))
                elif status == '离线':
                    status_item.setForeground(QColor('orange'))
                elif status in ['已停用', '已封禁', '号码被禁', '授权失效', '未授权', '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', '账号受限', '操作过于频繁']:
                    status_item.setForeground(QColor('red'))
                    status_item.setToolTip(f"账号状态异常: {status}")
                elif 'SpamBot检测' in status:
                    status_item.setForeground(QColor('red'))
                    status_item.setToolTip(f"SpamBot检测结果: {status}")
                elif '限流' in status:
                    status_item.setForeground(QColor('orange'))
                    status_item.setToolTip(f"账号被限流: {status}")
                else:
                    status_item.setForeground(QColor('gray'))
                
                self.account_table.setItem(row, 6, status_item)
                
                # 强制刷新这一行
                self.account_table.viewport().update()
                
                self.log(f"{phone} 表格行已更新 - 名字: {first_name}, 姓氏: {last_name}, 用户名: {username_display}")
                break
        
        # 更新任务面板的账号列表（只更新显示名称）
        self.update_account_lists()

    def on_account_selected(self, phone, state):
        """账号选择状态改变"""
        # 实时更新选中列表
        self.selected_accounts = self.get_selected_accounts_from_table()
        
        # 自动同步到所有任务列表
        self.update_account_lists()
    
    def select_all_accounts(self):
        """全选账号"""
        for row in range(self.account_table.rowCount()):
            checkbox = self.account_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(True)
    
    
    def deselect_all_accounts(self):
        """取消全选"""
        for row in range(self.account_table.rowCount()):
            checkbox = self.account_table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(False)
    
    def update_selected_accounts(self):
        """更新选中账号列表（用于兼容现有代码）"""
        self.selected_accounts = self.get_selected_accounts_from_table()
        self.log(f"当前选中账号数: {len(self.selected_accounts)}")

    def get_selected_accounts_from_table(self):
        """从全局账号表格获取选中的账号"""
        selected_accounts = []
        for row in range(self.account_table.rowCount()):
            checkbox = self.account_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                phone = self.account_table.item(row, 1).text()
                selected_accounts.append(phone)
        return selected_accounts

    def delete_selected_accounts(self):
        """删除选中的账号"""
        if not self.selected_accounts:
            QMessageBox.warning(self, "警告", "请先选择要删除的账号")
            return
        
        reply = QMessageBox.question(self, "确认", f"确定要删除 {len(self.selected_accounts)} 个账号吗？")
        if reply == QMessageBox.StandardButton.Yes:
            for phone in self.selected_accounts[:]:
                if phone in self.accounts:
                    del self.accounts[phone]
                    self.config_manager.remove_account(phone)
                    self.log(f"删除账号: {phone}")
            
            self.selected_accounts.clear()
            self.update_account_table()
            self.config_manager.save_config()

    def clean_error_accounts(self):
        """清理异常状态的账号"""
        error_statuses = [
            '已停用', '已封禁', '号码被禁', '授权失效', '未授权', 
            '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', 
            '账号受限', '操作过于频繁', 'API无效', '号码无效',
            '连接异常', '登录失败'
        ]
    
        error_accounts = []
        for phone, account in self.accounts.items():
            if account.get('status', '') in error_statuses:
                error_accounts.append(phone)
    
        if not error_accounts:
            QMessageBox.information(self, "信息", "没有发现异常账号")
            return
    
        reply = QMessageBox.question(
            self, "确认", 
            f"发现 {len(error_accounts)} 个异常账号，是否移动到error文件夹？\n\n"
            f"异常账号：{', '.join(error_accounts[:5])}"
            f"{'...' if len(error_accounts) > 5 else ''}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
    
        if reply == QMessageBox.StandardButton.Yes:
            for phone in error_accounts:
                account = self.accounts[phone]
                status = account.get('status', '异常')
                self.remove_failed_account(phone, status)
        
            QMessageBox.information(self, "完成", f"已处理 {len(error_accounts)} 个异常账号")

    
    def remove_failed_account(self, phone, reason):
        """移除失败的账号并移动session到error文件夹"""
        try:
            # 从accounts中移除
            if phone in self.accounts:
                del self.accounts[phone]
        
            # 从选中列表中移除
            if phone in self.selected_accounts:
                self.selected_accounts.remove(phone)
        
            # 从配置中移除
            self.config_manager.remove_account(phone)
        
            # 移动session文件到error文件夹
            session_file = Path(f'sessions/{phone}.session')
            if session_file.exists():
                error_dir = Path('sessions/error')
                error_dir.mkdir(exist_ok=True)
                error_file = error_dir / f'{phone}_{reason}.session'
            
                # 剪切文件（移动）
                shutil.move(str(session_file), str(error_file))
                self.log(f"账号 {phone} 因 {reason} 已移动到error文件夹")
        
            # 清理临时客户端
            if self.async_handler and phone in self.async_handler.temp_clients:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.async_handler.temp_clients[phone].disconnect(),
                        self.event_loop_thread.loop
                    )
                except:
                    pass
                del self.async_handler.temp_clients[phone]
        
            # 清理正式客户端
            if self.async_handler and phone in self.async_handler.clients:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.async_handler.clients[phone].disconnect(),
                        self.event_loop_thread.loop
                    )
                except:
                    pass
                del self.async_handler.clients[phone]
        
            # 更新界面
            self.update_account_table()
        
        except Exception as e:
            self.log(f"移除失败账号 {phone} 时出错: {str(e)}")

    def init_async_handler(self):
        """初始化异步处理器"""
        try:
            from telegram_async_handler import TelegramAsyncHandler
            self.async_handler = TelegramAsyncHandler(self)
            
            # 在主线程中连接信号 - 确保连接正确
            self.async_handler.signals.update_account_status.connect(
                self.on_account_updated, Qt.ConnectionType.QueuedConnection
            )
            self.async_handler.signals.profile_updated.connect(
                self.on_profile_updated, Qt.ConnectionType.QueuedConnection
            )
            self.async_handler.signals.stranger_message.connect(
                self.on_stranger_message_received, Qt.ConnectionType.QueuedConnection
            )
            
            self.log("信号连接完成")
            
            # 在事件循环中初始化
            async def init_handler():
                await self.async_handler.initialize()
                
            future = asyncio.run_coroutine_threadsafe(init_handler(), self.event_loop_thread.loop)
            future.result()
            self.log("异步处理器初始化成功")
            
        except Exception as e:
            self.log(f"异步处理器初始化失败: {str(e)}")
            import traceback
            self.log(f"详细错误: {traceback.format_exc()}")
    
    def on_account_updated(self, phone, info):
        """账号信息更新"""
        self.log(f"收到账号更新信号: {phone}, 信息: {info}")
        
        # 确保phone格式一致
        clean_phone = phone.replace('+', '').strip()
        
        if clean_phone in self.accounts:
            # 更新现有账号
            old_info = self.accounts[clean_phone].copy()
            self.accounts[clean_phone].update(info)
            
            # 记录更新的内容
            updated_fields = []
            for key, new_value in info.items():
                old_value = old_info.get(key, '')
                if old_value != new_value:
                    updated_fields.append(f"{key}: '{old_value}' -> '{new_value}'")
            
            if updated_fields:
                self.log(f"{clean_phone} 账号信息更新: {', '.join(updated_fields)}")
            
            # 检查是否为异常状态
            status = info.get('status', '')
            error_statuses = [
                '已停用', '已封禁', '号码被禁', '授权失效', '未授权', 
                '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', 
                '账号受限', '操作过于频繁', 'API无效', '号码无效'
            ]
            
            if status in error_statuses:
                self.remove_failed_account(clean_phone, status)
                return
            
        else:
            # 新账号，直接添加
            self.accounts[clean_phone] = info
            self.log(f"{clean_phone} 新账号添加: {info}")
        
        # 强制更新界面
        self.log(f"{clean_phone} 刷新界面...")
        
        # 更新配置
        self.config_manager.update_account(clean_phone, self.accounts[clean_phone])
        self.config_manager.save_config()
    
    def on_profile_updated(self, phone, info):
        """资料更新完成"""
        self.log(f"收到资料更新信号: {phone}, 资料: {info}")
        
        # 确保phone格式一致
        clean_phone = phone.replace('+', '').strip()
        
        if clean_phone in self.accounts:
            # 更新账号中的用户信息
            old_info = {}
            for key in ['first_name', 'last_name', 'username']:
                if key in info:
                    old_value = self.accounts[clean_phone].get(key, '')
                    new_value = info[key]
                    if old_value != new_value:
                        old_info[key] = old_value
                        self.accounts[clean_phone][key] = new_value
                        self.log(f"{clean_phone} 资料更新: {key} '{old_value}' -> '{new_value}'")
            
            # 只更新这个账号的表格行，不刷新整个表格
            if old_info:
                # 延时100ms更新，确保数据已保存
                QTimer.singleShot(100, lambda: self.update_single_account_row(clean_phone))
            
            # 保存到配置
            self.config_manager.update_account(clean_phone, self.accounts[clean_phone])
            self.config_manager.save_config()
            
        else:
            self.log(f"警告: 收到资料更新信号但账号不存在: {clean_phone}")
    
    def load_program_remark(self):
        """加载程序备注配置"""
        try:
            remark_file = Path('resources/program_remark.txt')
            if remark_file.exists():
                with open(remark_file, 'r', encoding='utf-8') as f:
                    self.program_remark = f.read().strip()
            else:
                self.program_remark = ""
            
            # 更新显示
            self.update_program_remark_display()
                    
        except Exception as e:
            self.log(f"加载程序备注失败: {str(e)}")
            self.program_remark = ""
            self.update_program_remark_display()

    def save_program_remark(self):
        """保存程序备注配置"""
        try:
            # 保存到文件
            remark_file = Path('resources/program_remark.txt')
            with open(remark_file, 'w', encoding='utf-8') as f:
                f.write(self.program_remark)
            
            self.log(f"程序备注已保存: {self.program_remark}")
            
        except Exception as e:
            self.log(f"保存程序备注失败: {str(e)}")

    def update_program_remark_display(self):
        """更新程序备注显示"""
        if hasattr(self, 'program_remark_label'):
            display_text = f"📝 {self.program_remark}" if self.program_remark else "📝 未命名设备"
            self.program_remark_label.setText(display_text)

    def edit_program_remark(self, event):
        """双击编辑程序备注"""
        current_remark = self.program_remark if self.program_remark else ""
        
        new_remark, ok = QInputDialog.getText(
            self, 
            "编辑程序备注", 
            "请输入程序备注（用于识别不同设备）:",
            QLineEdit.EchoMode.Normal,
            current_remark
        )
        
        if ok:
            self.program_remark = new_remark.strip()
            self.save_program_remark()
            self.update_program_remark_display()

    def get_program_remark(self):
        """获取程序备注，如果为空则返回默认值"""
        return self.program_remark if self.program_remark else "未命名设备"

    def save_config(self):
        """保存配置"""
        # 更新设置
        self.config_manager.set_setting('join_interval', self.join_interval_spin.value())
        self.config_manager.set_setting('auto_join', self.auto_join_checkbox.isChecked())
        self.config_manager.set_setting('broadcast_interval', self.broadcast_interval_spin.value())
        self.config_manager.set_setting('broadcast_round', self.broadcast_round_spin.value())
        self.config_manager.set_setting('auto_broadcast', self.auto_broadcast_checkbox.isChecked())
        self.config_manager.set_setting('unmute_interval', self.unmute_interval_spin.value())
        self.config_manager.set_setting('unmute_round', self.unmute_round_spin.value())
        self.config_manager.set_setting('auto_unmute', self.auto_unmute_checkbox.isChecked())
        self.config_manager.set_setting('contact_msg_interval', self.contact_msg_interval_spin.value())
        self.config_manager.set_setting('contact_msg_round', self.contact_msg_round_spin.value())
        self.config_manager.set_setting('channel_interval', self.channel_interval_spin.value())
        self.config_manager.set_setting('auto_contact_msg', self.auto_contact_msg_checkbox.isChecked())
        
        # 新增：陌生人消息设置
        if hasattr(self, 'auto_reply_checkbox'):
            self.config_manager.set_setting('auto_reply_enabled', self.auto_reply_checkbox.isChecked())
        if hasattr(self, 'bot_notify_checkbox'):
            self.config_manager.set_setting('bot_notify_enabled', self.bot_notify_checkbox.isChecked())
        
        # 保存账号
        for phone, account in self.accounts.items():
            self.config_manager.update_account(phone, account)
        
        # 保存设备分配
        if self.async_handler:
            self.async_handler.save_device_assignments()
        
        if self.config_manager.save_config():
            self.log("配置已保存")
        else:
            QMessageBox.critical(self, "错误", "保存配置失败")
    
    def load_config(self):
        """加载配置"""
        try:
            # 加载API配置
            self.config_manager.load_api_configs()
            
            # 加载账号
            self.accounts = self.config_manager.get_all_accounts()
            
            # 加载程序备注
            self.load_program_remark()

            # 加载设置
            self.join_interval_spin.setValue(
                self.config_manager.get_setting('join_interval', 60)
            )
            self.auto_join_checkbox.setChecked(
                self.config_manager.get_setting('auto_join', False)
            )
            self.broadcast_interval_spin.setValue(
                self.config_manager.get_setting('broadcast_interval', 180)
            )
            self.broadcast_round_spin.setValue(
                self.config_manager.get_setting('broadcast_round', 3600)
            )
            self.auto_broadcast_checkbox.setChecked(
                self.config_manager.get_setting('auto_broadcast', False)
            )
            self.unmute_interval_spin.setValue(
                self.config_manager.get_setting('unmute_interval', 60)
            )
            self.unmute_round_spin.setValue(
                self.config_manager.get_setting('unmute_round', 3600)
            )
            self.auto_unmute_checkbox.setChecked(
                self.config_manager.get_setting('auto_unmute', False)
            )
            self.contact_msg_interval_spin.setValue(
                self.config_manager.get_setting('contact_msg_interval', 60)
            )
            self.contact_msg_round_spin.setValue(
                self.config_manager.get_setting('contact_msg_round', 3600)
            )
            self.auto_contact_msg_checkbox.setChecked(
                self.config_manager.get_setting('auto_contact_msg', False)
            )
            self.channel_interval_spin.setValue(
                self.config_manager.get_setting('channel_interval', 7560)
            )
            
            # 新增：加载陌生人消息设置
            if hasattr(self, 'auto_reply_checkbox'):
                self.auto_reply_checkbox.setChecked(
                    self.config_manager.get_setting('auto_reply_enabled', False)
                )
            if hasattr(self, 'bot_notify_checkbox'):
                self.bot_notify_checkbox.setChecked(
                    self.config_manager.get_setting('bot_notify_enabled', False)
                )
            
            # 检查界面是否已经创建，如果已创建才更新界面
            if hasattr(self, 'account_table'):
                self.update_account_table()
                # 确保加载后自动全选
                QTimer.singleShot(100, self.select_all_accounts)  # 延迟100ms执行全选
            
            self.log("配置加载成功")
            
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")
    
    def log(self, message):
        """添加日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        
        # 添加到界面
        self.log_text.append(log_message)
        
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
        # 记录到文件
        logging.info(message)
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.log("日志已清空")
    
    def export_log(self):
        """导出日志"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", "Text Files (*.txt)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                self.log(f"日志已导出至: {file_path}")
                QMessageBox.information(self, "成功", "日志导出成功")
            except Exception as e:
                self.log(f"导出日志失败: {str(e)}")
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    @pyqtSlot(int, int)
    def show_progress(self, value, maximum=100):
        """显示进度"""
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(True)
    
    @pyqtSlot()
    def hide_progress(self):
        """隐藏进度条"""
        self.progress_bar.setVisible(False)
    
    def update_task_status(self, status):
        """更新任务状态"""
        self.task_status_label.setText(f"当前任务: {status}")

    def clear_privacy_status(self):
        """清空隐私状态显示"""
        self.privacy_status_text.clear()
        self.log("隐私状态显示已清空")

    # 更新 update_account_lists 方法，添加隐私设置账号列表
    def update_account_lists(self):
        """更新所有任务标签页的账号列表"""
        lists = [
            self.profile_account_list,
            self.join_account_list,
            self.stranger_account_list,
            self.contact_account_list,
            self.broadcast_account_list,
            self.group_account_list,
            self.security_account_list,
            self.channel_account_list,
            self.privacy_account_list
        ]
        
        # 获取所有选中的账号
        selected_accounts = self.get_selected_accounts_from_table()
        
        for list_widget in lists:
            list_widget.clear()
            
            # 添加所有选中的账号到列表
            for phone in selected_accounts:
                if phone in self.accounts:
                    account = self.accounts[phone]
                    name = account.get('first_name', '')
                    surname = account.get('last_name', '')
                    
                    display_text = f"{phone} - {name} {surname}".strip()
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, phone)
                    item.setSelected(True)  # 默认选中
                    list_widget.addItem(item)
            
            # 自动全选列表中的所有项目
            list_widget.selectAll()

    def show_api_login_dialog(self):
        """显示API接码登录对话框"""
        dialog = APILoginDialog(self)
        dialog.exec()
    def show_device_manager(self):
        """显示设备管理对话框"""
        if not hasattr(self, 'device_manager_dialog'):
            self.device_manager_dialog = DeviceManagerDialog(self, self.async_handler)
        
        self.device_manager_dialog.refresh_data()
        self.device_manager_dialog.show()
    def reply_to_last_message(self):
        """回复最后一条消息"""
        if not self.stranger_messages_history:
            QMessageBox.warning(self, "警告", "没有可回复的消息")
            return
        
        reply_text = self.reply_input.toPlainText().strip()
        if not reply_text:
            QMessageBox.warning(self, "警告", "请输入回复内容")
            return
        
        last_message = self.stranger_messages_history[-1]
        self.send_manual_reply(last_message, reply_text)

    def select_message_to_reply(self):
        """选择要回复的消息"""
        if not self.stranger_messages_history:
            QMessageBox.warning(self, "警告", "没有可回复的消息")
            return
        
        reply_text = self.reply_input.toPlainText().strip()
        if not reply_text:
            QMessageBox.warning(self, "警告", "请输入回复内容")
            return
        
        # 创建选择对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("选择要回复的消息")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # 消息列表
        message_list = QListWidget()
        message_list.setStyleSheet("""
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #E0E0E0;
            }
            QListWidget::item:selected {
                background-color: #E3F2FD;
            }
        """)
        
        for i, msg in enumerate(reversed(self.stranger_messages_history[-20:])):  # 显示最近20条
            item_text = f"📱 {msg['phone']} | 👤 {msg['sender_name']} | ⏰ {msg['timestamp']}\n💬 {msg['message'][:100]}..."
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, msg)
            message_list.addItem(item)
        
        layout.addWidget(message_list)
       
        # 按钮
        button_layout = QHBoxLayout()       
        reply_btn = QPushButton("回复选中消息")
        reply_btn.setStyleSheet(self.button_styles['primary'])
        reply_btn.clicked.connect(lambda: self.confirm_reply(dialog, message_list, reply_text))
        button_layout.addWidget(reply_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)        
        dialog.exec()

    def confirm_reply(self, dialog, message_list, reply_text):
        """确认回复选中的消息"""
        current_item = message_list.currentItem()
        if not current_item:
            QMessageBox.warning(dialog, "警告", "请选择要回复的消息")
            return
        
        message_data = current_item.data(Qt.ItemDataRole.UserRole)
        dialog.accept()
        self.send_manual_reply(message_data, reply_text)

    def send_manual_reply(self, message_data, reply_text):
        """发送手动回复"""
        phone = message_data['phone']
        sender_id = message_data['sender_id']
        sender_name = message_data['sender_name']
        
        self.log(f"正在用 {phone} 回复 {sender_name}: {reply_text}")
        
        # 在事件循环中发送回复
        async def do_reply():
            try:
                success = await self.async_handler.send_manual_reply_to_stranger(
                    phone, sender_id, reply_text
                )
                
                if success:
                    QMetaObject.invokeMethod(
                        self, "on_reply_sent",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone),
                        Q_ARG(str, sender_name),
                        Q_ARG(str, reply_text)
                    )
                else:
                    QMetaObject.invokeMethod(
                        self, "on_reply_failed",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, phone),
                        Q_ARG(str, sender_name)
                    )
            except Exception as e:
                QMetaObject.invokeMethod(
                    self, "on_reply_error",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, str(e))
                )
        
        asyncio.run_coroutine_threadsafe(do_reply(), self.event_loop_thread.loop)

    @pyqtSlot(str, str, str)
    def on_reply_sent(self, phone, sender_name, reply_text):
        """回复发送成功"""
        self.log(f"✅ {phone} 成功回复 {sender_name}: {reply_text}")
        self.reply_input.clear()

    @pyqtSlot(str, str)
    def on_reply_failed(self, phone, sender_name):
        """回复发送失败"""
        self.log(f"❌ {phone} 回复 {sender_name} 失败")
        QMessageBox.warning(self, "失败", f"回复 {sender_name} 失败")

    @pyqtSlot(str)
    def on_reply_error(self, error):
        """回复发送错误"""
        self.log(f"❌ 发送回复时出错: {error}")
        QMessageBox.critical(self, "错误", f"发送回复时出错: {error}")
    def eventFilter(self, obj, event):
        """事件过滤器：处理回复输入框的快捷键"""
        # 检查是否是回复输入框的按键事件
        if obj == self.reply_input and hasattr(event, 'type'):
            from PyQt6.QtGui import QKeyEvent
            if event.type() == QKeyEvent.Type.KeyPress:
                # Ctrl+Enter 发送回复到最后一条消息
                if (event.key() == Qt.Key.Key_Return and 
                    event.modifiers() == Qt.KeyboardModifier.ControlModifier):
                    self.reply_to_last_message()
                    return True
        return super().eventFilter(obj, event)
    
    # 建议在关闭时更彻底地清理资源
def closeEvent(self, event):
    """主程序关闭事件处理 - 改进版"""
    try:
        self.log("正在关闭程序，清理所有资源...")
        
        # 1. 关闭所有对话框
        if hasattr(self, 'api_login_dialog') and self.api_login_dialog:
            self.api_login_dialog.close()
        
        # 2. 停止所有定时器
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if isinstance(attr, QTimer):
                attr.stop()
        
        # 3. 停止所有异步任务
        if self.async_handler:
            async def cleanup_all():
                """清理所有异步资源"""
                try:
                    # 停止所有任务
                    await self.async_handler.stop_all_tasks()
                    
                    # 断开所有客户端
                    for phone, client in list(self.async_handler.clients.items()):
                        try:
                            if client.is_connected():
                                await client.disconnect()
                            self.log(f"{phone} 主程序清理：客户端已断开")
                        except Exception as e:
                            self.log(f"{phone} 主程序断开失败: {str(e)}")
                    
                    # 断开所有临时客户端
                    for phone, client in list(self.async_handler.temp_clients.items()):
                        try:
                            if client.is_connected():
                                await client.disconnect()
                            self.log(f"{phone} 主程序清理：临时客户端已断开")
                        except Exception as e:
                            self.log(f"{phone} 主程序临时客户端断开失败: {str(e)}")
                    
                    self.log("所有异步资源清理完成")
                    
                except Exception as e:
                    self.log(f"清理异步资源时出错: {str(e)}")
            
            # 执行清理并等待完成
            try:
                future = asyncio.run_coroutine_threadsafe(
                    cleanup_all(), 
                    self.event_loop_thread.loop
                )
                future.result(timeout=3)  # 3秒超时
            except Exception as e:
                self.log(f"异步清理超时或失败: {str(e)}")
        
        # 4. 保存配置
        self.save_config()
        
        # 5. 停止事件循环线程
        self.event_loop_thread.stop()
        
        self.log("程序关闭完成")
        
    except Exception as e:
        self.log(f"关闭时出错: {str(e)}")
    
    event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 高DPI显示支持 - 使用 PyQt6 兼容的方式
    # 在 PyQt6 中，高 DPI 缩放默认是启用的，不需要显式设置
    # 只设置高 DPI 图像支持
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
    # 设置应用程序图标
    if os.path.exists('logo.ico'):
        app.setWindowIcon(QIcon('logo.ico'))
    
    # 创建主窗口
    window = AccountManager()
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
