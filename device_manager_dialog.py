from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from device_spoofing import DeviceSpoofing
import json

class DeviceManagerDialog(QDialog):
    """设备管理对话框"""
    
    def __init__(self, parent, async_handler=None):
        super().__init__(parent)
        self.parent = parent
        self.async_handler = async_handler
        self.device_spoofing = DeviceSpoofing()
        self.device_spoofing.load_device_assignments()
        
        self.setup_ui()
        self.load_device_data()
    
    def setup_ui(self):
        """设置UI"""
        self.setWindowTitle("设备伪装管理")
        self.setMinimumSize(900, 700)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # 标题
        title = QLabel("设备伪装管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 标签页
        tab_widget = QTabWidget()
        
        # 账号设备分配标签页
        device_assignment_tab = self.create_device_assignment_tab()
        tab_widget.addTab(device_assignment_tab, "账号设备分配")
        
        # 设备模板管理标签页
        device_template_tab = self.create_device_template_tab()
        tab_widget.addTab(device_template_tab, "设备模板管理")
        
        # 统计信息标签页
        statistics_tab = self.create_statistics_tab()
        tab_widget.addTab(statistics_tab, "统计信息")
        
        layout.addWidget(tab_widget)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("刷新数据")
        self.refresh_btn.clicked.connect(self.refresh_data)
        button_layout.addWidget(self.refresh_btn)
        
        self.save_btn = QPushButton("保存配置")
        self.save_btn.clicked.connect(self.save_config)
        button_layout.addWidget(self.save_btn)
        
        self.reset_btn = QPushButton("重置所有设备")
        self.reset_btn.clicked.connect(self.reset_all_devices)
        self.reset_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        button_layout.addWidget(self.reset_btn)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def create_device_assignment_tab(self):
        """创建账号设备分配标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明文字
        info_label = QLabel(
            "这里显示每个账号分配的设备信息。每个账号会被自动分配一个唯一的设备信息，"
            "包括设备型号、系统版本、应用版本等，使每个账号看起来像是从不同的设备登录。"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 5px;")
        layout.addWidget(info_label)
        
        # 搜索和过滤
        filter_layout = QHBoxLayout()
        
        filter_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入手机号或设备型号...")
        self.search_input.textChanged.connect(self.filter_devices)
        filter_layout.addWidget(self.search_input)
        
        filter_layout.addWidget(QLabel("设备类型:"))
        self.device_type_filter = QComboBox()
        self.device_type_filter.addItems(["全部", "Android", "iOS", "Desktop"])
        self.device_type_filter.currentTextChanged.connect(self.filter_devices)
        filter_layout.addWidget(self.device_type_filter)
        
        filter_layout.addStretch()
        
        self.reassign_btn = QPushButton("重新分配选中设备")
        self.reassign_btn.clicked.connect(self.reassign_selected_devices)
        filter_layout.addWidget(self.reassign_btn)
        
        layout.addLayout(filter_layout)
        
        # 设备分配表格
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(8)
        self.device_table.setHorizontalHeaderLabels([
            "选择", "手机号", "设备型号", "系统版本", "应用版本", 
            "语言", "设备类型", "分配时间"
        ])
        
        # 设置列宽
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        
        self.device_table.setColumnWidth(0, 50)
        self.device_table.setColumnWidth(1, 120)
        self.device_table.setColumnWidth(3, 100)
        self.device_table.setColumnWidth(4, 100)
        self.device_table.setColumnWidth(5, 80)
        self.device_table.setColumnWidth(6, 100)
        self.device_table.setColumnWidth(7, 120)
        
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.device_table)
        
        return widget
    
    def create_device_template_tab(self):
        """创建设备模板管理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 说明文字
        info_label = QLabel(
            "设备模板管理：这里可以查看和管理所有可用的设备模板。"
            "系统会从这些模板中为每个账号随机分配设备信息。"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 5px;")
        layout.addWidget(info_label)
        
        # 设备类型选择
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("设备类型:"))
        
        self.template_type_combo = QComboBox()
        self.template_type_combo.addItems(["android", "ios", "desktop"])
        self.template_type_combo.currentTextChanged.connect(self.load_templates)
        type_layout.addWidget(self.template_type_combo)
        
        type_layout.addStretch()
        
        self.add_template_btn = QPushButton("添加模板")
        self.add_template_btn.clicked.connect(self.add_template)
        type_layout.addWidget(self.add_template_btn)
        
        layout.addLayout(type_layout)
        
        # 模板列表
        self.template_table = QTableWidget()
        self.template_table.setColumnCount(6)
        self.template_table.setHorizontalHeaderLabels([
            "设备型号", "系统版本", "应用版本", "语言代码", "系统语言", "操作"
        ])
        
        header = self.template_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        
        self.template_table.setColumnWidth(1, 100)
        self.template_table.setColumnWidth(2, 100)
        self.template_table.setColumnWidth(3, 80)
        self.template_table.setColumnWidth(4, 80)
        self.template_table.setColumnWidth(5, 100)
        
        layout.addWidget(self.template_table)
        
        return widget
    
    def create_statistics_tab(self):
        """创建统计信息标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 总体统计
        stats_group = QGroupBox("总体统计")
        stats_layout = QGridLayout(stats_group)
        
        self.total_devices_label = QLabel("0")
        self.android_count_label = QLabel("0")
        self.ios_count_label = QLabel("0")
        self.desktop_count_label = QLabel("0")
        
        stats_layout.addWidget(QLabel("总设备数:"), 0, 0)
        stats_layout.addWidget(self.total_devices_label, 0, 1)
        stats_layout.addWidget(QLabel("Android设备:"), 1, 0)
        stats_layout.addWidget(self.android_count_label, 1, 1)
        stats_layout.addWidget(QLabel("iOS设备:"), 2, 0)
        stats_layout.addWidget(self.ios_count_label, 2, 1)
        stats_layout.addWidget(QLabel("桌面设备:"), 3, 0)
        stats_layout.addWidget(self.desktop_count_label, 3, 1)
        
        layout.addWidget(stats_group)
        
        # 设备型号分布
        model_group = QGroupBox("设备型号分布")
        model_layout = QVBoxLayout(model_group)
        
        self.model_list = QListWidget()
        model_layout.addWidget(self.model_list)
        
        layout.addWidget(model_group)
        
        # 刷新按钮
        refresh_stats_btn = QPushButton("刷新统计")
        refresh_stats_btn.clicked.connect(self.refresh_statistics)
        layout.addWidget(refresh_stats_btn)
        
        layout.addStretch()
        
        return widget
    
    def load_device_data(self):
        """加载设备数据"""
        self.device_table.setRowCount(0)
        
        # 如果有主窗口的账号数据，优先使用
        if self.parent and hasattr(self.parent, 'accounts'):
            accounts = self.parent.accounts
        else:
            accounts = {}
        
        # 为所有账号生成设备信息（如果还没有的话）
        for phone in accounts.keys():
            device_info = self.device_spoofing.get_device_info(phone)
        
        # 显示设备分配
        row = 0
        for phone, device_info in self.device_spoofing.used_devices.items():
            self.device_table.insertRow(row)
            
            # 复选框
            checkbox = QCheckBox()
            self.device_table.setCellWidget(row, 0, checkbox)
            
            # 手机号
            self.device_table.setItem(row, 1, QTableWidgetItem(phone))
            
            # 设备型号
            self.device_table.setItem(row, 2, QTableWidgetItem(device_info['device_model']))
            
            # 系统版本
            self.device_table.setItem(row, 3, QTableWidgetItem(device_info['system_version']))
            
            # 应用版本
            self.device_table.setItem(row, 4, QTableWidgetItem(device_info['app_version']))
            
            # 语言
            self.device_table.setItem(row, 5, QTableWidgetItem(device_info['lang_code']))
            
            # 设备类型
            device_type = self.get_device_type(device_info['device_model'])
            self.device_table.setItem(row, 6, QTableWidgetItem(device_type))
            
            # 分配时间（模拟）
            self.device_table.setItem(row, 7, QTableWidgetItem("自动分配"))
            
            row += 1
        
        # 加载模板
        self.load_templates()
        
        # 刷新统计
        self.refresh_statistics()
    
    def get_device_type(self, device_model):
        """根据设备型号判断设备类型"""
        model_lower = device_model.lower()
        if any(brand in model_lower for brand in ['samsung', 'xiaomi', 'oppo', 'vivo', 'huawei', 'oneplus', 'pixel']):
            return "Android"
        elif 'iphone' in model_lower or 'ipad' in model_lower:
            return "iOS"
        elif 'desktop' in model_lower:
            return "Desktop"
        else:
            return "Unknown"
    
    def load_templates(self):
        """加载设备模板"""
        device_type = self.template_type_combo.currentText()
        templates = self.device_spoofing.device_templates.get(device_type, [])
        
        self.template_table.setRowCount(len(templates))
        
        for row, template in enumerate(templates):
            self.template_table.setItem(row, 0, QTableWidgetItem(template['device_model']))
            self.template_table.setItem(row, 1, QTableWidgetItem(template['system_version']))
            self.template_table.setItem(row, 2, QTableWidgetItem(template['app_version']))
            self.template_table.setItem(row, 3, QTableWidgetItem(template['lang_code']))
            self.template_table.setItem(row, 4, QTableWidgetItem(template['system_lang_code']))
            
            # 操作按钮
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(5, 0, 5, 0)
            
            edit_btn = QPushButton("编辑")
            edit_btn.clicked.connect(lambda checked, r=row: self.edit_template(r))
            action_layout.addWidget(edit_btn)
            
            delete_btn = QPushButton("删除")
            delete_btn.clicked.connect(lambda checked, r=row: self.delete_template(r))
            delete_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
            action_layout.addWidget(delete_btn)
            
            self.template_table.setCellWidget(row, 5, action_widget)
    
    def filter_devices(self):
        """过滤设备列表"""
        search_text = self.search_input.text().lower()
        device_type_filter = self.device_type_filter.currentText()
        
        for row in range(self.device_table.rowCount()):
            show_row = True
            
            # 搜索过滤
            if search_text:
                phone = self.device_table.item(row, 1).text().lower()
                device_model = self.device_table.item(row, 2).text().lower()
                if search_text not in phone and search_text not in device_model:
                    show_row = False
            
            # 设备类型过滤
            if device_type_filter != "全部":
                device_type = self.device_table.item(row, 6).text()
                if device_type != device_type_filter:
                    show_row = False
            
            self.device_table.setRowHidden(row, not show_row)
    
    def reassign_selected_devices(self):
        """重新分配选中的设备"""
        selected_phones = []
        
        for row in range(self.device_table.rowCount()):
            checkbox = self.device_table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                phone = self.device_table.item(row, 1).text()
                selected_phones.append(phone)
        
        if not selected_phones:
            QMessageBox.warning(self, "警告", "请先选择要重新分配的设备")
            return
        
        reply = QMessageBox.question(
            self, "确认", 
            f"确定要重新分配 {len(selected_phones)} 个账号的设备信息吗？\n"
            f"这将为这些账号生成新的设备信息。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for phone in selected_phones:
                # 从已使用设备中移除
                if phone in self.device_spoofing.used_devices:
                    del self.device_spoofing.used_devices[phone]
                
                # 重新生成设备信息
                self.device_spoofing.get_device_info(phone)
            
            # 重新加载数据
            self.load_device_data()
            QMessageBox.information(self, "成功", f"已重新分配 {len(selected_phones)} 个账号的设备信息")
    
    def add_template(self):
        """添加设备模板"""
        dialog = DeviceTemplateDialog(self, "添加设备模板")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            template = dialog.get_template()
            device_type = self.template_type_combo.currentText()
            
            self.device_spoofing.device_templates[device_type].append(template)
            self.load_templates()
            QMessageBox.information(self, "成功", "设备模板添加成功")
    
    def edit_template(self, row):
        """编辑设备模板"""
        device_type = self.template_type_combo.currentText()
        template = self.device_spoofing.device_templates[device_type][row]
        
        dialog = DeviceTemplateDialog(self, "编辑设备模板", template)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_template = dialog.get_template()
            self.device_spoofing.device_templates[device_type][row] = new_template
            self.load_templates()
            QMessageBox.information(self, "成功", "设备模板编辑成功")
    
    def delete_template(self, row):
        """删除设备模板"""
        reply = QMessageBox.question(
            self, "确认", "确定要删除这个设备模板吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            device_type = self.template_type_combo.currentText()
            del self.device_spoofing.device_templates[device_type][row]
            self.load_templates()
            QMessageBox.information(self, "成功", "设备模板删除成功")
    
    def refresh_statistics(self):
        """刷新统计信息"""
        summary = self.device_spoofing.get_device_summary()
        
        self.total_devices_label.setText(str(summary['total_devices']))
        self.android_count_label.setText(str(summary['android_count']))
        self.ios_count_label.setText(str(summary['ios_count']))
        self.desktop_count_label.setText(str(summary['desktop_count']))
        
        # 设备型号分布
        self.model_list.clear()
        for model, count in sorted(summary['device_models'].items(), key=lambda x: x[1], reverse=True):
            self.model_list.addItem(f"{model}: {count}个")
    
    def refresh_data(self):
        """刷新数据"""
        self.device_spoofing.load_device_assignments()
        self.load_device_data()
        QMessageBox.information(self, "成功", "数据刷新完成")
    
    def save_config(self):
        """保存配置"""
        success = self.device_spoofing.save_device_assignments()
        if success:
            QMessageBox.information(self, "成功", "设备配置保存成功")
        else:
            QMessageBox.critical(self, "错误", "设备配置保存失败")
    
    def reset_all_devices(self):
        """重置所有设备"""
        reply = QMessageBox.question(
            self, "确认", 
            "确定要重置所有账号的设备信息吗？\n"
            "这将清除所有现有的设备分配，为每个账号重新生成设备信息。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.device_spoofing.used_devices.clear()
            
            # 如果有主窗口的账号数据，重新为所有账号生成设备信息
            if self.parent and hasattr(self.parent, 'accounts'):
                for phone in self.parent.accounts.keys():
                    self.device_spoofing.get_device_info(phone)
            
            self.load_device_data()
            QMessageBox.information(self, "成功", "所有设备信息已重置")


class DeviceTemplateDialog(QDialog):
    """设备模板编辑对话框"""
    
    def __init__(self, parent, title, template=None):
        super().__init__(parent)
        self.template = template or {}
        self.setWindowTitle(title)
        self.setModal(True)
        self.setup_ui()
        
        if template:
            self.load_template(template)
    
    def setup_ui(self):
        """设置UI"""
        layout = QFormLayout(self)
        
        self.device_model_input = QLineEdit()
        self.device_model_input.setPlaceholderText("例如: Samsung Galaxy S24")
        layout.addRow("设备型号:", self.device_model_input)
        
        self.system_version_input = QLineEdit()
        self.system_version_input.setPlaceholderText("例如: 14")
        layout.addRow("系统版本:", self.system_version_input)
        
        self.app_version_input = QLineEdit()
        self.app_version_input.setPlaceholderText("例如: 10.14.5")
        layout.addRow("应用版本:", self.app_version_input)
        
        self.lang_code_input = QLineEdit()
        self.lang_code_input.setPlaceholderText("例如: en")
        layout.addRow("语言代码:", self.lang_code_input)
        
        self.system_lang_code_input = QLineEdit()
        self.system_lang_code_input.setPlaceholderText("例如: en")
        layout.addRow("系统语言代码:", self.system_lang_code_input)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addRow(button_layout)
    
    def load_template(self, template):
        """加载模板数据"""
        self.device_model_input.setText(template.get('device_model', ''))
        self.system_version_input.setText(template.get('system_version', ''))
        self.app_version_input.setText(template.get('app_version', ''))
        self.lang_code_input.setText(template.get('lang_code', ''))
        self.system_lang_code_input.setText(template.get('system_lang_code', ''))
    
    def get_template(self):
        """获取模板数据"""
        return {
            'device_model': self.device_model_input.text().strip(),
            'system_version': self.system_version_input.text().strip(),
            'app_version': self.app_version_input.text().strip(),
            'lang_code': self.lang_code_input.text().strip(),
            'system_lang_code': self.system_lang_code_input.text().strip()
        }