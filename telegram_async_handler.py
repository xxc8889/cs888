import asyncio
import random
import shutil
from pathlib import Path
from datetime import datetime
from telethon import TelegramClient, events, functions, types
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError,
    UserDeactivatedError, UserDeactivatedBanError, AuthKeyUnregisteredError,
    UnauthorizedError, PhoneNumberBannedError, PhoneNumberInvalidError,
    ApiIdInvalidError, ApiIdPublishedFloodError, SessionRevokedError,
    UserMigrateError, NetworkMigrateError, PhoneMigrateError, UserBannedInChannelError,
    ChatWriteForbiddenError, UserRestrictedError, PeerFloodError
)
from telethon.tl import functions, types
from telethon.tl.functions.messages import GetDialogsRequest, SendMessageRequest
from telethon.tl.functions.channels import JoinChannelRequest, GetParticipantRequest, CreateChannelRequest, EditAdminRequest, LeaveChannelRequest
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.contacts import AddContactRequest, ImportContactsRequest, ResolveUsernameRequest
from telethon.tl.types import InputPeerEmpty, ChatBannedRights, InputPhoneContact, ChatAdminRights
from PyQt6.QtCore import QObject, pyqtSignal, QThread
import logging
import json

class WorkerSignals(QObject):
    """工作线程信号"""
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    update_account_status = pyqtSignal(str, dict)
    update_group_list = pyqtSignal(list)
    profile_updated = pyqtSignal(str, dict)  # 资料更新信号
    stranger_message = pyqtSignal(dict)

