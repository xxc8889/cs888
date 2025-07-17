import PyInstaller.__main__
import os
import shutil
from pathlib import Path

def build_app():
    """构建应用程序"""
    
    # 清理之前的构建
    if os.path.exists('build'):
        shutil.rmtree('build')
    if os.path.exists('dist'):
        shutil.rmtree('dist')
    
    # PyInstaller 参数
    args = [
        'telegram_manager.py',  # 主程序
        '--name=TelegramManager',  # 输出名称
        '--onedir',  # 打包成文件夹
        '--windowed',  # Windows下不显示控制台
        '--icon=logo.ico',  # 图标
        '--add-data=logo.ico;.',  # 包含图标文件
        '--add-binary=logo.ico;.',  # 确保图标文件可访问
        '--hidden-import=telethon',
        '--hidden-import=cryptg',
        '--hidden-import=PyQt6',
        '--hidden-import=config_manager',
        '--hidden-import=telegram_async_handler',
        '--collect-all=telethon',
        '--collect-all=cryptg',
        '--clean',  # 清理临时文件
    ]
    
    # 运行 PyInstaller
    PyInstaller.__main__.run(args)
    
    # 创建必要的文件夹结构
    dist_path = Path('dist/TelegramManager')
    
    # 复制图标文件到输出目录
    if os.path.exists('logo.ico'):
        shutil.copy2('logo.ico', dist_path / 'logo.ico')
        print("已复制logo.ico到输出目录")

    # 创建文件夹
    folders = [
        'sessions',
        'sessions/ok',
        'sessions/error',
        'backup',
        'logs',
        'resources',
        'resources/头像'
    ]
    
    for folder in folders:
        (dist_path / folder).mkdir(parents=True, exist_ok=True)
    
    # 创建示例资源文件
    resource_files = {
        'resources/名字.txt': '# 每行一个名字\n',
        'resources/姓氏.txt': '# 每行一个姓氏\n',
        'resources/简介.txt': '# 每行一个简介\n',
        'resources/用户名.txt': '# 每行一个用户名\n',
        'resources/群组.txt': '# 每行一个群组链接\n# 例如: https://t.me/example\n',
        'resources/联系人.txt': '# 每行一个联系人（手机号或用户名）\n',
        'resources/联系人消息.txt': '# 每行一条消息\n',
        'resources/群发消息.txt': '# 每行一条群发消息\n',
        'resources/API配置.txt': '# 每两行一组配置\n# 第一行: API_ID\n# 第二行: API_HASH\n'
    }
    
    for file_path, content in resource_files.items():
        with open(dist_path / file_path, 'w', encoding='utf-8') as f:
            f.write(content)

    print("打包完成！")
    print(f"输出目录: {dist_path}")
    
    # 压缩成zip文件（可选）
    try:
        shutil.make_archive('TelegramManager', 'zip', 'dist/TelegramManager')
        print("已创建压缩包: TelegramManager.zip")
    except:
        print("创建压缩包失败，请手动压缩 dist/TelegramManager 文件夹")

if __name__ == '__main__':
    build_app()