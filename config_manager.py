import json
import os
from pathlib import Path
from datetime import datetime
import shutil

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self._loading = False  # 防止递归加载
        self.config = self.load_config()
        
    def load_config(self):
        """加载配置文件"""
        # 防止递归调用
        if self._loading:
            return self.get_default_config()
        
        self._loading = True
        try:
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    
                    # 验证配置结构
                    if not isinstance(config, dict):
                        raise ValueError("配置文件格式错误")
                    
                    # 确保必要的键存在
                    default_config = self.get_default_config()
                    for key in default_config:
                        if key not in config:
                            config[key] = default_config[key]
                    
                    return config
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"配置文件损坏，使用默认配置: {e}")
                    return self.get_default_config()
            else:
                return self.get_default_config()
        finally:
            self._loading = False
    
    def save_config(self):
        """保存配置文件"""
        try:
            # 备份原配置
            if os.path.exists(self.config_file):
                backup_file = f'backup/config_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                Path('backup').mkdir(exist_ok=True)
                shutil.copy2(self.config_file, backup_file)
            
            # 保存新配置
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False
    
    def get_default_config(self):
        """获取默认配置"""
        return {
            'accounts': {},
            'settings': {
                'join_interval': 60,
                'auto_join': False,
                'broadcast_interval': 180,
                'broadcast_round': 3600,
                'auto_broadcast': False,
                'unmute_interval': 60,
                'unmute_round': 3600,
                'auto_unmute': False,
                'check_mute_interval': 3600,
                'auto_check_mute': False,
                'contact_message_interval': 60,
                'contact_message_round': 3600,
                'auto_contact_message': False,
                'channel_interval': 7560,
                'max_accounts': 30,
                'theme': 'default',
                'contact_msg_interval': 3600,
                'contact_msg_round': 30600,
                'auto_contact_msg': False
            },
            'tasks': {
                'last_join_time': None,
                'last_broadcast_time': None,
                'last_unmute_time': None,
                'last_check_time': None,
                'last_contact_message_time': None,
                'last_channel_create_time': None
            },
            'resources': {
                'api_configs': [],
                'current_api_index': 0
            },
            'saved_passwords': {},  # 保存的二次验证密码
            'joined_groups': {}  # 软件加入的群组记录
        }
    
    def get_setting(self, key, default=None):
        """获取设置项"""
        if not isinstance(self.config, dict):
            return default
        settings = self.config.get('settings', {})
        if not isinstance(settings, dict):
            return default
        return settings.get(key, default)
    
    def set_setting(self, key, value):
        """设置配置项"""
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
        if 'settings' not in self.config:
            self.config['settings'] = {}
        if not isinstance(self.config['settings'], dict):
            self.config['settings'] = {}
        
        self.config['settings'][key] = value
        # 不在这里自动保存，避免递归调用
    
    def get_account(self, phone):
        """获取账号信息"""
        if not isinstance(self.config, dict):
            return None
        accounts = self.config.get('accounts', {})
        if not isinstance(accounts, dict):
            return None
        return accounts.get(phone, None)
    
    def add_account(self, phone, account_info):
        """添加账号"""
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
        if 'accounts' not in self.config:
            self.config['accounts'] = {}
        if not isinstance(self.config['accounts'], dict):
            self.config['accounts'] = {}
        
        self.config['accounts'][phone] = account_info
        # 不在这里自动保存，避免递归调用
    
    def update_account(self, phone, account_info):
        """更新账号信息"""
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
        if 'accounts' not in self.config:
            self.config['accounts'] = {}
        if not isinstance(self.config['accounts'], dict):
            self.config['accounts'] = {}
        
        if phone in self.config['accounts']:
            if isinstance(self.config['accounts'][phone], dict) and isinstance(account_info, dict):
                self.config['accounts'][phone].update(account_info)
            else:
                self.config['accounts'][phone] = account_info
        else:
            self.config['accounts'][phone] = account_info
    
    def remove_account(self, phone):
        """删除账号"""
        if not isinstance(self.config, dict):
            return
        accounts = self.config.get('accounts', {})
        if isinstance(accounts, dict) and phone in accounts:
            del accounts[phone]
    
    def get_all_accounts(self):
        """获取所有账号"""
        if not isinstance(self.config, dict):
            return {}
        accounts = self.config.get('accounts', {})
        return accounts if isinstance(accounts, dict) else {}
    
    def load_api_configs(self):
        """加载API配置"""
        api_file = Path('resources/API配置.txt')
        if not api_file.exists():
            return []
        
        try:
            configs = []
            with open(api_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
                # 每行一个配置，格式：api_id:api_hash
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#') and ':' in line:
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            api_id = parts[0].strip()
                            api_hash = parts[1].strip()
                            if api_id and api_hash:
                                configs.append({
                                    'api_id': api_id,
                                    'api_hash': api_hash
                                })
            
            # 确保config结构正确
            if not isinstance(self.config, dict):
                self.config = self.get_default_config()
            if 'resources' not in self.config:
                self.config['resources'] = {}
            if not isinstance(self.config['resources'], dict):
                self.config['resources'] = {}
            
            self.config['resources']['api_configs'] = configs
            return configs
            
        except Exception as e:
            print(f"加载API配置失败: {e}")
            return []
    
    def get_next_api_config(self):
        """获取下一个API配置（轮询）"""
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
        
        resources = self.config.get('resources', {})
        if not isinstance(resources, dict):
            resources = {}
            self.config['resources'] = resources
        
        configs = resources.get('api_configs', [])
        if not isinstance(configs, list):
            configs = []
        
        if not configs:
            configs = self.load_api_configs()
        
        if not configs:
            return None
        
        current_index = resources.get('current_api_index', 0)
        if not isinstance(current_index, int):
            current_index = 0
        
        config = configs[current_index % len(configs)]
        
        # 更新索引
        resources['current_api_index'] = (current_index + 1) % len(configs)
        
        return config
    
    def get_available_api_configs(self, used_api_ids=None):
        """获取可用的API配置列表"""
        if used_api_ids is None:
            used_api_ids = set()
        
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
        
        resources = self.config.get('resources', {})
        if not isinstance(resources, dict):
            resources = {}
        
        configs = resources.get('api_configs', [])
        if not isinstance(configs, list):
            configs = []
        
        if not configs:
            configs = self.load_api_configs()
        
        # 过滤掉已使用的配置
        available_configs = []
        for config in configs:
            if isinstance(config, dict) and config.get('api_id') not in used_api_ids:
                available_configs.append(config)
        
        return available_configs
    
    def update_task_time(self, task_name):
        """更新任务执行时间"""
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
        if 'tasks' not in self.config:
            self.config['tasks'] = {}
        if not isinstance(self.config['tasks'], dict):
            self.config['tasks'] = {}
        
        self.config['tasks'][f'last_{task_name}_time'] = datetime.now().isoformat()
    
    def get_last_task_time(self, task_name):
        """获取任务上次执行时间"""
        if not isinstance(self.config, dict):
            return None
        
        tasks = self.config.get('tasks', {})
        if not isinstance(tasks, dict):
            return None
        
        time_str = tasks.get(f'last_{task_name}_time')
        if time_str and isinstance(time_str, str):
            try:
                return datetime.fromisoformat(time_str)
            except:
                return None
        return None
    
    def save_password(self, phone, password):
        """保存二次验证密码"""
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
        if 'saved_passwords' not in self.config:
            self.config['saved_passwords'] = {}
        if not isinstance(self.config['saved_passwords'], dict):
            self.config['saved_passwords'] = {}
        
        self.config['saved_passwords'][phone] = password
    
    def get_saved_password(self, phone):
        """获取保存的二次验证密码"""
        if not isinstance(self.config, dict):
            return ''
        
        passwords = self.config.get('saved_passwords', {})
        if not isinstance(passwords, dict):
            return ''
        
        return passwords.get(phone, '')
    
    def get_all_saved_passwords(self):
        """获取所有保存的密码"""
        if not isinstance(self.config, dict):
            return {}
        
        passwords = self.config.get('saved_passwords', {})
        return passwords if isinstance(passwords, dict) else {}
    
    def export_config(self, export_path):
        """导出配置"""
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"导出配置失败: {e}")
            return False
    
    def import_config(self, import_path):
        """导入配置"""
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                imported_config = json.load(f)
            
            if not isinstance(imported_config, dict):
                raise ValueError("导入的配置格式错误")
            
            # 备份当前配置
            self.save_config()
            
            # 合并配置
            if isinstance(self.config, dict):
                self.config.update(imported_config)
            else:
                self.config = imported_config
            
            return True
        except Exception as e:
            print(f"导入配置失败: {e}")
            return False
    
    def reset_config(self):
        """重置配置"""
        self.config = self.get_default_config()
    
    def validate_config(self):
        """验证配置有效性"""
        if not isinstance(self.config, dict):
            self.config = self.get_default_config()
            return True
        
        default_config = self.get_default_config()
        
        # 确保所有必要的键存在
        for key in default_config:
            if key not in self.config:
                self.config[key] = default_config[key]
            elif not isinstance(self.config[key], type(default_config[key])):
                self.config[key] = default_config[key]
        
        # 验证设置值范围
        settings = self.config.get('settings', {})
        if isinstance(settings, dict):
            # 确保间隔时间在合理范围内
            interval_keys = ['join_interval', 'broadcast_interval', 'unmute_interval', 
                            'broadcast_round', 'unmute_round', 'check_mute_interval',
                            'contact_message_interval', 'contact_message_round', 'channel_interval']
            
            for key in interval_keys:
                if key in settings:
                    value = settings[key]
                    if not isinstance(value, (int, float)) or value < 1:
                        settings[key] = default_config['settings'].get(key, 60)
        
        # 确保其他必要字段存在
        if 'saved_passwords' not in self.config:
            self.config['saved_passwords'] = {}
        if 'joined_groups' not in self.config:
            self.config['joined_groups'] = {}
        
        return True
    
    def cleanup_old_backups(self, keep_days=30):
        """清理旧的备份文件"""
        backup_dir = Path('backup')
        if not backup_dir.exists():
            return
        
        try:
            from datetime import timedelta
            cutoff_date = datetime.now() - timedelta(days=keep_days)
            
            for backup_file in backup_dir.glob('config_*.json'):
                try:
                    # 从文件名提取日期
                    name_parts = backup_file.stem.split('_')
                    if len(name_parts) >= 3:
                        date_str = name_parts[1]
                        time_str = name_parts[2]
                        file_date = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                        
                        if file_date < cutoff_date:
                            backup_file.unlink()
                            print(f"删除旧备份文件: {backup_file.name}")
                except:
                    # 如果无法解析日期，跳过该文件
                    continue
                    
        except Exception as e:
            print(f"清理备份文件失败: {e}")
    
    def get_config_stats(self):
        """获取配置统计信息"""
        if not isinstance(self.config, dict):
            return {
                'total_accounts': 0,
                'online_accounts': 0,
                'offline_accounts': 0,
                'error_accounts': 0,
                'total_api_configs': 0,
                'saved_passwords': 0
            }
        
        accounts = self.config.get('accounts', {})
        if not isinstance(accounts, dict):
            accounts = {}
        
        resources = self.config.get('resources', {})
        if not isinstance(resources, dict):
            resources = {}
        
        api_configs = resources.get('api_configs', [])
        if not isinstance(api_configs, list):
            api_configs = []
        
        passwords = self.config.get('saved_passwords', {})
        if not isinstance(passwords, dict):
            passwords = {}
        
        stats = {
            'total_accounts': len(accounts),
            'online_accounts': 0,
            'offline_accounts': 0,
            'error_accounts': 0,
            'total_api_configs': len(api_configs),
            'saved_passwords': len(passwords)
        }
        
        # 统计账号状态
        for account in accounts.values():
            if isinstance(account, dict):
                status = account.get('status', '未知')
                if status == '在线':
                    stats['online_accounts'] += 1
                elif status == '离线':
                    stats['offline_accounts'] += 1
                elif status == '异常':
                    stats['error_accounts'] += 1
        
        return stats