class TelegramAsyncHandler:
    """Telegram异步处理器"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.clients = {}
        self.temp_clients = {}  # 临时客户端，用于登录过程
        self.running_tasks = {}
        self.signals = WorkerSignals()
        
        # 任务控制标志 - 改为每个账号独立的标志
        self.stop_flags = {}
        
        # 已添加的联系人记录
        self.added_contacts = {}
        
        # 群组记录 - 保存每个账号加入的群组
        self.account_groups = {}
        self.load_group_records()
        # 保存事件处理器引用，防止被垃圾回收
        self.message_handlers = {}
        self.monitoring_phones = set()  # 正在监听的账号
        
    def load_group_records(self):
        """加载群组记录"""
        try:
            groups_file = Path('resources/account_groups.json')
            if groups_file.exists():
                with open(groups_file, 'r', encoding='utf-8') as f:
                    self.account_groups = json.load(f)
        except Exception as e:
            self.signals.log.emit(f"加载群组记录失败: {str(e)}")
            self.account_groups = {}
    
    def save_group_records(self):
        """保存群组记录"""
        try:
            groups_file = Path('resources/account_groups.json')
            with open(groups_file, 'w', encoding='utf-8') as f:
                json.dump(self.account_groups, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.signals.log.emit(f"保存群组记录失败: {str(e)}")
    
    def init_stop_flags(self, phone):
        """初始化账号的停止标志"""
        if phone not in self.stop_flags:
            self.stop_flags[phone] = {
                'join_group': False,
                'broadcast': False,
                'unmute': False,
                'check_status': False,
                'create_channel': False,
                'contact_message': False,
                'update_profile': False,
                'add_contact': False,
                'stranger_monitor': False
            }
    
    def load_proxy_config(self):
        """加载代理配置"""
        try:
            proxy_file = Path('resources/proxy.txt')
            if proxy_file.exists():
                with open(proxy_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if line.startswith('http://'):
                                parts = line[7:].split(':')
                                if len(parts) == 2:
                                    return ('http', parts[0], int(parts[1]))
                            elif line.startswith('socks5://'):
                                parts = line[9:].split(':')
                                if len(parts) == 2:
                                    return ('socks5', parts[0], int(parts[1]))
            return None
        except Exception as e:
            print(f"加载代理配置失败: {e}")
            return None
        
    async def initialize(self):
        """初始化处理器"""
        self.signals.log.emit("异步处理器初始化完成")
    
    def is_account_banned_or_frozen(self, error):
        """检测账号是否被冻结或封禁"""
        banned_errors = [
            UserDeactivatedError,
            UserDeactivatedBanError,
            PhoneNumberBannedError,
            AuthKeyUnregisteredError,
            UnauthorizedError,
            SessionRevokedError,
            UserBannedInChannelError,
            UserRestrictedError,
            PeerFloodError
        ]
        
        return any(isinstance(error, err_type) for err_type in banned_errors)
    
    def get_account_status_from_error(self, error):
        """从错误中获取账号状态"""
        if isinstance(error, UserDeactivatedError):
            return "已停用"
        elif isinstance(error, UserDeactivatedBanError):
            return "已封禁"
        elif isinstance(error, PhoneNumberBannedError):
            return "号码被禁"
        elif isinstance(error, AuthKeyUnregisteredError):
            return "授权失效"
        elif isinstance(error, UnauthorizedError):
            return "未授权"
        elif isinstance(error, SessionRevokedError):
            return "会话撤销"
        elif isinstance(error, ApiIdInvalidError):
            return "API无效"
        elif isinstance(error, PhoneNumberInvalidError):
            return "号码无效"
        elif isinstance(error, FloodWaitError):
            return f"限流{error.seconds}秒"
        elif isinstance(error, UserBannedInChannelError):
            return "频道封禁"
        elif isinstance(error, UserRestrictedError):
            return "账号受限"
        elif isinstance(error, PeerFloodError):
            return "操作过于频繁"
        else:
            return "连接异常"
    
    async def check_spambot_status(self, client):
        """检查SpamBot状态 - 检测账号是否被Telegram官方封禁"""
        try:
            # 尝试联系SpamBot，增加超时和错误处理
            spambot = await asyncio.wait_for(client.get_entity('SpamBot'), timeout=10)
            
            # 发送/start命令
            await asyncio.wait_for(client.send_message(spambot, '/start'), timeout=10)
            await asyncio.sleep(3)
            
            # 获取最近的消息
            messages = await asyncio.wait_for(client.get_messages(spambot, limit=5), timeout=10)
            
            for message in messages:
                if message.text:
                    text = message.text.lower()
                    # 检测封禁关键词
                    if any(keyword in text for keyword in [
                        'your account was blocked',
                        'account was limited',
                        'violations of the telegram terms',
                        'based on user reports',
                        'account has been restricted',
                        'suspended',
                        'banned'
                    ]):
                        return "SpamBot检测到账号被封禁"
                    elif 'good news' in text or 'no limits' in text:
                        return "正常"
            
            return "正常"
            
        except asyncio.TimeoutError:
            return "SpamBot检测超时"
        except Exception as e:
            # 如果无法联系SpamBot，可能是网络问题或其他原因
            error_text = str(e).lower()
            if any(keyword in error_text for keyword in [
                'flood', 'wait', 'too many requests'
            ]):
                return "SpamBot检测频繁"
            return "SpamBot检测失败"
    
    async def comprehensive_account_check(self, client, phone):
        """综合账号检查 - 包括基础连接和SpamBot检查"""
        try:
            # 1. 基础连接检查
            if not await client.is_user_authorized():
                return "未授权"
            
            # 2. 获取用户信息
            me = await asyncio.wait_for(client.get_me(), timeout=10)
            if not me:
                return "无法获取用户信息"
            
            # 3. 检查SpamBot状态 - 增加try-catch避免SpamBot检查失败影响整体判断
            try:
                spambot_status = await self.check_spambot_status(client)
                if spambot_status != "正常" and "检测失败" not in spambot_status and "检测超时" not in spambot_status:
                    return spambot_status
            except Exception as e:
                # SpamBot检查失败不影响整体判断，记录日志但继续其他检查
                self.signals.log.emit(f"{phone} SpamBot检查异常: {str(e)}")
            
            # 4. 尝试获取对话列表（测试基本功能）
            try:
                dialogs = await asyncio.wait_for(client.get_dialogs(limit=1), timeout=15)
            except Exception as e:
                if self.is_account_banned_or_frozen(e):
                    return self.get_account_status_from_error(e)
                return "获取对话失败"
            
            # 5. 尝试解析一个公开用户名（测试网络功能）
            try:
                await asyncio.wait_for(client.get_entity('telegram'), timeout=10)
            except Exception as e:
                if self.is_account_banned_or_frozen(e):
                    return self.get_account_status_from_error(e)
                # 这个错误不影响整体判断
                pass
            
            return "在线"
            
        except asyncio.TimeoutError:
            return "连接超时"
        except Exception as e:
            if self.is_account_banned_or_frozen(e):
                return self.get_account_status_from_error(e)
            return "检测异常"
    
    async def send_verification_code(self, phone, api_id, api_hash):
        """发送验证码"""
        session_file = f'sessions/{phone}.session'
        
        try:
            # 添加代理支持
            proxy_config = self.load_proxy_config()
            if proxy_config:
                client = TelegramClient(session_file, api_id, api_hash, proxy=proxy_config)
            else:
                client = TelegramClient(session_file, api_id, api_hash)
            
            await client.connect()
            
            # 发送验证码并等待确认
            result = await client.send_code_request(f"+{phone}")
            
            # 检查发送结果
            if result:
                self.signals.log.emit(f"验证码发送成功至 +{phone}")
                self.signals.log.emit(f"发送详情: type={type(result).__name__}")
                
                # 保存临时客户端
                self.temp_clients[phone] = client
                return True
            else:
                self.signals.log.emit(f"验证码发送失败 +{phone}: 无返回结果")
                try:
                    await client.disconnect()
                except:
                    pass
                return False
            
        except PhoneNumberBannedError:
            self.signals.log.emit(f"手机号码被封禁: +{phone}")
            if phone in self.temp_clients:
                try:
                    await self.temp_clients[phone].disconnect()
                except:
                    pass
                del self.temp_clients[phone]
            return False
        except PhoneNumberInvalidError:
            self.signals.log.emit(f"手机号码无效: +{phone}")
            return False
        except ApiIdInvalidError:
            self.signals.log.emit(f"API ID无效: {api_id}")
            return False
        except FloodWaitError as e:
            self.signals.log.emit(f"发送验证码太频繁，需等待 {e.seconds} 秒: +{phone}")
            return False
        except Exception as e:
            self.signals.log.emit(f"发送验证码失败 {phone}: {str(e)}")
            if phone in self.temp_clients:
                try:
                    await self.temp_clients[phone].disconnect()
                except:
                    pass
                del self.temp_clients[phone]
            return False
    
    async def complete_login(self, phone, api_id, api_hash, code, password=None):
        """完成登录"""
        if phone not in self.temp_clients:
            return False
        
        client = self.temp_clients[phone]
        
        try:
            # 尝试用验证码登录
            try:
                await client.sign_in(f"+{phone}", code)
            except PhoneCodeInvalidError:
                self.signals.log.emit(f"验证码错误: {phone}")
                return False
            except SessionPasswordNeededError:
                # 需要两步验证密码
                if not password:
                    self.signals.log.emit(f"需要两步验证密码: {phone}")
                    return False
                await client.sign_in(password=password)
            
            # 获取用户信息
            me = await client.get_me()
            self.signals.log.emit(f"{phone} 获取用户信息: {me.first_name} {me.last_name} @{me.username}")
            
            # 构建完整的用户信息
            user_info = {
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'username': me.username or '',
                'user_id': str(me.id)
            }
            
            # 构建账号信息
            account_info = {
                'api_id': str(api_id),
                'api_hash': str(api_hash),
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'username': me.username or '',
                'phone': phone,
                'user_id': str(me.id),
                'status': '在线'
            }
            
            # 移动到正式客户端列表
            self.clients[phone] = client
            del self.temp_clients[phone]
            
            # 发送两个信号：账号状态更新 + 资料更新
            self.signals.log.emit(f"{phone} 发送账号状态更新信号")
            self.signals.update_account_status.emit(phone, account_info)
            
            self.signals.log.emit(f"{phone} 发送资料更新信号")
            self.signals.profile_updated.emit(phone, user_info)
            
            self.signals.log.emit(f"账号登录成功: +{phone} ({me.first_name} {me.last_name})")
            
            # 复制session文件到ok文件夹
            session_file = Path(f'sessions/{phone}.session')
            ok_session = Path(f'sessions/ok/{phone}.session')
            if session_file.exists():
                shutil.copy2(session_file, ok_session)
            
            return True
            
        except Exception as e:
            self.signals.log.emit(f"登录失败 {phone}: {str(e)}")
            
            # 检测账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"账号状态异常 {phone}: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            
            try:
                await client.disconnect()
            except:
                pass
            if phone in self.temp_clients:
                del self.temp_clients[phone]
            return False
    
    async def check_account_status(self, phone):
        """检测账号状态"""
        session_file = Path(f'sessions/{phone}.session')
        
        if phone not in self.clients:
            # 尝试连接
            account = self.main_window.accounts.get(phone, {})
            api_id = account.get('api_id')
            api_hash = account.get('api_hash')
            
            if not api_id or not api_hash:
                self.signals.log.emit(f"账号 {phone} 缺少API配置")
                return False
            
            client = TelegramClient(str(session_file), api_id, api_hash)
            
            try:
                proxy_config = self.load_proxy_config()
                if proxy_config:
                    client = TelegramClient(str(session_file), api_id, api_hash, proxy=proxy_config)
                else:
                    client = TelegramClient(str(session_file), api_id, api_hash)
                await client.connect()
                if await client.is_user_authorized():
                    # 使用综合检查方法
                    status = await self.comprehensive_account_check(client, phone)
                    
                    if status == "在线":
                        me = await client.get_me()
                        self.clients[phone] = client
                        
                        # 构建完整的用户信息
                        user_info = {
                            'first_name': me.first_name or '',
                            'last_name': me.last_name or '',
                            'username': me.username or '',
                            'user_id': str(me.id)
                        }
                        
                        # 构建账号信息
                        account_info = {
                            'api_id': api_id,
                            'api_hash': api_hash,
                            'first_name': me.first_name or '',
                            'last_name': me.last_name or '',
                            'username': me.username or '',
                            'status': status
                        }
                        
                        # 发送两个信号
                        self.signals.update_account_status.emit(phone, account_info)
                        self.signals.profile_updated.emit(phone, user_info)
                        
                        # 复制session到ok文件夹
                        ok_session = Path(f'sessions/ok/{phone}.session')
                        if session_file.exists():
                            shutil.copy2(session_file, ok_session)
                        
                        return True
                    else:
                        # 账号状态异常
                        await client.disconnect()
                        self.signals.log.emit(f"账号 {phone} 状态异常: {status}")
                        self.signals.update_account_status.emit(phone, {'status': status})
                        
                        # 移动session到error文件夹
                        if session_file.exists():
                            error_session = Path(f'sessions/error/{phone}_{status}.session')
                            error_session.parent.mkdir(exist_ok=True)
                            try:
                                shutil.move(str(session_file), str(error_session))
                            except:
                                pass
                        
                        return False
                else:
                    await client.disconnect()
                    self.signals.update_account_status.emit(phone, {'status': '未登录'})
                    return False
                    
            except Exception as e:
                # 检测账号冻结或封禁状态
                if self.is_account_banned_or_frozen(e):
                    status = self.get_account_status_from_error(e)
                    self.signals.log.emit(f"账号 {phone} 状态异常: {status}")
                    self.signals.update_account_status.emit(phone, {'status': status})
                    
                    # 移动session到error文件夹
                    if session_file.exists():
                        error_session = Path(f'sessions/error/{phone}_{status}.session')
                        error_session.parent.mkdir(exist_ok=True)
                        try:
                            shutil.move(str(session_file), str(error_session))
                        except:
                            pass
                else:
                    self.signals.log.emit(f"账号 {phone} 检测失败: {str(e)}")
                    self.signals.update_account_status.emit(phone, {'status': '连接异常'})
                
                try:
                    await client.disconnect()
                except:
                    pass
                
                return False
        
        else:
            # 已连接的客户端检查部分
            client = self.clients[phone]
            try:
                status = await self.comprehensive_account_check(client, phone)
                
                if status == "在线":
                    me = await client.get_me()
                    account = self.main_window.accounts.get(phone, {})
                    
                    # 构建完整的用户信息
                    user_info = {
                        'first_name': me.first_name or '',
                        'last_name': me.last_name or '',
                        'username': me.username or '',
                        'user_id': str(me.id)
                    }
                    
                    # 构建账号信息
                    account_info = {
                        'api_id': account.get('api_id', ''),
                        'api_hash': account.get('api_hash', ''),
                        'first_name': me.first_name or '',
                        'last_name': me.last_name or '',
                        'username': me.username or '',
                        'status': status
                    }
                    
                    # 发送两个信号
                    self.signals.update_account_status.emit(phone, account_info)
                    self.signals.profile_updated.emit(phone, user_info)
                    
                    return True
                else:
                    # 状态异常
                    self.signals.log.emit(f"账号 {phone} 运行时状态异常: {status}")
                    self.signals.update_account_status.emit(phone, {'status': status})
                    
                    # 从客户端列表中移除
                    if phone in self.clients:
                        try:
                            await self.clients[phone].disconnect()
                        except:
                            pass
                        del self.clients[phone]
                    
                    return False
                    
            except Exception as e:
                # 检测运行时的账号状态变化
                if self.is_account_banned_or_frozen(e):
                    status = self.get_account_status_from_error(e)
                    self.signals.log.emit(f"账号 {phone} 运行时状态异常: {status}")
                    self.signals.update_account_status.emit(phone, {'status': status})
                    
                    # 从客户端列表中移除
                    if phone in self.clients:
                        try:
                            await self.clients[phone].disconnect()
                        except:
                            pass
                        del self.clients[phone]
                else:
                    self.signals.update_account_status.emit(phone, {'status': '离线'})
                return False
    
    async def ensure_client_connected(self, phone):
        """确保客户端已连接"""
        if phone not in self.clients:
            # 尝试连接
            account = self.main_window.accounts.get(phone, {})
            api_id = account.get('api_id')
            api_hash = account.get('api_hash')
            
            if not api_id or not api_hash:
                self.signals.log.emit(f"账号 {phone} 缺少API配置")
                return None
            
            session_file = f'sessions/{phone}.session'
            client = TelegramClient(session_file, api_id, api_hash)
            
            try:
                proxy_config = self.load_proxy_config()
                if proxy_config:
                    client = TelegramClient(session_file, api_id, api_hash, proxy=proxy_config)
                else:
                    client = TelegramClient(session_file, api_id, api_hash)
                await client.connect()
                if await client.is_user_authorized():
                    self.clients[phone] = client
                    return client
                else:
                    await client.disconnect()
                    self.signals.log.emit(f"账号 {phone} 未授权")
                    return None
            except Exception as e:
                # 检测连接时的账号状态
                if self.is_account_banned_or_frozen(e):
                    status = self.get_account_status_from_error(e)
                    self.signals.log.emit(f"账号 {phone} 连接失败: {status}")
                    self.signals.update_account_status.emit(phone, {'status': status})
                else:
                    self.signals.log.emit(f"连接账号 {phone} 失败: {str(e)}")
                try:
                    await client.disconnect()
                except:
                    pass
                return None
        
        return self.clients[phone]
    async def start_stranger_message_monitor(self, phone, auto_reply_enabled=False, bot_notify_enabled=False):
        """启动陌生人消息监听 - 增强版"""
        self.signals.log.emit(f"🔄 正在为 {phone} 启动陌生人消息监听...")
    
        client = await self.ensure_client_connected(phone)
        if not client:
            self.signals.log.emit(f"❌ {phone} 客户端连接失败")
            return False
    
        # 如果已经在监听，先停止
        if phone in self.monitoring_phones:
            await self.stop_stranger_message_monitor(phone)
    
        try:
            # 测试客户端是否正常工作
            try:
                me = await client.get_me()
                self.signals.log.emit(f"✅ {phone} 客户端测试成功，用户: {me.first_name}")
            except Exception as e:
                self.signals.log.emit(f"❌ {phone} 客户端测试失败: {str(e)}")
                return False
        
            # 定义消息处理器 - 使用更简单的逻辑先测试
            async def handle_all_messages(event):
                try:
                    # 只处理私聊消息（不是群组消息）
                    if event.is_private and event.message.text:
                        sender = await event.get_sender()
                    
                        # 先不判断是否为联系人，直接处理所有私聊消息用于测试
                        self.signals.log.emit(f"📨 {phone} 收到私聊消息，发送者ID: {sender.id}")
                    
                        # 检查是否为陌生人
                        is_stranger = not await self.is_contact_enhanced(client, sender)
                    
                        if is_stranger:
                            self.signals.log.emit(f"👤 {phone} 确认为陌生人消息")
                        
                            # 构建消息数据
                            message_data = {
                                'phone': phone,
                                'sender_id': sender.id,
                                'sender_name': self.get_user_display_name(sender),
                                'sender_username': getattr(sender, 'username', '') or '无',
                                'sender_phone': getattr(sender, 'phone', '') or '未知',
                                'message': event.message.text[:500],  # 限制长度
                                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                        
                            self.signals.log.emit(f"📤 {phone} 发送陌生人消息信号到UI")
                        
                            # 发送到主界面显示
                            self.signals.stranger_message.emit(message_data)
                        
                            # 自动回复
                            if auto_reply_enabled:
                                await self.send_auto_reply_enhanced(client, sender, phone)
                        
                            # 机器人通知
                            if bot_notify_enabled:
                                await self.send_bot_notification_enhanced(phone, message_data)
                        else:
                            self.signals.log.emit(f"👥 {phone} 跳过联系人消息")
                        
                except Exception as e:
                    self.signals.log.emit(f"❌ {phone} 处理消息时出错: {str(e)}")
                    import traceback
                    self.signals.log.emit(f"详细错误: {traceback.format_exc()}")
        
            # 注册事件处理器
            self.signals.log.emit(f"🔗 {phone} 正在注册事件处理器...")
            client.add_event_handler(handle_all_messages, events.NewMessage(incoming=True))
        
            # 保存强引用
            self.message_handlers[phone] = handle_all_messages
            self.monitoring_phones.add(phone)
        
            self.signals.log.emit(f"✅ {phone} 陌生人消息监听启动成功")
        
            # 发送测试日志确认监听正常
            self.signals.log.emit(f"🎯 {phone} 监听器已激活，等待接收消息...")
        
            return True
        
        except Exception as e:
            self.signals.log.emit(f"❌ {phone} 启动陌生人消息监听失败: {str(e)}")
            import traceback
            self.signals.log.emit(f"详细错误: {traceback.format_exc()}")
            return False

    async def is_contact(self, client, user):
        """检查用户是否为联系人"""
        try:
            # 获取联系人列表
            contacts = await client.get_contacts()
            for contact in contacts:
                if contact.id == user.id:
                    return True
            return False
        except:
            return False

    async def send_auto_reply_enhanced(self, client, sender, phone):
        """增强的自动回复 - 修复编码问题"""
        try:
            self.signals.log.emit(f"🤖 {phone} 准备发送自动回复...")

            # 标记消息为已读
            try:
                await client.send_read_acknowledge(sender)
                self.signals.log.emit(f"📖 {phone} 已读陌生人消息")
            except Exception as read_error:
                self.signals.log.emit(f"⚠️ {phone} 标记已读失败: {str(read_error)}")
        
            # 加载自动回复内容
            replies = self.main_window.load_resource_file('自动回复.txt')
            if not replies:
                # 如果没有配置文件，使用默认回复
                replies = [
                    "您好！我现在不在线，稍后回复您。",
                    "感谢您的消息，我会尽快回复。",
                    "Hello! I'm currently offline, will reply later.",
                    "谢谢您的消息！"
                ]
                self.signals.log.emit(f"⚠️ {phone} 使用默认自动回复，共 {len(replies)} 条")
            else:
                self.signals.log.emit(f"✅ {phone} 加载到 {len(replies)} 条自动回复")
        
            reply_message = random.choice(replies)
        
            self.signals.log.emit(f"📝 {phone} 选择的回复内容: {reply_message}")
        
            await client.send_message(sender, reply_message)
        
            sender_name = self.get_user_display_name(sender)
            self.signals.log.emit(f"✅ {phone} 已向 {sender_name} 发送自动回复")
        
        except Exception as e:
            self.signals.log.emit(f"❌ {phone} 发送自动回复失败: {str(e)}")
            import traceback
            self.signals.log.emit(f"详细错误: {traceback.format_exc()}")

    async def send_bot_notification(self, phone, message_data):
        """发送机器人通知"""
        try:
            # 加载机器人配置
            bot_configs = self.main_window.load_resource_file('通知机器人.txt')
            if not bot_configs:
                return
            
            # 构造通知消息
            notification = f"""📩 新的陌生人消息
