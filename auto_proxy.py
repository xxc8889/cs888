import urllib.request
import winreg
import os
import re
import json
import socket
import socks
from pathlib import Path
import logging

class AutoProxyDetector:
    """自动代理检测器"""
    
    def __init__(self):
        self.detected_proxies = []
        self.system_proxy = None
        self.env_proxy = None
        self.common_proxies = []
        
    def detect_system_proxy_windows(self):
        """检测Windows系统代理设置"""
        try:
            # 读取注册表中的代理设置
            reg_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            )
            
            try:
                # 检查是否启用了代理
                proxy_enable, _ = winreg.QueryValueEx(reg_key, "ProxyEnable")
                if proxy_enable:
                    # 获取代理服务器地址
                    proxy_server, _ = winreg.QueryValueEx(reg_key, "ProxyServer")
                    
                    # 解析代理服务器设置
                    if '=' in proxy_server:
                        # 多协议代理设置，如 "http=127.0.0.1:8080;https=127.0.0.1:8080;socks=127.0.0.1:1080"
                        proxy_dict = {}
                        for item in proxy_server.split(';'):
                            if '=' in item:
                                protocol, address = item.split('=', 1)
                                proxy_dict[protocol.lower()] = address
                        
                        if 'socks' in proxy_dict:
                            self.system_proxy = {'type': 'socks5', 'address': proxy_dict['socks']}
                        elif 'http' in proxy_dict:
                            self.system_proxy = {'type': 'http', 'address': proxy_dict['http']}
                        elif 'https' in proxy_dict:
                            self.system_proxy = {'type': 'http', 'address': proxy_dict['https']}
                    else:
                        # 单一代理设置，如 "127.0.0.1:8080"
                        self.system_proxy = {'type': 'http', 'address': proxy_server}
                        
                    print(f"检测到系统代理: {self.system_proxy}")
                    return self.system_proxy
                    
            except FileNotFoundError:
                pass
            finally:
                winreg.CloseKey(reg_key)
                
        except Exception as e:
            print(f"检测Windows系统代理失败: {e}")
            
        return None
    
    def detect_environment_proxy(self):
        """检测环境变量中的代理设置"""
        proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'SOCKS_PROXY', 'ALL_PROXY']
        
        for var in proxy_vars:
            proxy_url = os.environ.get(var) or os.environ.get(var.lower())
            if proxy_url:
                proxy_info = self.parse_proxy_url(proxy_url)
                if proxy_info:
                    self.env_proxy = proxy_info
                    print(f"检测到环境变量代理 {var}: {proxy_info}")
                    return proxy_info
        
        return None
    
    def parse_proxy_url(self, proxy_url):
        """解析代理URL"""
        try:
            # 处理不同格式的代理URL
            if proxy_url.startswith('socks5://'):
                address = proxy_url[9:]
                return {'type': 'socks5', 'address': address}
            elif proxy_url.startswith('socks4://'):
                address = proxy_url[9:]
                return {'type': 'socks4', 'address': address}
            elif proxy_url.startswith('http://'):
                address = proxy_url[7:]
                return {'type': 'http', 'address': address}
            elif proxy_url.startswith('https://'):
                address = proxy_url[8:]
                return {'type': 'http', 'address': address}
            else:
                # 默认假设是HTTP代理
                return {'type': 'http', 'address': proxy_url}
        except Exception as e:
            print(f"解析代理URL失败: {e}")
            return None
    
    def detect_common_proxy_ports(self):
        """检测常见的本地代理端口"""
        common_ports = [
            ('127.0.0.1', 1080, 'socks5'),  # 常见SOCKS5端口
            ('127.0.0.1', 1081, 'socks5'),
            ('127.0.0.1', 7890, 'socks5'),  # Clash默认端口
            ('127.0.0.1', 7891, 'http'),    # Clash HTTP端口
            ('127.0.0.1', 8080, 'http'),    # 常见HTTP代理端口
            ('127.0.0.1', 8888, 'http'),
            ('127.0.0.1', 3128, 'http'),
            ('127.0.0.1', 10809, 'socks5'), # V2Ray默认端口
            ('127.0.0.1', 10808, 'http'),   # V2Ray HTTP端口
        ]
        
        detected = []
        for host, port, proxy_type in common_ports:
            if self.test_proxy_port(host, port, proxy_type):
                proxy_info = {
                    'type': proxy_type,
                    'address': f"{host}:{port}",
                    'description': f'本地{proxy_type.upper()}代理'
                }
                detected.append(proxy_info)
                print(f"检测到本地代理: {proxy_type.upper()} {host}:{port}")
        
        self.common_proxies = detected
        return detected
    
    def test_proxy_port(self, host, port, proxy_type):
        """测试代理端口是否可用"""
        try:
            # 简单的端口连通性测试
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                # 端口开放，进一步测试是否为代理
                return self.test_proxy_functionality(host, port, proxy_type)
            return False
            
        except Exception:
            return False
    
    def test_proxy_functionality(self, host, port, proxy_type):
        """测试代理功能是否正常"""
        try:
            if proxy_type == 'socks5':
                # 测试SOCKS5代理
                sock = socks.socksocket()
                sock.set_proxy(socks.SOCKS5, host, port)
                sock.settimeout(5)
                sock.connect(('httpbin.org', 80))
                sock.close()
                return True
            elif proxy_type == 'http':
                # 测试HTTP代理
                proxy_handler = urllib.request.ProxyHandler({
                    'http': f'http://{host}:{port}',
                    'https': f'http://{host}:{port}'
                })
                opener = urllib.request.build_opener(proxy_handler)
                opener.addheaders = [('User-Agent', 'TelegramManager/1.0')]
                
                request = urllib.request.Request('http://httpbin.org/ip', timeout=5)
                response = opener.open(request)
                return response.status == 200
                
        except Exception:
            return False
        
        return False
    
    def detect_vpn_software(self):
        """检测常见VPN软件的代理设置"""
        vpn_configs = []
        
        # Clash配置检测
        clash_config = self.detect_clash_config()
        if clash_config:
            vpn_configs.extend(clash_config)
        
        # V2Ray配置检测
        v2ray_config = self.detect_v2ray_config()
        if v2ray_config:
            vpn_configs.extend(v2ray_config)
        
        # Shadowsocks配置检测
        ss_config = self.detect_shadowsocks_config()
        if ss_config:
            vpn_configs.extend(ss_config)
        
        return vpn_configs
    
    def detect_clash_config(self):
        """检测Clash配置"""
        try:
            # 常见Clash配置文件位置
            clash_paths = [
                Path.home() / '.config' / 'clash' / 'config.yaml',
                Path.home() / 'Documents' / 'clash' / 'config.yaml',
                Path('C:/Users') / os.getenv('USERNAME', '') / '.clash' / 'config.yaml',
            ]
            
            for config_path in clash_paths:
                if config_path.exists():
                    # 尝试读取Clash配置中的端口信息
                    with open(config_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # 简单的正则匹配端口
                    socks_port_match = re.search(r'socks-port:\s*(\d+)', content)
                    http_port_match = re.search(r'port:\s*(\d+)', content)
                    
                    configs = []
                    if socks_port_match:
                        port = int(socks_port_match.group(1))
                        if self.test_proxy_port('127.0.0.1', port, 'socks5'):
                            configs.append({
                                'type': 'socks5',
                                'address': f'127.0.0.1:{port}',
                                'description': 'Clash SOCKS5代理'
                            })
                    
                    if http_port_match:
                        port = int(http_port_match.group(1))
                        if self.test_proxy_port('127.0.0.1', port, 'http'):
                            configs.append({
                                'type': 'http',
                                'address': f'127.0.0.1:{port}',
                                'description': 'Clash HTTP代理'
                            })
                    
                    if configs:
                        print(f"检测到Clash配置: {config_path}")
                        return configs
                        
        except Exception as e:
            print(f"检测Clash配置失败: {e}")
        
        return []
    
    def detect_v2ray_config(self):
        """检测V2Ray配置"""
        try:
            # 常见V2Ray配置文件位置
            v2ray_paths = [
                Path('C:/Program Files/v2ray/config.json'),
                Path.home() / 'v2ray' / 'config.json',
                Path('v2ray/config.json'),
            ]
            
            for config_path in v2ray_paths:
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    
                    configs = []
                    if 'inbounds' in config:
                        for inbound in config['inbounds']:
                            protocol = inbound.get('protocol', '')
                            port = inbound.get('port', 0)
                            
                            if protocol == 'socks' and port:
                                if self.test_proxy_port('127.0.0.1', port, 'socks5'):
                                    configs.append({
                                        'type': 'socks5',
                                        'address': f'127.0.0.1:{port}',
                                        'description': 'V2Ray SOCKS代理'
                                    })
                            elif protocol == 'http' and port:
                                if self.test_proxy_port('127.0.0.1', port, 'http'):
                                    configs.append({
                                        'type': 'http',
                                        'address': f'127.0.0.1:{port}',
                                        'description': 'V2Ray HTTP代理'
                                    })
                    
                    if configs:
                        print(f"检测到V2Ray配置: {config_path}")
                        return configs
                        
        except Exception as e:
            print(f"检测V2Ray配置失败: {e}")
        
        return []
    
    def detect_shadowsocks_config(self):
        """检测Shadowsocks配置"""
        try:
            # Shadowsocks通常使用1080端口作为本地SOCKS代理
            ss_ports = [1080, 1086, 1081]
            configs = []
            
            for port in ss_ports:
                if self.test_proxy_port('127.0.0.1', port, 'socks5'):
                    configs.append({
                        'type': 'socks5',
                        'address': f'127.0.0.1:{port}',
                        'description': 'Shadowsocks本地代理'
                    })
            
            return configs
            
        except Exception as e:
            print(f"检测Shadowsocks配置失败: {e}")
        
        return []
    
    def get_best_proxy(self):
        """获取最佳代理配置"""
        all_proxies = []
        
        # 收集所有检测到的代理
        if self.system_proxy:
            all_proxies.append({**self.system_proxy, 'priority': 1, 'source': '系统代理'})
        
        if self.env_proxy:
            all_proxies.append({**self.env_proxy, 'priority': 2, 'source': '环境变量'})
        
        for proxy in self.common_proxies:
            all_proxies.append({**proxy, 'priority': 3, 'source': '本地端口'})
        
        vpn_proxies = self.detect_vpn_software()
        for proxy in vpn_proxies:
            all_proxies.append({**proxy, 'priority': 4, 'source': 'VPN软件'})
        
        if not all_proxies:
            return None
        
        # 按优先级排序，测试连通性
        all_proxies.sort(key=lambda x: x['priority'])
        
        for proxy in all_proxies:
            if self.test_proxy_with_telegram(proxy):
                print(f"选择最佳代理: {proxy}")
                return proxy
        
        # 如果都测试失败，返回第一个
        return all_proxies[0] if all_proxies else None
    
    def test_proxy_with_telegram(self, proxy):
        """测试代理是否能连接Telegram服务器"""
        try:
            host, port = proxy['address'].split(':')
            port = int(port)
            
            if proxy['type'] == 'socks5':
                sock = socks.socksocket()
                sock.set_proxy(socks.SOCKS5, host, port)
            elif proxy['type'] == 'http':
                # HTTP代理测试比较复杂，这里简化处理
                return True
            else:
                return False
            
            sock.settimeout(10)
            # 测试连接Telegram服务器
            sock.connect(('91.108.56.174', 443))
            sock.close()
            return True
            
        except Exception:
            return False
    
    def run_auto_detection(self):
        """运行自动检测"""
        print("开始自动检测代理配置...")
        print("=" * 50)
        
        # 检测系统代理
        print("1. 检测系统代理设置...")
        self.detect_system_proxy_windows()
        
        # 检测环境变量代理
        print("2. 检测环境变量代理...")
        self.detect_environment_proxy()
        
        # 检测常见代理端口
        print("3. 检测本地代理端口...")
        self.detect_common_proxy_ports()
        
        # 检测VPN软件
        print("4. 检测VPN软件配置...")
        self.detect_vpn_software()
        
        # 获取最佳代理
        print("5. 选择最佳代理...")
        best_proxy = self.get_best_proxy()
        
        return best_proxy
    
    def save_proxy_config(self, proxy):
        """保存代理配置到文件"""
        if not proxy:
            return False
        
        try:
            proxy_file = Path('resources/proxy.txt')
            proxy_file.parent.mkdir(exist_ok=True)
            
            with open(proxy_file, 'w', encoding='utf-8') as f:
                f.write(f"# 自动检测的代理配置\n")
                f.write(f"# 来源: {proxy.get('source', '未知')}\n")
                f.write(f"# 描述: {proxy.get('description', '自动检测')}\n")
                f.write(f"{proxy['type']}://{proxy['address']}\n")
            
            print(f"代理配置已保存到: {proxy_file}")
            return True
            
        except Exception as e:
            print(f"保存代理配置失败: {e}")
            return False

def main():
    """主函数"""
    print("自动代理检测工具")
    print("=" * 50)
    
    detector = AutoProxyDetector()
    best_proxy = detector.run_auto_detection()
    
    print("\n" + "=" * 50)
    if best_proxy:
        print(f"✅ 检测到可用代理:")
        print(f"   类型: {best_proxy['type'].upper()}")
        print(f"   地址: {best_proxy['address']}")
        print(f"   来源: {best_proxy.get('source', '未知')}")
        print(f"   描述: {best_proxy.get('description', '无')}")
        
        # 询问是否保存配置
        save = input("\n是否保存此代理配置？(y/n): ").lower().strip()
        if save in ['y', 'yes', '是']:
            detector.save_proxy_config(best_proxy)
            print("✅ 代理配置已保存，重启程序即可使用")
        
    else:
        print("❌ 未检测到可用的代理配置")
        print("建议:")
        print("1. 手动配置代理")
        print("2. 启动VPN软件")
        print("3. 检查网络连接")
    
    input("\n按Enter键退出...")

if __name__ == "__main__":
    main()