账号: {phone}
发送者: {message_data['sender_name']}
用户名: @{message_data['sender_username']}
手机号: {message_data['sender_phone']}
时间: {message_data['timestamp']}
内容: {message_data['message']}"""
            
            # 发送到配置的机器人
            for bot_config in bot_configs:
                if ':' in bot_config:
                    parts = bot_config.split(':', 2)
                    if len(parts) >= 2:
                        bot_token = parts[0].strip()
                        chat_id = parts[1].strip()
                        await self.send_telegram_bot_message(bot_token, chat_id, notification)
                    
        except Exception as e:
            self.signals.log.emit(f"{phone} 发送机器人通知失败: {str(e)}")

    async def send_telegram_bot_message(self, bot_token, chat_id, message):
        """通过Telegram Bot发送消息"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                data = {
                    'chat_id': chat_id,
                    'text': message
                }
                async with session.post(url, data=data) as response:
                    if response.status == 200:
                        self.signals.log.emit("机器人通知发送成功")
                    else:
                        self.signals.log.emit(f"机器人通知发送失败: {response.status}")
        except Exception as e:
            self.signals.log.emit(f"机器人通知发送错误: {str(e)}")

    async def stop_stranger_message_monitor(self, phone):
        """停止陌生人消息监听 - 增强版"""
        self.signals.log.emit(f"🛑 正在停止 {phone} 的陌生人消息监听...")
    
        client = self.clients.get(phone)
        if not client:
            self.signals.log.emit(f"⚠️ {phone} 客户端不存在")
            return False
        
        try:
            # 移除事件处理器
            if phone in self.message_handlers:
                client.remove_event_handler(self.message_handlers[phone])
                del self.message_handlers[phone]
                self.signals.log.emit(f"🗑️ {phone} 事件处理器已移除")
        
            # 从监听列表中移除
            if phone in self.monitoring_phones:
                self.monitoring_phones.remove(phone)
            
            self.signals.log.emit(f"✅ {phone} 陌生人消息监听已停止")
            return True
        
        except Exception as e:
            self.signals.log.emit(f"❌ {phone} 停止监听失败: {str(e)}")
            return False
    def get_user_display_name(self, user):
        """获取用户显示名称"""
        first_name = getattr(user, 'first_name', '') or ''
        last_name = getattr(user, 'last_name', '') or ''
        display_name = f"{first_name} {last_name}".strip()
        if not display_name:
            display_name = getattr(user, 'username', '') or f"用户{user.id}"
        return display_name

    async def is_contact_enhanced(self, client, user):
        """增强的联系人检查"""
        try:
            self.signals.log.emit(f"🔍 检查用户 {user.id} 是否为联系人...")
        
            # 获取联系人列表
            contacts = await client.get_contacts()
            self.signals.log.emit(f"📋 获取到 {len(contacts)} 个联系人")
        
            for contact in contacts:
                if contact.id == user.id:
                    self.signals.log.emit(f"✅ 用户 {user.id} 是联系人")
                    return True
        
            self.signals.log.emit(f"❌ 用户 {user.id} 不是联系人")
            return False
        
        except Exception as e:
            self.signals.log.emit(f"⚠️ 检查联系人时出错: {str(e)}")
            # 出错时假设是陌生人
            return False

    async def send_bot_notification_enhanced(self, phone, message_data):
        """增强的机器人通知 - 修复配置解析"""
        try:
            self.signals.log.emit(f"🔔 {phone} 准备发送机器人通知...")
    
            # 加载机器人配置
            bot_configs = self.main_window.load_resource_file('通知机器人.txt')
            if not bot_configs:
                self.signals.log.emit(f"⚠️ {phone} 没有配置通知机器人")
                return
    
            self.signals.log.emit(f"📋 {phone} 加载到 {len(bot_configs)} 个机器人配置")
    
            # 构造通知消息
            notification = f"""📩 新的陌生人消息

🔸 账号: {phone}
🔸 发送者: {message_data['sender_name']}
🔸 用户名: @{message_data['sender_username']}
🔸 手机号: {message_data['sender_phone']}
🔸 时间: {message_data['timestamp']}
🔸 内容: {message_data['message']}

━━━━━━━━━━━━━━━━━━━━━━"""
        
            # 发送到所有配置的机器人
            for i, bot_config in enumerate(bot_configs):
                try:
                    self.signals.log.emit(f"🔍 {phone} 解析机器人配置 {i+1}: {bot_config}")
                
                    # 配置格式: BOT_ID:BOT_TOKEN:CHAT_ID
                    # 例如: 7389460907:AAFrDBQlbyo-Cd2j-dnQIOAtaBiNYudZepM:-1002691176217
                    if ':' in bot_config:
                        parts = bot_config.split(':')
                        if len(parts) >= 3:
                            # 前两部分组成完整的bot token
                            bot_token = f"{parts[0].strip()}:{parts[1].strip()}"
                            chat_id = parts[2].strip()
                        elif len(parts) == 2:
                            # 兼容简单格式 TOKEN:CHAT_ID
                            bot_token = parts[0].strip()
                            chat_id = parts[1].strip()
                        else:
                            self.signals.log.emit(f"⚠️ {phone} 机器人配置格式错误: {bot_config}")
                            continue
                    
                        # 验证配置格式
                        if not bot_token or not chat_id:
                            self.signals.log.emit(f"⚠️ {phone} 机器人配置格式错误: token或chat_id为空")
                            continue
                    
                        # 验证chat_id格式（应该是数字或以-开头的数字）
                        if not (chat_id.isdigit() or (chat_id.startswith('-') and chat_id[1:].isdigit())):
                            self.signals.log.emit(f"⚠️ {phone} chat_id格式可能不正确: {chat_id}")
                    
                        self.signals.log.emit(f"📤 {phone} 正在通过机器人发送通知...")
                        self.signals.log.emit(f"   Token: {bot_token[:10]}...")
                        self.signals.log.emit(f"   Chat ID: {chat_id}")
                    
                        success = await self.send_telegram_bot_message_enhanced(bot_token, chat_id, notification)
                    
                        if success:
                            self.signals.log.emit(f"✅ {phone} 机器人通知 {i+1} 发送成功")
                        else:
                            self.signals.log.emit(f"❌ {phone} 机器人通知 {i+1} 发送失败")
                    else:
                        self.signals.log.emit(f"⚠️ {phone} 机器人配置格式错误（没有冒号）: {bot_config}")
                
                except Exception as e:
                    self.signals.log.emit(f"❌ {phone} 处理机器人配置 {i+1} 时异常: {str(e)}")
                
        except Exception as e:
            self.signals.log.emit(f"❌ {phone} 发送机器人通知失败: {str(e)}")

    async def send_telegram_bot_message_enhanced(self, bot_token, chat_id, message):
        """增强的Telegram Bot消息发送 - 增加更多调试信息"""
        try:
            self.signals.log.emit(f"🌐 准备发送Bot消息到 {chat_id}")
    
            import aiohttp
            import asyncio
    
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': message
            }
    
            self.signals.log.emit(f"📡 发送请求到: {url}")
    
            # 设置超时
            timeout = aiohttp.ClientTimeout(total=30)  # 增加超时时间
    
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=data) as response:
                    response_text = await response.text()
                    self.signals.log.emit(f"📥 Bot API响应状态: {response.status}")
                    self.signals.log.emit(f"📥 Bot API响应内容: {response_text[:200]}...")
            
                    if response.status == 200:
                        try:
                            result = await response.json()
                            if result.get('ok'):
                                self.signals.log.emit(f"✅ Bot消息发送成功")
                                return True
                            else:
                                error_desc = result.get('description', '未知错误')
                                self.signals.log.emit(f"❌ Bot API返回错误: {error_desc}")
                                return False
                        except Exception as json_error:
                            self.signals.log.emit(f"❌ 解析JSON响应失败: {str(json_error)}")
                            return False
                    else:
                        self.signals.log.emit(f"❌ HTTP错误 {response.status}: {response_text}")
                        return False
                
        except asyncio.TimeoutError:
            self.signals.log.emit(f"⏰ Bot消息发送超时")
            return False
        except Exception as e:
            self.signals.log.emit(f"❌ Bot消息发送异常: {str(e)}")
            import traceback
            self.signals.log.emit(f"详细错误: {traceback.format_exc()}")
            return False
        
    async def update_profile(self, phone, profile_data):
        """更新账号资料"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        try:
            updated_info = {}
            
            # 更新名字和姓氏
            if 'first_name' in profile_data or 'last_name' in profile_data:
                first_name = profile_data.get('first_name', '')
                last_name = profile_data.get('last_name', '')
                
                # 处理删除情况 - 真正删除资料而不是设置为空字符串
                if first_name == "删除":
                    first_name = ""
                    self.signals.log.emit(f"{phone} 删除名字")
                if last_name == "删除":
                    last_name = ""
                    self.signals.log.emit(f"{phone} 删除姓氏")
                
                # 获取当前用户信息，如果只修改其中一个字段，保持另一个字段不变
                me = await client.get_me()
                current_first_name = me.first_name or ""
                current_last_name = me.last_name or ""
                
                # 如果没有指定要修改的字段，保持原值
                if 'first_name' not in profile_data:
                    first_name = current_first_name
                if 'last_name' not in profile_data:
                    last_name = current_last_name
                
                # 更新名字和姓氏
                await client(UpdateProfileRequest(
                    first_name=first_name,
                    last_name=last_name
                ))
                
                updated_info['first_name'] = first_name
                updated_info['last_name'] = last_name
                
                if profile_data.get('first_name') == "删除":
                    self.signals.log.emit(f"{phone} 成功删除名字")
                elif 'first_name' in profile_data:
                    self.signals.log.emit(f"{phone} 更新名字成功: {first_name}")
                    
                if profile_data.get('last_name') == "删除":
                    self.signals.log.emit(f"{phone} 成功删除姓氏")
                elif 'last_name' in profile_data:
                    self.signals.log.emit(f"{phone} 更新姓氏成功: {last_name}")
            
            # 更新简介
            if 'bio' in profile_data:
                bio = profile_data.get('bio', '')
                if bio == "删除":
                    bio = ""
                    self.signals.log.emit(f"{phone} 删除简介")
                
                await client(UpdateProfileRequest(about=bio))
                updated_info['bio'] = bio
                
                if profile_data.get('bio') == "删除":
                    self.signals.log.emit(f"{phone} 成功删除简介")
                else:
                    self.signals.log.emit(f"{phone} 更新简介成功")
            
            # 更新用户名 - 用户名不支持删除功能，只能设置为空
            if 'username' in profile_data:
                username = profile_data.get('username', '')
                if username == "删除":
                    username = ""
                    self.signals.log.emit(f"{phone} 清空用户名")
                
                await client(UpdateUsernameRequest(username=username))
                updated_info['username'] = username
                
                if profile_data.get('username') == "删除":
                    self.signals.log.emit(f"{phone} 成功清空用户名")
                else:
                    self.signals.log.emit(f"{phone} 更新用户名成功: {username}")
            
            # 更新头像
            if 'avatar' in profile_data:
                avatar_path = profile_data.get('avatar')
                if avatar_path and Path(avatar_path).exists():
                    # 先删除旧头像
                    photos = await client.get_profile_photos('me')
                    if photos:
                        await client(DeletePhotosRequest([photos[0]]))
                    
                    # 上传新头像
                    file = await client.upload_file(avatar_path)
                    await client(UploadProfilePhotoRequest(file=file))
                    self.signals.log.emit(f"{phone} 更新头像成功")
            
            # 发送资料更新信号
            self.signals.profile_updated.emit(phone, updated_info)
            
            return True
            
        except FloodWaitError as e:
            self.signals.log.emit(f"{phone} 操作太频繁，需等待 {e.seconds} 秒")
            return False
        except Exception as e:
            # 检测资料更新时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 更新资料时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 更新资料失败: {str(e)}")
            return False
        
    async def change_two_factor_password(self, phone, old_password, new_password):
        """更改二次验证密码 - 简化可靠版本"""
        import traceback
        
        client = await self.ensure_client_connected(phone)
        if not client:
            self.signals.log.emit(f"{phone} 客户端连接失败")
            return False
        
        try:
            self.signals.log.emit(f"{phone} 开始更改二次验证密码...")
            
            # 方法1: 尝试使用Telethon的高级API
            try:
                if hasattr(client, 'edit_2fa'):
                    self.signals.log.emit(f"{phone} 使用Telethon高级API方法...")
                    result = await client.edit_2fa(
                        current_password=old_password,
                        new_password=new_password,
                        hint=f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                    )
                    self.signals.log.emit(f"{phone} ✅ 密码更改成功")
                    return True
                else:
                    self.signals.log.emit(f"{phone} edit_2fa方法不可用，尝试其他方法...")
            except Exception as edit_error:
                error_msg = str(edit_error)
                self.signals.log.emit(f"{phone} edit_2fa失败: {error_msg}")
                
                # 分析错误类型
                if "PASSWORD_HASH_INVALID" in error_msg:
                    self.signals.log.emit(f"{phone} ❌ 当前密码错误，请检查输入")
                    return False
                elif "PASSWORD_TOO_FRESH" in error_msg:
                    self.signals.log.emit(f"{phone} ❌ 密码修改太频繁，请稍后再试")
                    return False
                elif "FLOOD_WAIT" in error_msg:
                    self.signals.log.emit(f"{phone} ❌ 操作限制，请稍后再试")
                    return False
                # 如果是其他错误，继续尝试下一种方法
            
            # 方法2: 尝试使用原始API但动态导入
            try:
                self.signals.log.emit(f"{phone} 尝试使用原始API方法...")
                
                from telethon.tl.functions.account import UpdatePasswordSettingsRequest, GetPasswordRequest
                
                # 动态查找PasswordInputSettings
                PasswordInputSettings = None
                
                # 尝试多种导入路径
                import_attempts = [
                    ('telethon.tl.types', 'PasswordInputSettings'),
                    ('telethon.tl.types.account', 'PasswordInputSettings'),
                    ('telethon.types', 'PasswordInputSettings'),
                    ('telethon', 'types.PasswordInputSettings'),
                ]
                
                for module_path, class_name in import_attempts:
                    try:
                        if '.' in class_name:
                            # 处理嵌套属性
                            module = __import__(module_path, fromlist=[''])
                            parts = class_name.split('.')
                            PasswordInputSettings = module
                            for part in parts:
                                PasswordInputSettings = getattr(PasswordInputSettings, part)
                        else:
                            module = __import__(module_path, fromlist=[class_name])
                            PasswordInputSettings = getattr(module, class_name)
                        
                        self.signals.log.emit(f"{phone} 成功导入PasswordInputSettings from {module_path}")
                        break
                    except:
                        continue
                
                if PasswordInputSettings is None:
                    self.signals.log.emit(f"{phone} ❌ 无法找到PasswordInputSettings类")
                    raise ImportError("PasswordInputSettings not found")
                
                # 获取密码信息
                password_info = await client(GetPasswordRequest())
                
                if not password_info.has_password:
                    self.signals.log.emit(f"{phone} ❌ 账号未设置二次验证密码")
                    return False
                
                # 使用简化的哈希计算
                import hashlib
                
                current_algo = password_info.current_algo
                
                if hasattr(current_algo, 'salt1') and hasattr(current_algo, 'salt2'):
                    salt1 = current_algo.salt1
                    salt2 = current_algo.salt2
                    
                    # 计算当前密码哈希
                    pwd_bytes = old_password.encode('utf-8')
                    hash1 = hashlib.sha256(salt1 + pwd_bytes + salt1).digest()
                    current_hash = hashlib.sha256(salt2 + hash1 + salt2).digest()
                    
                    # 计算新密码哈希
                    new_pwd_bytes = new_password.encode('utf-8')
                    new_hash1 = hashlib.sha256(salt1 + new_pwd_bytes + salt1).digest()
                    new_hash = hashlib.sha256(salt2 + new_hash1 + salt2).digest()
                    
                    # 创建新密码设置
                    new_settings = PasswordInputSettings(
                        new_password_hash=new_hash,
                        hint=f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        email=''
                    )
                    
                    # 执行密码更改
                    result = await client(UpdatePasswordSettingsRequest(
                        current_password_hash=current_hash,
                        new_settings=new_settings
                    ))
                    
                    self.signals.log.emit(f"{phone} ✅ 原始API密码更改成功")
                    return True
                
                else:
                    self.signals.log.emit(f"{phone} ❌ 无法获取密码算法参数")
                    return False
                
            except Exception as api_error:
                error_msg = str(api_error)
                self.signals.log.emit(f"{phone} 原始API方法失败: {error_msg}")
                
                if "PASSWORD_HASH_INVALID" in error_msg:
                    self.signals.log.emit(f"{phone} ❌ 密码错误")
                    return False
            
            # 方法3: 建议用户手动操作
            self.signals.log.emit(f"{phone} ❌ 所有自动方法都失败")
            self.signals.log.emit(f"{phone} 建议解决方案:")
            self.signals.log.emit(f"  1. 升级Telethon版本: pip install --upgrade telethon")
            self.signals.log.emit(f"  2. 使用官方Telegram客户端手动更改密码")
            self.signals.log.emit(f"  3. 检查当前Telethon版本: pip show telethon")
            
            return False
            
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            self.signals.log.emit(f"{phone} ❌ 严重错误: {error_type}")
            self.signals.log.emit(f"{phone} 错误详情: {error_msg}")
            self.signals.log.emit(f"{phone} 完整堆栈: {traceback.format_exc()}")
            
            # 检测账号状态异常
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 账号状态异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            
            return False

    def extract_flood_wait_time(self, error_msg):
        """从错误信息中提取等待时间"""
        import re
        patterns = [
            r'FLOOD_WAIT_(\d+)',
            r'wait (\d+) second',
            r'(\d+) second',
            r'(\d+)s',
            r'(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_msg, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return "未知"

    async def terminate_other_sessions(self, phone):
        """踢出其他设备"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
    
        try:
            from telethon.tl.functions.auth import ResetAuthorizationsRequest
        
            # 获取所有活跃会话
            authorizations = await client(functions.account.GetAuthorizationsRequest())
        
            active_sessions = len(authorizations.authorizations)
            self.signals.log.emit(f"{phone} 当前有 {active_sessions} 个活跃会话")
        
            if active_sessions <= 1:
                self.signals.log.emit(f"{phone} 只有当前会话，无需踢出其他设备")
                return True
        
            # 终止所有其他会话（保留当前会话）
            await client(ResetAuthorizationsRequest())
        
            self.signals.log.emit(f"{phone} 已踢出所有其他设备，共 {active_sessions - 1} 个会话被终止")
            return True
        
        except Exception as e:
            self.signals.log.emit(f"{phone} 踢出其他设备失败: {str(e)}")
            return False

    async def get_active_sessions(self, phone):
        """获取活跃会话信息"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return []
    
        try:
            authorizations = await client(functions.account.GetAuthorizationsRequest())
        
            sessions = []
            for auth in authorizations.authorizations:
                session_info = {
                    'hash': auth.hash,
                    'device_model': getattr(auth, 'device_model', '未知设备'),
                    'platform': getattr(auth, 'platform', '未知平台'),
                    'system_version': getattr(auth, 'system_version', '未知版本'),
                    'api_id': getattr(auth, 'api_id', 0),
                    'app_name': getattr(auth, 'app_name', '未知应用'),
                    'app_version': getattr(auth, 'app_version', '未知版本'),
                    'date_created': getattr(auth, 'date_created', None),
                    'date_active': getattr(auth, 'date_active', None),
                    'country': getattr(auth, 'country', '未知'),
                    'region': getattr(auth, 'region', '未知'),
                    'current': getattr(auth, 'current', False)
                }
                sessions.append(session_info)
        
            self.signals.log.emit(f"{phone} 获取到 {len(sessions)} 个活跃会话")
            return sessions
        
        except Exception as e:
            self.signals.log.emit(f"{phone} 获取会话信息失败: {str(e)}")
            return []    
    
    async def join_group(self, phone, group_link):
        """加入群组"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        
        try:
            # 解析群组链接
            group_entity = None
            if 'joinchat/' in group_link or '/+' in group_link:
                # 私有群组邀请链接
                if 'joinchat/' in group_link:
                    hash_id = group_link.split('joinchat/')[-1]
                else:  # /+ 格式
                    hash_id = group_link.split('/+')[-1]
                
                result = await client(functions.messages.ImportChatInviteRequest(hash_id))
                group_entity = result.chats[0]
            else:
                # 公开群组
                username = group_link.split('/')[-1]
                if username.startswith('@'):
                    username = username[1:]
                result = await client(JoinChannelRequest(username))
                group_entity = result.chats[0]
            
            # 记录群组信息
            if group_entity:
                if phone not in self.account_groups:
                    self.account_groups[phone] = {}
                
                self.account_groups[phone][str(group_entity.id)] = {
                    'title': group_entity.title,
                    'id': group_entity.id,
                    'link': group_link,
                    'is_channel': hasattr(group_entity, 'broadcast') and group_entity.broadcast,
                    'join_time': datetime.now().isoformat()
                }
                
                self.save_group_records()
            
            self.signals.log.emit(f"{phone} 成功加入群组: {group_link}")
            return True
            
        except FloodWaitError as e:
            self.signals.log.emit(f"{phone} 操作太频繁，需等待 {e.seconds} 秒")
            await asyncio.sleep(e.seconds)
            return False
        except Exception as e:
            # 检测加群时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 加群时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 加群失败: {str(e)}")
            return False
    
    async def get_recorded_groups_status(self, phone):
        """获取记录群组的当前状态"""
        if phone not in self.account_groups:
            return []
        
        client = await self.ensure_client_connected(phone)
        if not client:
            return []
        
        groups_status = []
        
        for group_id, group_info in self.account_groups[phone].items():
            # 只处理群组，不包括频道
            if group_info.get('is_channel', False):
                continue
                
            group_status = {
                'id': int(group_id),
                'title': group_info['title'],
                'link': group_info.get('link', ''),
                'join_time': group_info.get('join_time', ''),
                'phone': phone,
                'status': '未知',
                'is_muted': False,
                'entity': None
            }
            
            try:
                # 尝试获取群组实体
                group_entity = await client.get_entity(int(group_id))
                group_status['entity'] = group_entity
                group_status['title'] = group_entity.title  # 更新最新的群名
                
                # 检查是否被禁言
                is_muted = await self.check_if_muted(client, group_entity)
                group_status['is_muted'] = is_muted
                group_status['status'] = '正常'
                
                # 更新记录中的群名（可能有变化）
                self.account_groups[phone][group_id]['title'] = group_entity.title
                
            except Exception as e:
                # 群组不存在或已退出/被踢
                if "No such peer" in str(e) or "USER_NOT_PARTICIPANT" in str(e):
                    group_status['status'] = '已退出'
                    self.signals.log.emit(f"{phone} 已退出群组: {group_info['title']}")
                elif "CHANNEL_PRIVATE" in str(e):
                    group_status['status'] = '群组私有'
                else:
                    group_status['status'] = '连接失败'
                    self.signals.log.emit(f"{phone} 检测群组失败 {group_info['title']}: {str(e)}")
            
            groups_status.append(group_status)
        
        return groups_status
    
    async def get_recorded_groups_for_broadcast(self, phone):
        """获取记录的群组用于群发（只返回状态正常的群组）"""
        if phone not in self.account_groups:
            return []
        
        client = await self.ensure_client_connected(phone)
        if not client:
            return []
        
        available_groups = []
        
        for group_id, group_info in self.account_groups[phone].items():
            # 只处理群组，不包括频道
            if group_info.get('is_channel', False):
                continue
                
            try:
                # 尝试获取群组实体
                group_entity = await client.get_entity(int(group_id))
                
                # 检查是否被禁言
                is_muted = await self.check_if_muted(client, group_entity)
                
                available_groups.append({
                    'id': int(group_id),
                    'title': group_entity.title,
                    'entity': group_entity,
                    'is_muted': is_muted
                })
                
            except Exception as e:
                # 群组不存在或已退出，跳过
                continue
        
        return available_groups
    
    async def get_groups_only(self, phone):
        """获取已加入的群组（仅群组，不包括频道）"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return []
        
        groups = []
        
        try:
            dialogs = await client.get_dialogs()
            
            for dialog in dialogs:
                # 只获取群组，不包括频道
                if dialog.is_group and not dialog.is_channel:
                    # 检查是否被禁言
                    is_muted = await self.check_if_muted(client, dialog.entity)
                    
                    groups.append({
                        'id': dialog.id,
                        'title': dialog.title,
                        'entity': dialog.entity,
                        'is_muted': is_muted
                    })
                    
                    # 更新群组记录
                    if phone not in self.account_groups:
                        self.account_groups[phone] = {}
                    
                    self.account_groups[phone][str(dialog.id)] = {
                        'title': dialog.title,
                        'id': dialog.id,
                        'link': '',
                        'is_channel': False,
                        'join_time': datetime.now().isoformat()
                    }
            
            self.save_group_records()
            self.signals.log.emit(f"{phone} 获取到 {len(groups)} 个群组")
            return groups
            
        except Exception as e:
            # 检测获取群组时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 获取群组时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"获取群组列表失败: {str(e)}")
            return []
    
    async def leave_all_groups(self, phone):
        """退出所有群组（不包括频道）- 只退出记录中的群组"""
        client = await self.ensure_client_connected(phone)
        if not client:
            self.signals.log.emit(f"{phone} 客户端连接失败")
            return False
    
        try:
            self.signals.log.emit(f"{phone} 开始退出记录中的群组...")
        
            # 检查是否有群组记录
            if phone not in self.account_groups or not self.account_groups[phone]:
                self.signals.log.emit(f"{phone} 没有找到群组记录")
                return True
        
            # 获取记录中的群组（不包括频道）
            recorded_groups = []
            for group_id_str, group_info in self.account_groups[phone].items():
                # 跳过频道记录
                if group_info.get('is_channel', False):
                    continue
            
                recorded_groups.append({
                    'id': int(group_id_str),
                    'title': group_info.get('title', f'群组{group_id_str}'),
                    'group_info': group_info
                })
        
            self.signals.log.emit(f"{phone} 找到 {len(recorded_groups)} 个需要退出的群组记录")
        
            if not recorded_groups:
                self.signals.log.emit(f"{phone} 记录中没有群组（只有频道），无需退出")
                return True
        
            left_count = 0
            failed_count = 0
        
            self.signals.log.emit(f"{phone} 开始逐个退出记录中的群组...")
        
            for i, group in enumerate(recorded_groups):
                try:
                    self.signals.log.emit(f"{phone} 正在退出群组 {i+1}/{len(recorded_groups)}: {group['title']} (ID: {group['id']})")
                
                    # 尝试获取群组实体
                    try:
                        entity = await client.get_entity(group['id'])
                    except Exception as get_entity_error:
                        # 无法获取实体，可能群组已不存在或用户已被踢出
                        self.signals.log.emit(f"{phone} ⚠️ 无法获取群组实体: {str(get_entity_error)}")
                    
                        # 直接删除记录
                        group_id_str = str(group['id'])
                        if group_id_str in self.account_groups[phone]:
                            del self.account_groups[phone][group_id_str]
                            self.signals.log.emit(f"{phone} 📝 已删除无效群组记录: {group['title']}")
                    
                        left_count += 1  # 算作成功处理
                        continue
                
                    # 检查群组类型并使用对应的退出方法
                    group_type = ""
                
                    if hasattr(entity, 'megagroup') and entity.megagroup:
                        # 超级群组 - 使用 LeaveChannelRequest
                        group_type = "超级群组"
                        await client(LeaveChannelRequest(entity))
                    elif hasattr(entity, 'broadcast') and entity.broadcast:
                        # 频道 - 跳过（理论上不应该出现在这里）
                        group_type = "频道"
                        self.signals.log.emit(f"{phone} 跳过频道: {group['title']}")
                        continue
                    else:
                        # 普通群组 - 尝试多种方法
                        group_type = "普通群组"
                    
                        # 方法1: 尝试使用 LeaveChannelRequest
                        try:
                            await client(LeaveChannelRequest(entity))
                            self.signals.log.emit(f"{phone} 使用 LeaveChannelRequest 成功")
                        except Exception as e1:
                            self.signals.log.emit(f"{phone} LeaveChannelRequest 失败: {str(e1)}")
                        
                            # 方法2: 尝试通过删除自己来退出群组
                            try:
                                from telethon.tl.functions.channels import EditBannedRequest
                                from telethon.tl.types import ChatBannedRights
                            
                                me = await client.get_me()
                                await client(EditBannedRequest(
                                    entity,
                                    me,
                                    ChatBannedRights(
                                        until_date=None,
                                        view_messages=True,
                                        send_messages=True,
                                        send_media=True
                                    )
                                ))
                                self.signals.log.emit(f"{phone} 使用 EditBannedRequest 成功")
                            except Exception as e2:
                                self.signals.log.emit(f"{phone} EditBannedRequest 也失败: {str(e2)}")
                            
                                # 方法3: 尝试使用 client.delete_dialog
                                try:
                                    await client.delete_dialog(entity)
                                    self.signals.log.emit(f"{phone} 使用 delete_dialog 成功")
                                except Exception as e3:
                                    self.signals.log.emit(f"{phone} delete_dialog 也失败: {str(e3)}")
                                    raise Exception(f"所有退出方法都失败: {str(e1)}, {str(e2)}, {str(e3)}")
                
                    left_count += 1
                    self.signals.log.emit(f"{phone} ✅ 成功退出{group_type}: {group['title']} (ID: {group['id']})")
                
                    # 从群组记录中删除
                    group_id_str = str(group['id'])
                    if group_id_str in self.account_groups[phone]:
                        del self.account_groups[phone][group_id_str]
                        self.signals.log.emit(f"{phone} 📝 已删除群组记录: {group['title']}")
                
                    # 退群间隔，避免操作过于频繁
                    if i < len(recorded_groups) - 1:  # 不是最后一个时才等待
                        self.signals.log.emit(f"{phone} 等待8秒后继续...")
                        await asyncio.sleep(8)
                
                except Exception as e:
                    failed_count += 1
                    error_msg = str(e)
                    self.signals.log.emit(f"{phone} ❌ 退出群组时出错 {group['title']}: {error_msg}")
                
                    # 检查是否是特定的错误（比如已经不在群组中）
                    if "USER_NOT_PARTICIPANT" in error_msg:
                        # 用户已经不在群组中，删除记录
                        group_id_str = str(group['id'])
                        if group_id_str in self.account_groups[phone]:
                            del self.account_groups[phone][group_id_str]
                            self.signals.log.emit(f"{phone} 📝 已删除群组记录（用户不在群组中）: {group['title']}")
                        self.signals.log.emit(f"{phone} ℹ️ 群组 {group['title']} - 用户已不在群组中")
                        left_count += 1  # 算作成功处理
                        failed_count -= 1  # 减少失败计数
                    elif "CHAT_ADMIN_REQUIRED" in error_msg:
                        self.signals.log.emit(f"{phone} ⚠️ 退出群组失败 {group['title']}: 需要管理员权限")
                    elif "PEER_ID_INVALID" in error_msg:
                        # 群组ID无效，删除记录
                        group_id_str = str(group['id'])
                        if group_id_str in self.account_groups[phone]:
                            del self.account_groups[phone][group_id_str]
                            self.signals.log.emit(f"{phone} 📝 已删除无效群组记录: {group['title']}")
                        self.signals.log.emit(f"{phone} ℹ️ 群组 {group['title']} - 群组ID无效")
                        left_count += 1  # 算作成功处理
                        failed_count -= 1  # 减少失败计数
                    elif "FLOOD_WAIT" in error_msg:
                        # 被限流，需要等待
                        import re
                        wait_time = re.search(r'(\d+)', error_msg)
                        if wait_time:
                            wait_seconds = int(wait_time.group(1))
                            self.signals.log.emit(f"{phone} ⏰ 被限流，需要等待 {wait_seconds} 秒")
                            await asyncio.sleep(wait_seconds)
                            # 重试退出
                            try:
                                entity = await client.get_entity(group['id'])
                                await client(LeaveChannelRequest(entity))
                                left_count += 1
                                failed_count -= 1  # 减少失败计数
                                self.signals.log.emit(f"{phone} ✅ 重试成功退出群组: {group['title']}")
                                group_id_str = str(group['id'])
                                if group_id_str in self.account_groups[phone]:
                                    del self.account_groups[phone][group_id_str]
                                    self.signals.log.emit(f"{phone} 📝 已删除群组记录: {group['title']}")
                            except Exception as retry_e:
                                self.signals.log.emit(f"{phone} ❌ 重试仍然失败: {str(retry_e)}")
                    else:
                        self.signals.log.emit(f"{phone} ❌ 未知错误退出群组失败 {group['title']}: {error_msg}")
        
            # 保存更新后的群组记录
            self.save_group_records()
        
            self.signals.log.emit(f"{phone} 🎉 退出群组任务完成 - 成功处理: {left_count}个, 失败: {failed_count}个")
        
            # 验证记录清理结果
            remaining_group_records = []
            if phone in self.account_groups:
                for group_id_str, group_info in self.account_groups[phone].items():
                    if not group_info.get('is_channel', False):
                        remaining_group_records.append(group_info.get('title', group_id_str))
        
            if remaining_group_records:
                self.signals.log.emit(f"{phone} ⚠️ 仍有 {len(remaining_group_records)} 个群组记录未清理: {', '.join(remaining_group_records)}")
            else:
                self.signals.log.emit(f"{phone} ✅ 所有群组记录已清理完成")
        
            return True
        
        except Exception as e:
            # 检测退群时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 退群时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 退出群组失败: {str(e)}")
            return False
    
    async def check_if_muted(self, client, group):
        """检查是否被禁言"""
        try:
            # 获取自己在群组中的权限
            me = await client.get_me()
            participant = await client(GetParticipantRequest(
                channel=group,
                participant=me.id
            ))
            
            if hasattr(participant.participant, 'banned_rights'):
                banned_rights = participant.participant.banned_rights
                if banned_rights and banned_rights.send_messages:
                    return True
            
            return False
            
        except:
            return False
    
    async def try_unmute(self, phone, group):
        """尝试解除禁言"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        
        try:
            # 获取群组的消息，查找解除禁言按钮
            messages = await client.get_messages(group, limit=10)
            
            for message in messages:
                if message.buttons:
                    for row in message.buttons:
                        for button in row:
                            if '解除禁言' in button.text or 'unmute' in button.text.lower():
                                # 点击按钮
                                await button.click()
                                self.signals.log.emit(f"{phone} 尝试解除禁言: {group.title}")
                                return True
            
            return False
            
        except Exception as e:
            # 检测解禁时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 解禁时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"解除禁言失败: {str(e)}")
            return False
    
    async def send_message_to_group(self, phone, group, message):
        """发送群消息"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        
        try:
            # 检查是否被禁言
            if await self.check_if_muted(client, group):
                self.signals.log.emit(f"{phone} 在群组 {group.title} 被禁言，跳过")
                return False
            
            await client.send_message(group, message)
            self.signals.log.emit(f"{phone} 发送消息到群组: {group.title}")
            return True
            
        except FloodWaitError as e:
            self.signals.log.emit(f"{phone} 发送太频繁，需等待 {e.seconds} 秒")
            await asyncio.sleep(e.seconds)
            return False
        except Exception as e:
            # 检测发送消息时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 发送消息时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 发送消息失败: {str(e)}")
            return False
    
    async def add_contact(self, phone, contact_info):
        """添加联系人"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        
        try:
            # 根据用户名或手机号添加
            if contact_info.startswith('+') or contact_info.isdigit():
                # 手机号
                if not contact_info.startswith('+'):
                    contact_info = '+' + contact_info
                    
                result = await client(ImportContactsRequest(
                    contacts=[InputPhoneContact(
                        client_id=random.randint(0, 999999),
                        phone=contact_info,
                        first_name='Contact',
                        last_name=''
                    )]
                ))
                
                if result.users:
                    self.signals.log.emit(f"{phone} 添加联系人成功: {contact_info}")
                    return True
                else:
                    self.signals.log.emit(f"{phone} 添加联系人失败，号码可能无效: {contact_info}")
                    return False
            else:
                # 用户名
                if not contact_info.startswith('@'):
                    contact_info = '@' + contact_info
                    
                user = await client.get_entity(contact_info)
                await client(AddContactRequest(
                    id=user,
                    first_name=user.first_name or 'Contact',
                    last_name=user.last_name or '',
                    phone=''
                ))
                
                self.signals.log.emit(f"{phone} 添加联系人成功: {contact_info}")
                return True
            
        except Exception as e:
            # 检测添加联系人时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 添加联系人时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 添加联系人失败 {contact_info}: {str(e)}")
            return False
    
    async def send_message_to_contact(self, phone, contact, message):
        """发送消息给联系人"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        
        try:
            # 获取联系人实体
            if contact.startswith('+') or contact.isdigit():
                if not contact.startswith('+'):
                    contact = '+' + contact
            elif not contact.startswith('@'):
                contact = '@' + contact
                
            entity = await client.get_entity(contact)
            #标记消息为已读
            try:
                await client.send_read_acknowledge(entity)
                self.signals.log.emit(f"📖 {phone} 已读与 {contact} 的对话")
            except Exception as read_error:
                self.signals.log.emit(f"⚠️ {phone} 标记已读失败 {contact}: {str(read_error)}")
            await client.send_message(entity, message)
            self.signals.log.emit(f"{phone} 发送消息给联系人: {contact}")
            return True
            
        except Exception as e:
            # 检测发送消息时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 发送联系人消息时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 发送消息失败 {contact}: {str(e)}")
            return False
    
    async def create_channel(self, phone, channel_data, admins=None, bots=None, add_admins=True, add_bots=True):
        """创建频道"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        
        try:
            name = channel_data.get('name', '频道')
            description = channel_data.get('description', '')
            username = channel_data.get('username', '')
            
            # 创建频道
            result = await client(CreateChannelRequest(
                title=name,
                about=description,
                megagroup=False,  # False表示频道，True表示超级群组
                broadcast=True
            ))
            
            channel = result.chats[0]
            self.signals.log.emit(f"{phone} 创建频道成功: {name}")
            
            # 设置用户名（如果提供）
            if username:
                try:
                    await client(functions.channels.UpdateUsernameRequest(
                        channel=channel,
                        username=username
                    ))
                    self.signals.log.emit(f"{phone} 设置频道用户名成功: @{username}")
                except Exception as e:
                    self.signals.log.emit(f"{phone} 设置频道用户名失败: {str(e)}")
            
            # 上传频道头像
            avatar_dir = Path('resources/频道头像')
            if avatar_dir.exists():
                avatars = list(avatar_dir.glob('*.*'))
                if avatars:
                    avatar_path = random.choice(avatars)
                    try:
                        file = await client.upload_file(str(avatar_path))
                        await client(functions.channels.EditPhotoRequest(
                            channel=channel,
                            photo=file
                        ))
                        self.signals.log.emit(f"{phone} 上传频道头像成功")
                    except Exception as e:
                        self.signals.log.emit(f"{phone} 上传频道头像失败: {str(e)}")
            
            # 添加管理员
            if add_admins and admins:
                for admin in admins:
                    try:
                        if not admin.startswith('@'):
                            admin = '@' + admin
                        
                        user = await client.get_entity(admin)
                        await client(EditAdminRequest(
                            channel=channel,
                            user_id=user,
                            admin_rights=ChatAdminRights(
                                change_info=True,
                                post_messages=True,
                                edit_messages=True,
                                delete_messages=True,
                                ban_users=True,
                                invite_users=True,
                                pin_messages=True,
                                add_admins=False
                            ),
                            rank='管理员'
                        ))
                        self.signals.log.emit(f"{phone} 添加管理员成功: {admin}")
                    except Exception as e:
                        self.signals.log.emit(f"{phone} 添加管理员失败 {admin}: {str(e)}")
            
            # 添加机器人管理员
            if add_bots and bots:
                for bot in bots:
                    try:
                        if not bot.startswith('@'):
                            bot = '@' + bot
                        
                        bot_user = await client.get_entity(bot)
                        await client(EditAdminRequest(
                            channel=channel,
                            user_id=bot_user,
                            admin_rights=ChatAdminRights(
                                change_info=True,
                                post_messages=True,
                                edit_messages=True,
                                delete_messages=True,
                                ban_users=True,
                                invite_users=True,
                                pin_messages=True,
                                add_admins=False
                            ),
                            rank='机器人管理员'
                        ))
                        self.signals.log.emit(f"{phone} 添加机器人管理员成功: {bot}")
                    except Exception as e:
                        self.signals.log.emit(f"{phone} 添加机器人管理员失败 {bot}: {str(e)}")
            
            return True
            
        except Exception as e:
            # 检测创建频道时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 创建频道时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 创建频道失败: {str(e)}")
            return False
    
    async def create_channels(self, phone, count, interval, channel_data_list, admins, bots, add_admins, add_bots):
        """批量创建频道"""
        self.init_stop_flags(phone)
        
        try:
            account_list = list(self.main_window.accounts.keys())
            if phone not in account_list:
                return
                
            account_index = account_list.index(phone)
            
            if account_index >= len(channel_data_list):
                return
            
            account_data = channel_data_list[account_index]
            
            for i in range(min(count, len(account_data))):
                if self.stop_flags[phone].get('create_channel', False):
                    break
                
                channel_data = account_data[i]
                success = await self.create_channel(phone, channel_data, admins, bots, add_admins, add_bots)
                
                if success:
                    self.signals.log.emit(f"{phone} 创建第 {i+1} 个频道完成")
                
                # 等待间隔
                if i < count - 1 and not self.stop_flags[phone].get('create_channel', False):
                    await asyncio.sleep(interval)
                    
        except Exception as e:
            # 检测批量创建频道时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 批量创建频道时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 创建频道任务出错: {str(e)}")
    
    async def run_contact_message_task(self, phone, interval, round_interval, messages):
        """运行联系人消息任务"""
        self.init_stop_flags(phone)
        
        contacts = self.main_window.load_resource_file('联系人.txt')
        if not contacts:
            return
        
        while not self.stop_flags[phone].get('contact_message', False):
            for contact in contacts:
                if self.stop_flags[phone].get('contact_message', False):
                    break
                
                message = random.choice(messages)
                success = await self.send_message_to_contact(phone, contact, message)
                
                # 如果账号状态异常，停止任务
                if not success:
                    account = self.main_window.accounts.get(phone, {})
                    status = account.get('status', '')
                    if status in ['已停用', '已封禁', '号码被禁', '授权失效', '未授权', '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', '账号受限', '操作过于频繁']:
                        self.signals.log.emit(f"{phone} 账号状态异常，停止联系人消息任务")
                        self.stop_flags[phone]['contact_message'] = True
                        break
                
                if not self.stop_flags[phone].get('contact_message', False):
                    await asyncio.sleep(interval)
            
            if not self.stop_flags[phone].get('contact_message', False):
                self.signals.log.emit(f"{phone} 联系人消息轮次完成，等待 {round_interval} 秒")
                await asyncio.sleep(round_interval)
    
    async def run_broadcast_task(self, phone, interval, round_interval):
        """运行群发任务 - 使用记录的群组"""
        self.init_stop_flags(phone)
        
        messages = self.main_window.load_resource_file('群发消息.txt')
        if not messages:
            return
        
        while not self.stop_flags[phone].get('broadcast', False):
            message = random.choice(messages)
            # 使用记录的群组进行群发
            recorded_groups = await self.get_recorded_groups_for_broadcast(phone)
            
            if not recorded_groups:
                self.signals.log.emit(f"{phone} 没有可用的群组进行群发")
                break
            
            for group in recorded_groups:
                if self.stop_flags[phone].get('broadcast', False):
                    break
                
                success = await self.send_message_to_group(phone, group['entity'], message)
                
                # 如果账号状态异常，停止任务
                if not success:
                    account = self.main_window.accounts.get(phone, {})
                    status = account.get('status', '')
                    if status in ['已停用', '已封禁', '号码被禁', '授权失效', '未授权', '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', '账号受限', '操作过于频繁']:
                        self.signals.log.emit(f"{phone} 账号状态异常，停止群发任务")
                        self.stop_flags[phone]['broadcast'] = True
                        break
                
                if not self.stop_flags[phone].get('broadcast', False):
                    await asyncio.sleep(interval)
            
            if not self.stop_flags[phone].get('broadcast', False):
                self.signals.log.emit(f"{phone} 群发轮次完成，等待 {round_interval} 秒")
                await asyncio.sleep(round_interval)
    
    async def run_unmute_task(self, phone, interval, round_interval):
        """运行解禁任务 - 使用记录的群组"""
        self.init_stop_flags(phone)
        
        while not self.stop_flags[phone].get('unmute', False):
            # 使用记录的群组进行解禁检测
            recorded_groups = await self.get_recorded_groups_for_broadcast(phone)
            
            if not recorded_groups:
                self.signals.log.emit(f"{phone} 没有可用的群组进行解禁检测")
                break
            
            for group in recorded_groups:
                if self.stop_flags[phone].get('unmute', False):
                    break
                
                if group.get('is_muted', False):
                    success = await self.try_unmute(phone, group['entity'])
                    
                    # 如果账号状态异常，停止任务
                    if not success:
                        account = self.main_window.accounts.get(phone, {})
                        status = account.get('status', '')
                        if status in ['已停用', '已封禁', '号码被禁', '授权失效', '未授权', '会话撤销', 'SpamBot检测到账号被封禁', '频道封禁', '账号受限', '操作过于频繁']:
                            self.signals.log.emit(f"{phone} 账号状态异常，停止解禁任务")
                            self.stop_flags[phone]['unmute'] = True
                            break
                
                if not self.stop_flags[phone].get('unmute', False):
                    await asyncio.sleep(interval)
            
            if not self.stop_flags[phone].get('unmute', False):
                self.signals.log.emit(f"{phone} 解禁轮次完成，等待 {round_interval} 秒")
                await asyncio.sleep(round_interval)
    
    async def clean_invalid_groups(self, phone):
        """清理无效的群组记录"""
        if phone not in self.account_groups:
            return
        
        client = await self.ensure_client_connected(phone)
        if not client:
            return
        
        invalid_groups = []
        
        for group_id, group_info in self.account_groups[phone].items():
            # 只检查群组，不检查频道
            if group_info.get('is_channel', False):
                continue
                
            try:
                await client.get_entity(int(group_id))
            except Exception as e:
                if "No such peer" in str(e) or "USER_NOT_PARTICIPANT" in str(e):
                    invalid_groups.append(group_id)
                    self.signals.log.emit(f"{phone} 标记无效群组: {group_info['title']}")
        
        # 移除无效群组
        for group_id in invalid_groups:
            del self.account_groups[phone][group_id]
        
        if invalid_groups:
            self.save_group_records()
            self.signals.log.emit(f"{phone} 清理了 {len(invalid_groups)} 个无效群组记录")

    # 在 telegram_async_handler.py 中更新隐私设置方法：
    async def set_privacy_settings(self, phone, privacy_settings):
        """设置隐私设置 - 修复版"""
        client = await self.ensure_client_connected(phone)
        if not client:
            self.signals.log.emit(f"{phone} 客户端连接失败")
            return False
        
        try:
            # 导入隐私设置相关的模块
            from telethon.tl.functions.account import SetPrivacyRequest
            from telethon.tl.types import (
                InputPrivacyKeyPhoneNumber, InputPrivacyKeyStatusTimestamp,
                InputPrivacyValueAllowAll, InputPrivacyValueAllowContacts, InputPrivacyValueDisallowAll
            )
            
            self.signals.log.emit(f"{phone} 开始设置隐私...")
            
            # 映射隐私级别到Telegram类型 - 使用正确的Input类型
            privacy_mapping = {
                0: InputPrivacyValueAllowAll(),
                1: InputPrivacyValueAllowContacts(),
                2: InputPrivacyValueDisallowAll()
            }
            
            # 隐私设置配置 - 使用正确的Input类型
            privacy_configs = [
                (InputPrivacyKeyPhoneNumber(), privacy_settings.get('phone_privacy', 2), "手机号码"),
                (InputPrivacyKeyStatusTimestamp(), privacy_settings.get('lastseen_privacy', 2), "最后上线时间")
            ]
            
            success_count = 0
            
            for privacy_key, privacy_level, privacy_name in privacy_configs:
                try:
                    self.signals.log.emit(f"{phone} 正在设置{privacy_name}隐私...")
                    
                    # 确保privacy_level有效
                    if privacy_level not in privacy_mapping:
                        self.signals.log.emit(f"{phone} 无效的隐私级别: {privacy_level}，使用默认值2")
                        privacy_level = 2
                    
                    privacy_rule = privacy_mapping[privacy_level]
                    
                    # 调用Telegram API设置隐私
                    await client(SetPrivacyRequest(
                        key=privacy_key,
                        rules=[privacy_rule]
                    ))
                    
                    level_names = ["所有人可见", "仅联系人可见", "任何人都不可见"]
                    self.signals.log.emit(f"{phone} {privacy_name}隐私设置成功: {level_names[privacy_level]}")
                    success_count += 1
                    
                    # 设置间隔
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    self.signals.log.emit(f"{phone} 设置{privacy_name}隐私失败: {str(e)}")
                    continue
            
            if success_count > 0:
                self.signals.log.emit(f"{phone} 隐私设置完成，成功设置 {success_count}/{len(privacy_configs)} 项")
                return True
            else:
                self.signals.log.emit(f"{phone} 所有隐私设置都失败")
                return False
                
        except Exception as e:
            self.signals.log.emit(f"{phone} 设置隐私时发生错误: {str(e)}")
            return False
    async def refresh_account_profile(self, phone):
        """刷新账号资料"""
        client = await self.ensure_client_connected(phone)
        if not client:
            return False
        
        try:
            # 获取最新的用户信息
            me = await client.get_me()
            self.signals.log.emit(f"{phone} 获取最新用户信息: {me.first_name} {me.last_name} @{me.username}")
            
            # 构建用户信息
            user_info = {
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'username': me.username or '',
                'user_id': str(me.id)
            }
            
            # 发送资料更新信号
            self.signals.profile_updated.emit(phone, user_info)
            
            # 同时发送账号状态更新（包含完整信息）
            account = self.main_window.accounts.get(phone, {})
            account_info = {
                'api_id': account.get('api_id', ''),
                'api_hash': account.get('api_hash', ''),
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'username': me.username or '',
                'phone': phone,
                'user_id': str(me.id),
                'status': '在线'
            }
            
            self.signals.update_account_status.emit(phone, account_info)
            
            self.signals.log.emit(f"{phone} 资料刷新完成")
            return True
            
        except Exception as e:
            # 检测获取资料时的账号状态
            if self.is_account_banned_or_frozen(e):
                status = self.get_account_status_from_error(e)
                self.signals.log.emit(f"{phone} 获取资料时发现账号异常: {status}")
                self.signals.update_account_status.emit(phone, {'status': status})
            else:
                self.signals.log.emit(f"{phone} 获取资料失败: {str(e)}")
            return False
    async def stop_single_task(self, phone, task_type):
        """停止单个账号的特定任务"""
        self.init_stop_flags(phone)
        self.stop_flags[phone][task_type] = True
        
        task_key = f"{phone}_{task_type}"
        if task_key in self.running_tasks:
            del self.running_tasks[task_key]
            
        self.signals.log.emit(f"停止任务: {phone} - {task_type}")
    
    def stop_task(self, task_name):
        """停止指定任务的所有账号"""
        for phone in self.stop_flags:
            if task_name in self.stop_flags[phone]:
                self.stop_flags[phone][task_name] = True
        
        self.signals.log.emit(f"正在停止任务: {task_name}")
    
    def stop_account_task(self, phone, task_name):
        """停止指定账号的指定任务"""
        self.init_stop_flags(phone)
        self.stop_flags[phone][task_name] = True
        self.signals.log.emit(f"正在停止任务: {phone} - {task_name}")
    
    async def stop_all_tasks(self):
        """停止所有任务"""
        for phone in self.stop_flags:
            for task in self.stop_flags[phone]:
                self.stop_flags[phone][task] = True
        
        # 断开所有客户端连接
        for phone, client in self.clients.items():
            try:
                await client.disconnect()
            except:
                pass
        
        # 断开临时客户端
        for phone, client in self.temp_clients.items():
            try:
                await client.disconnect()
            except:
                pass
        
        self.clients.clear()
        self.temp_clients.clear()
        self.signals.log.emit("所有任务已停止")
        
    def extract_flood_wait_time(self, error_msg):
        """从错误信息中提取等待时间"""
        import re
        match = re.search(r'(\d+)', error_msg)
        return match.group(1) if match else "未知"
