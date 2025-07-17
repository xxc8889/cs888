import random
import hashlib
from pathlib import Path
import json

class DeviceSpoofing:
    """设备伪装类 - 为每个账号生成不同的设备信息"""
    
    def __init__(self):
        self.device_templates = self.load_device_templates()
        self.used_devices = {}  # 记录已使用的设备
        
    def load_device_templates(self):
        """加载设备模板"""
        return {
            'android': [
                # Samsung 设备
                {
                    'device_model': 'Samsung Galaxy S24 Ultra',
                    'system_version': '14',
                    'app_version': '10.14.5',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'Samsung Galaxy S23',
                    'system_version': '13',
                    'app_version': '10.14.3',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'Samsung Galaxy Note20',
                    'system_version': '12',
                    'app_version': '10.13.8',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'Samsung Galaxy A54',
                    'system_version': '13',
                    'app_version': '10.14.2',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'Samsung Galaxy S22',
                    'system_version': '13',
                    'app_version': '10.14.1',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                # Xiaomi 设备
                {
                    'device_model': 'Xiaomi 14 Pro',
                    'system_version': '14',
                    'app_version': '10.14.4',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'Xiaomi 13',
                    'system_version': '13',
                    'app_version': '10.14.0',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'Redmi Note 13 Pro',
                    'system_version': '13',
                    'app_version': '10.13.9',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'POCO F5 Pro',
                    'system_version': '13',
                    'app_version': '10.13.7',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                # OnePlus 设备
                {
                    'device_model': 'OnePlus 12',
                    'system_version': '14',
                    'app_version': '10.14.6',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'OnePlus 11',
                    'system_version': '13',
                    'app_version': '10.14.2',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                # Google Pixel 设备
                {
                    'device_model': 'Pixel 8 Pro',
                    'system_version': '14',
                    'app_version': '10.14.7',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'Pixel 7a',
                    'system_version': '13',
                    'app_version': '10.14.1',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                # Huawei 设备
                {
                    'device_model': 'HUAWEI P60 Pro',
                    'system_version': '13',
                    'app_version': '10.13.8',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'HUAWEI Mate 50',
                    'system_version': '12',
                    'app_version': '10.13.5',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                # OPPO 设备
                {
                    'device_model': 'OPPO Find X6 Pro',
                    'system_version': '13',
                    'app_version': '10.14.0',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'OPPO Reno10 Pro',
                    'system_version': '13',
                    'app_version': '10.13.9',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                # Vivo 设备
                {
                    'device_model': 'vivo X100 Pro',
                    'system_version': '14',
                    'app_version': '10.14.3',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'vivo V29e',
                    'system_version': '13',
                    'app_version': '10.13.8',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                }
            ],
            'ios': [
                {
                    'device_model': 'iPhone 15 Pro Max',
                    'system_version': '17.2.1',
                    'app_version': '10.5.2',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 15 Pro',
                    'system_version': '17.2.0',
                    'app_version': '10.5.1',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 15',
                    'system_version': '17.1.2',
                    'app_version': '10.5.0',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 14 Pro Max',
                    'system_version': '16.7.2',
                    'app_version': '10.4.8',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 14 Pro',
                    'system_version': '16.7.1',
                    'app_version': '10.4.7',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 14',
                    'system_version': '16.6.1',
                    'app_version': '10.4.6',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 13 Pro Max',
                    'system_version': '16.6.0',
                    'app_version': '10.4.5',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 13 Pro',
                    'system_version': '16.5.1',
                    'app_version': '10.4.4',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 13',
                    'system_version': '16.5.0',
                    'app_version': '10.4.3',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 13 mini',
                    'system_version': '16.4.1',
                    'app_version': '10.4.2',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 12 Pro Max',
                    'system_version': '16.4.0',
                    'app_version': '10.4.1',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 12 Pro',
                    'system_version': '16.3.1',
                    'app_version': '10.4.0',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone 12',
                    'system_version': '16.3.0',
                    'app_version': '10.3.9',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPhone SE (3rd generation)',
                    'system_version': '16.2.1',
                    'app_version': '10.3.8',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPad Pro 12.9-inch (6th generation)',
                    'system_version': '17.1.1',
                    'app_version': '10.5.0',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'iPad Air (5th generation)',
                    'system_version': '17.0.3',
                    'app_version': '10.4.9',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                }
            ],
            'desktop': [
                {
                    'device_model': 'GA-EA790X-DS4',
                    'system_version': '10.0.22631',
                    'app_version': '4.16.4',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },
                {
                    'device_model': 'MS-7B86',
                    'system_version': '11.0.22000',
                    'app_version': '4.16.6',
                    'lang_code': 'en',
                    'system_lang_code': 'en'
                },

    {'device_model': 'B360M MORTAR', 'system_version': '10.0.19045', 'app_version': '4.16.8', 'lang_code': 'en', 'system_lang_code': 'en'},
    {'device_model': 'Z370P D3', 'system_version': '10.0.19044', 'app_version': '4.16.7', 'lang_code': 'zh', 'system_lang_code': 'zh-CN'},
    {'device_model': 'ThinkPad X1C 6th', 'system_version': '10.0.19043', 'app_version': '4.16.6', 'lang_code': 'es', 'system_lang_code': 'es'},
    {'device_model': 'XPS 13 9360', 'system_version': '10.0.19042', 'app_version': '4.16.5', 'lang_code': 'fr', 'system_lang_code': 'fr'},
    {'device_model': 'TUF B450M-PLUS', 'system_version': '10.0.19041', 'app_version': '4.16.4', 'lang_code': 'de', 'system_lang_code': 'de'},
    {'device_model': 'B550M PRO-VDH', 'system_version': '10.0.18363', 'app_version': '4.16.3', 'lang_code': 'ru', 'system_lang_code': 'ru'},
    {'device_model': 'Z490-A PRO', 'system_version': '10.0.18362', 'app_version': '4.16.2', 'lang_code': 'pt', 'system_lang_code': 'pt'},
    {'device_model': 'PRIME H310M-E', 'system_version': '10.0.17763', 'app_version': '4.16.1', 'lang_code': 'it', 'system_lang_code': 'it'},
    {'device_model': 'Legion Y7000P', 'system_version': '10.0.17134', 'app_version': '4.16.0', 'lang_code': 'ja', 'system_lang_code': 'ja'},
    {'device_model': 'EliteBook 840 G3', 'system_version': '10.0.16299', 'app_version': '4.15.9', 'lang_code': 'ko', 'system_lang_code': 'ko'},
    {'device_model': 'Inspiron 15-5570', 'system_version': '10.0.15063', 'app_version': '4.15.8', 'lang_code': 'ar', 'system_lang_code': 'ar'},
    {'device_model': 'ProDesk 400 G6', 'system_version': '10.0.14393', 'app_version': '4.15.7', 'lang_code': 'hi', 'system_lang_code': 'hi'},
    {'device_model': 'Aspire E5-575G', 'system_version': '10.0.19045.3803', 'app_version': '4.15.6', 'lang_code': 'tr', 'system_lang_code': 'tr'},
    {'device_model': 'ROG STRIX B550-F', 'system_version': '10.0.19044.3693', 'app_version': '4.15.5', 'lang_code': 'pl', 'system_lang_code': 'pl'},
    {'device_model': 'Predator G3-710', 'system_version': '10.0.19043.3570', 'app_version': '4.15.4', 'lang_code': 'nl', 'system_lang_code': 'nl'},
    {'device_model': 'IdeaPad 320-15IKB', 'system_version': '10.0.19042.3447', 'app_version': '4.15.3', 'lang_code': 'sv', 'system_lang_code': 'sv'},
    {'device_model': 'Latitude 7490', 'system_version': '10.0.19041.3324', 'app_version': '4.15.2', 'lang_code': 'da', 'system_lang_code': 'da'},
    {'device_model': 'ENVY 13-ad1xx', 'system_version': '10.0.18363.3201', 'app_version': '4.15.1', 'lang_code': 'no', 'system_lang_code': 'no'},
    {'device_model': 'Surface Pro 7', 'system_version': '10.0.18362.3078', 'app_version': '4.15.0', 'lang_code': 'fi', 'system_lang_code': 'fi'},
    {'device_model': 'MacBookPro15,2', 'system_version': '10.0.17763.2955', 'app_version': '4.14.9', 'lang_code': 'cs', 'system_lang_code': 'cs'},
    {'device_model': 'VivoBook S14 S4300', 'system_version': '10.0.17134.2832', 'app_version': '4.14.8', 'lang_code': 'hu', 'system_lang_code': 'hu'},
    {'device_model': 'Pavilion 15-cs0xxx', 'system_version': '10.0.16299.2709', 'app_version': '4.14.7', 'lang_code': 'ro', 'system_lang_code': 'ro'},
    {'device_model': 'Z590M-ITX/ax', 'system_version': '10.0.15063.2586', 'app_version': '4.14.6', 'lang_code': 'bg', 'system_lang_code': 'bg'},
    {'device_model': 'B460M DS3H', 'system_version': '10.0.14393.2463', 'app_version': '4.14.5', 'lang_code': 'sk', 'system_lang_code': 'sk'},
    {'device_model': 'H310M-HDV', 'system_version': '10.0.19045.3636', 'app_version': '4.14.4', 'lang_code': 'hr', 'system_lang_code': 'hr'},
    {'device_model': 'X570 AORUS ELITE', 'system_version': '10.0.19044.3513', 'app_version': '4.14.3', 'lang_code': 'sl', 'system_lang_code': 'sl'},
    {'device_model': 'Nitro AN515-54', 'system_version': '10.0.19043.3390', 'app_version': '4.14.2', 'lang_code': 'et', 'system_lang_code': 'et'},
    {'device_model': 'ThinkCentre M720q', 'system_version': '10.0.19042.3267', 'app_version': '4.14.1', 'lang_code': 'lv', 'system_lang_code': 'lv'},
    {'device_model': 'Yoga Slim 7-14IIL', 'system_version': '10.0.19041.3144', 'app_version': '4.14.0', 'lang_code': 'lt', 'system_lang_code': 'lt'},
    {'device_model': 'Swift 3 SF314-57', 'system_version': '10.0.18363.3021', 'app_version': '4.13.9', 'lang_code': 'uk', 'system_lang_code': 'uk'},
    {'device_model': 'MateBook D14', 'system_version': '10.0.18362.2898', 'app_version': '4.13.8', 'lang_code': 'be', 'system_lang_code': 'be'},
    {'device_model': 'MagicBook 14', 'system_version': '10.0.17763.2775', 'app_version': '4.13.7', 'lang_code': 'mk', 'system_lang_code': 'mk'},
    {'device_model': 'Vostro 3471', 'system_version': '10.0.17134.2652', 'app_version': '4.13.6', 'lang_code': 'sq', 'system_lang_code': 'sq'},
    {'device_model': 'ProBook 450 G7', 'system_version': '10.0.16299.2529', 'app_version': '4.13.5', 'lang_code': 'sr', 'system_lang_code': 'sr'},
    {'device_model': 'R7000-2020', 'system_version': '10.0.15063.2406', 'app_version': '4.13.4', 'lang_code': 'bs', 'system_lang_code': 'bs'},
    {'device_model': 'X299 UD4 PRO', 'system_version': '10.0.14393.2283', 'app_version': '4.13.3', 'lang_code': 'mt', 'system_lang_code': 'mt'},
    {'device_model': 'Z390 UD', 'system_version': '10.0.19045.3456', 'app_version': '4.13.2', 'lang_code': 'cy', 'system_lang_code': 'cy'},
    {'device_model': 'B365M D3H', 'system_version': '10.0.19044.3333', 'app_version': '4.13.1', 'lang_code': 'ga', 'system_lang_code': 'ga'},
    {'device_model': 'H410M S2H', 'system_version': '10.0.19043.3210', 'app_version': '4.13.0', 'lang_code': 'eu', 'system_lang_code': 'eu'},
    {'device_model': 'TUF GAMING B560M-PLUS', 'system_version': '10.0.19042.3087', 'app_version': '4.12.9', 'lang_code': 'ca', 'system_lang_code': 'ca'},
    {'device_model': 'ROG MAXIMUS XI HERO', 'system_version': '10.0.19041.2964', 'app_version': '4.12.8', 'lang_code': 'gl', 'system_lang_code': 'gl'},
    {'device_model': 'Z590-A PRO', 'system_version': '10.0.18363.2841', 'app_version': '4.12.7', 'lang_code': 'he', 'system_lang_code': 'he'},
    {'device_model': 'B450M DS3H', 'system_version': '10.0.18362.2718', 'app_version': '4.12.6', 'lang_code': 'th', 'system_lang_code': 'th'},
    {'device_model': 'X470 GAMING PLUS', 'system_version': '10.0.17763.2595', 'app_version': '4.12.5', 'lang_code': 'vi', 'system_lang_code': 'vi'},
    {'device_model': 'H81M-DS2', 'system_version': '10.0.17134.2472', 'app_version': '4.12.4', 'lang_code': 'id', 'system_lang_code': 'id'},
    {'device_model': 'B450M DS3H', 'system_version': '10.0.16299.2349', 'app_version': '4.12.3', 'lang_code': 'ms', 'system_lang_code': 'ms'},
    {'device_model': 'H81M-DS2', 'system_version': '10.0.15063.2226', 'app_version': '4.12.2', 'lang_code': 'tl', 'system_lang_code': 'tl'},
    {'device_model': 'B450M DS3H', 'system_version': '10.0.14393.2103', 'app_version': '4.12.1', 'lang_code': 'bn', 'system_lang_code': 'bn'},
    {'device_model': 'H81M-DS2', 'system_version': '10.0.19045.3276', 'app_version': '4.12.0', 'lang_code': 'ur', 'system_lang_code': 'ur'},
    {'device_model': 'B450M DS3H', 'system_version': '10.0.19044.3153', 'app_version': '4.11.9', 'lang_code': 'fa', 'system_lang_code': 'fa'},
    {'device_model': 'H81M-DS2', 'system_version': '10.0.19043.3030', 'app_version': '4.11.8', 'lang_code': 'ta', 'system_lang_code': 'ta'},
    {'device_model': 'MacBookPro16,1', 'system_version': '14.2.1', 'app_version': '10.5.2', 'lang_code': 'en', 'system_lang_code': 'en'},
    {'device_model': 'MacBookPro15,2', 'system_version': '14.2.0', 'app_version': '10.5.1', 'lang_code': 'zh', 'system_lang_code': 'zh-CN'},
    {'device_model': 'MacBookPro14,3', 'system_version': '14.1.2', 'app_version': '10.5.0', 'lang_code': 'es', 'system_lang_code': 'es'},
    {'device_model': 'MacBookPro13,3', 'system_version': '14.1.1', 'app_version': '10.4.9', 'lang_code': 'fr', 'system_lang_code': 'fr'},
    {'device_model': 'MacBookPro12,1', 'system_version': '14.1.0', 'app_version': '10.4.8', 'lang_code': 'de', 'system_lang_code': 'de'},
    {'device_model': 'MacBookAir10,1', 'system_version': '14.0.1', 'app_version': '10.4.7', 'lang_code': 'ru', 'system_lang_code': 'ru'},
    {'device_model': 'MacBookAir9,1', 'system_version': '14.0.0', 'app_version': '10.4.6', 'lang_code': 'pt', 'system_lang_code': 'pt'},
    {'device_model': 'MacBookAir8,2', 'system_version': '13.6.3', 'app_version': '10.4.5', 'lang_code': 'it', 'system_lang_code': 'it'},
    {'device_model': 'MacBookAir7,2', 'system_version': '13.6.2', 'app_version': '10.4.4', 'lang_code': 'ja', 'system_lang_code': 'ja'},
    {'device_model': 'MacBookAir6,2', 'system_version': '13.6.1', 'app_version': '10.4.3', 'lang_code': 'ko', 'system_lang_code': 'ko'},
    {'device_model': 'iMac21,1', 'system_version': '13.6.0', 'app_version': '10.4.2', 'lang_code': 'ar', 'system_lang_code': 'ar'},
    {'device_model': 'iMac20,2', 'system_version': '13.5.2', 'app_version': '10.4.1', 'lang_code': 'hi', 'system_lang_code': 'hi'},
    {'device_model': 'iMac19,2', 'system_version': '13.5.1', 'app_version': '10.4.0', 'lang_code': 'tr', 'system_lang_code': 'tr'},
    {'device_model': 'iMac18,3', 'system_version': '13.5.0', 'app_version': '10.3.9', 'lang_code': 'pl', 'system_lang_code': 'pl'},
    {'device_model': 'iMac17,1', 'system_version': '13.4.1', 'app_version': '10.3.8', 'lang_code': 'nl', 'system_lang_code': 'nl'},
    {'device_model': 'iMac16,2', 'system_version': '13.4.0', 'app_version': '10.3.7', 'lang_code': 'sv', 'system_lang_code': 'sv'},
    {'device_model': 'iMac15,1', 'system_version': '13.3.1', 'app_version': '10.3.6', 'lang_code': 'da', 'system_lang_code': 'da'},
    {'device_model': 'Macmini9,1', 'system_version': '13.3.0', 'app_version': '10.3.5', 'lang_code': 'no', 'system_lang_code': 'no'},
    {'device_model': 'Macmini8,1', 'system_version': '13.2.1', 'app_version': '10.3.4', 'lang_code': 'fi', 'system_lang_code': 'fi'},
    {'device_model': 'Macmini7,1', 'system_version': '13.2.0', 'app_version': '10.3.3', 'lang_code': 'cs', 'system_lang_code': 'cs'},
    {'device_model': 'MacPro7,1', 'system_version': '13.1.1', 'app_version': '10.3.2', 'lang_code': 'hu', 'system_lang_code': 'hu'},
    {'device_model': 'MacPro6,1', 'system_version': '13.1.0', 'app_version': '10.3.1', 'lang_code': 'ro', 'system_lang_code': 'ro'},
    {'device_model': 'MacPro5,1', 'system_version': '13.0.1', 'app_version': '10.3.0', 'lang_code': 'bg', 'system_lang_code': 'bg'},
    {'device_model': 'MacPro4,1', 'system_version': '13.0.0', 'app_version': '10.2.9', 'lang_code': 'sk', 'system_lang_code': 'sk'},
    {'device_model': 'MacStudio1,1', 'system_version': '12.7.2', 'app_version': '10.2.8', 'lang_code': 'hr', 'system_lang_code': 'hr'},
    {'device_model': 'MacStudio1,2', 'system_version': '12.7.1', 'app_version': '10.2.7', 'lang_code': 'sl', 'system_lang_code': 'sl'},
    {'device_model': 'MacBook10,1', 'system_version': '12.7.0', 'app_version': '10.2.6', 'lang_code': 'et', 'system_lang_code': 'et'},
    {'device_model': 'MacBook9,1', 'system_version': '12.6.9', 'app_version': '10.2.5', 'lang_code': 'lv', 'system_lang_code': 'lv'},
    {'device_model': 'MacBook8,1', 'system_version': '12.6.8', 'app_version': '10.2.4', 'lang_code': 'lt', 'system_lang_code': 'lt'},
    {'device_model': 'MacBook7,1', 'system_version': '12.6.7', 'app_version': '10.2.3', 'lang_code': 'uk', 'system_lang_code': 'uk'},
    {'device_model': 'MacBook6,1', 'system_version': '12.6.6', 'app_version': '10.2.2', 'lang_code': 'be', 'system_lang_code': 'be'},
    {'device_model': 'MacBook5,2', 'system_version': '12.6.5', 'app_version': '10.2.1', 'lang_code': 'mk', 'system_lang_code': 'mk'},
    {'device_model': 'MacBook5,1', 'system_version': '12.6.4', 'app_version': '10.2.0', 'lang_code': 'sq', 'system_lang_code': 'sq'},
    {'device_model': 'MacBook4,1', 'system_version': '12.6.3', 'app_version': '10.1.9', 'lang_code': 'sr', 'system_lang_code': 'sr'},
    {'device_model': 'MacBook3,1', 'system_version': '12.6.2', 'app_version': '10.1.8', 'lang_code': 'bs', 'system_lang_code': 'bs'},
    {'device_model': 'MacBook2,1', 'system_version': '12.6.1', 'app_version': '10.1.7', 'lang_code': 'mt', 'system_lang_code': 'mt'},
    {'device_model': 'MacBook1,1', 'system_version': '12.6.0', 'app_version': '10.1.6', 'lang_code': 'cy', 'system_lang_code': 'cy'},
    {'device_model': 'iMac14,2', 'system_version': '12.5.1', 'app_version': '10.1.5', 'lang_code': 'ga', 'system_lang_code': 'ga'},
    {'device_model': 'iMac13,2', 'system_version': '12.5.0', 'app_version': '10.1.4', 'lang_code': 'eu', 'system_lang_code': 'eu'},
    {'device_model': 'iMac12,1', 'system_version': '12.4.1', 'app_version': '10.1.3', 'lang_code': 'ca', 'system_lang_code': 'ca'},
    {'device_model': 'iMac11,3', 'system_version': '12.4.0', 'app_version': '10.1.2', 'lang_code': 'gl', 'system_lang_code': 'gl'},
    {'device_model': 'iMac10,1', 'system_version': '12.3.1', 'app_version': '10.1.1', 'lang_code': 'he', 'system_lang_code': 'he'},
    {'device_model': 'iMac9,1', 'system_version': '12.3.0', 'app_version': '10.1.0', 'lang_code': 'th', 'system_lang_code': 'th'},
    {'device_model': 'iMac8,1', 'system_version': '12.2.1', 'app_version': '10.0.9', 'lang_code': 'vi', 'system_lang_code': 'vi'},
    {'device_model': 'iMac7,1', 'system_version': '12.2.0', 'app_version': '10.0.8', 'lang_code': 'id', 'system_lang_code': 'id'},
    {'device_model': 'iMac6,1', 'system_version': '12.1.1', 'app_version': '10.0.7', 'lang_code': 'ms', 'system_lang_code': 'ms'},
    {'device_model': 'iMac5,2', 'system_version': '12.1.0', 'app_version': '10.0.6', 'lang_code': 'tl', 'system_lang_code': 'tl'},
    {'device_model': 'iMac4,2', 'system_version': '12.0.1', 'app_version': '10.0.5', 'lang_code': 'bn', 'system_lang_code': 'bn'},
    {'device_model': 'iMac4,1', 'system_version': '12.0.0', 'app_version': '10.0.4', 'lang_code': 'ur', 'system_lang_code': 'ur'},
    {'device_model': 'iMac3,6', 'system_version': '11.7.10', 'app_version': '10.0.3', 'lang_code': 'fa', 'system_lang_code': 'fa'},
    {'device_model': 'iMac3,4', 'system_version': '11.7.9', 'app_version': '10.0.2', 'lang_code': 'ta', 'system_lang_code': 'ta'},
    {'device_model': 'iMac3,2', 'system_version': '11.7.8', 'app_version': '10.0.1', 'lang_code': 'te', 'system_lang_code': 'te'},
    {'device_model': 'iMac3,1', 'system_version': '11.7.7', 'app_version': '10.0.0', 'lang_code': 'ml', 'system_lang_code': 'ml'},
    {'device_model': 'MacBookPro11,5', 'system_version': '11.7.6', 'app_version': '10.0.9', 'lang_code': 'en', 'system_lang_code': 'en'},
    {'device_model': 'MacBookPro10,2', 'system_version': '11.7.5', 'app_version': '10.0.8', 'lang_code': 'zh', 'system_lang_code': 'zh-CN'},
    {'device_model': 'MacBookPro9,2', 'system_version': '11.7.4', 'app_version': '10.0.7', 'lang_code': 'es', 'system_lang_code': 'es'},
    {'device_model': 'MacBookPro8,3', 'system_version': '11.7.3', 'app_version': '10.0.6', 'lang_code': 'fr', 'system_lang_code': 'fr'},
    {'device_model': 'MacBookPro7,1', 'system_version': '11.7.2', 'app_version': '10.0.5', 'lang_code': 'de', 'system_lang_code': 'de'},
    {'device_model': 'MacBookPro6,2', 'system_version': '11.7.1', 'app_version': '10.0.4', 'lang_code': 'ru', 'system_lang_code': 'ru'},
    {'device_model': 'MacBookPro5,5', 'system_version': '11.7.0', 'app_version': '10.0.3', 'lang_code': 'pt', 'system_lang_code': 'pt'},
    {'device_model': 'MacBookPro4,1', 'system_version': '11.6.9', 'app_version': '10.0.2', 'lang_code': 'it', 'system_lang_code': 'it'},
    {'device_model': 'MacBookPro3,1', 'system_version': '11.6.8', 'app_version': '10.0.1', 'lang_code': 'ja', 'system_lang_code': 'ja'},
    {'device_model': 'MacBookPro2,2', 'system_version': '11.6.7', 'app_version': '10.0.0', 'lang_code': 'ko', 'system_lang_code': 'ko'},
    {'device_model': 'MacBookPro1,1', 'system_version': '11.6.6', 'app_version': '10.0.9', 'lang_code': 'ar', 'system_lang_code': 'ar'},
    {'device_model': 'MacBookAir7,1', 'system_version': '11.6.5', 'app_version': '10.0.8', 'lang_code': 'hi', 'system_lang_code': 'hi'},
    {'device_model': 'MacBookAir6,1', 'system_version': '11.6.4', 'app_version': '10.0.7', 'lang_code': 'tr', 'system_lang_code': 'tr'},
    {'device_model': 'MacBookAir5,2', 'system_version': '11.6.3', 'app_version': '10.0.6', 'lang_code': 'pl', 'system_lang_code': 'pl'},
    {'device_model': 'MacBookAir4,2', 'system_version': '11.6.2', 'app_version': '10.0.5', 'lang_code': 'nl', 'system_lang_code': 'nl'},
    {'device_model': 'MacBookAir3,2', 'system_version': '11.6.1', 'app_version': '10.0.4', 'lang_code': 'sv', 'system_lang_code': 'sv'},
    {'device_model': 'MacBookAir2,1', 'system_version': '11.6.0', 'app_version': '10.0.3', 'lang_code': 'da', 'system_lang_code': 'da'},
    {'device_model': 'MacBookAir1,1', 'system_version': '11.5.2', 'app_version': '10.0.2', 'lang_code': 'no', 'system_lang_code': 'no'},
    {'device_model': 'iMac12,2', 'system_version': '11.5.1', 'app_version': '10.0.1', 'lang_code': 'fi', 'system_lang_code': 'fi'},
    {'device_model': 'iMac11,2', 'system_version': '11.5.0', 'app_version': '10.0.0', 'lang_code': 'cs', 'system_lang_code': 'cs'},
    {'device_model': 'iMac10,2', 'system_version': '11.4.9', 'app_version': '10.0.9', 'lang_code': 'hu', 'system_lang_code': 'hu'},
    {'device_model': 'iMac9,2', 'system_version': '11.4.8', 'app_version': '10.0.8', 'lang_code': 'ro', 'system_lang_code': 'ro'},
    {'device_model': 'iMac8,2', 'system_version': '11.4.7', 'app_version': '10.0.7', 'lang_code': 'bg', 'system_lang_code': 'bg'},
    {'device_model': 'iMac7,2', 'system_version': '11.4.6', 'app_version': '10.0.6', 'lang_code': 'sk', 'system_lang_code': 'sk'},
    {'device_model': 'iMac6,2', 'system_version': '11.4.5', 'app_version': '10.0.5', 'lang_code': 'hr', 'system_lang_code': 'hr'},
    {'device_model': 'iMac5,1', 'system_version': '11.4.4', 'app_version': '10.0.4', 'lang_code': 'sl', 'system_lang_code': 'sl'},
    {'device_model': 'iMac4,1', 'system_version': '11.4.3', 'app_version': '10.0.3', 'lang_code': 'et', 'system_lang_code': 'et'},
    {'device_model': 'iMac3,1', 'system_version': '11.4.2', 'app_version': '10.0.2', 'lang_code': 'lv', 'system_lang_code': 'lv'},
    {'device_model': 'iMac2,1', 'system_version': '11.4.1', 'app_version': '10.0.1', 'lang_code': 'lt', 'system_lang_code': 'lt'},
    {'device_model': 'iMac1,1', 'system_version': '11.4.0', 'app_version': '10.0.0', 'lang_code': 'uk', 'system_lang_code': 'uk'},
    {'device_model': 'MacBookPro16,1', 'system_version': '14.2.1', 'app_version': '10.5.2', 'lang_code': 'en', 'system_lang_code': 'en'},
{'device_model': 'MacBookPro15,2', 'system_version': '14.2.0', 'app_version': '10.5.1', 'lang_code': 'zh', 'system_lang_code': 'zh-CN'},
{'device_model': 'MacBookPro14,3', 'system_version': '14.1.2', 'app_version': '10.5.0', 'lang_code': 'es', 'system_lang_code': 'es'},
{'device_model': 'MacBookPro13,3', 'system_version': '14.1.1', 'app_version': '10.4.9', 'lang_code': 'fr', 'system_lang_code': 'fr'},
{'device_model': 'MacBookPro12,1', 'system_version': '14.1.0', 'app_version': '10.4.8', 'lang_code': 'de', 'system_lang_code': 'de'},
{'device_model': 'MacBookAir10,1', 'system_version': '14.0.1', 'app_version': '10.4.7', 'lang_code': 'ru', 'system_lang_code': 'ru'},
{'device_model': 'MacBookAir9,1', 'system_version': '14.0.0', 'app_version': '10.4.6', 'lang_code': 'pt', 'system_lang_code': 'pt'},
{'device_model': 'MacBookAir8,2', 'system_version': '13.6.3', 'app_version': '10.4.5', 'lang_code': 'it', 'system_lang_code': 'it'},
{'device_model': 'MacBookAir7,2', 'system_version': '13.6.2', 'app_version': '10.4.4', 'lang_code': 'ja', 'system_lang_code': 'ja'},
{'device_model': 'MacBookAir6,2', 'system_version': '13.6.1', 'app_version': '10.4.3', 'lang_code': 'ko', 'system_lang_code': 'ko'},
{'device_model': 'iMac21,1', 'system_version': '13.6.0', 'app_version': '10.4.2', 'lang_code': 'ar', 'system_lang_code': 'ar'},
{'device_model': 'iMac20,2', 'system_version': '13.5.2', 'app_version': '10.4.1', 'lang_code': 'hi', 'system_lang_code': 'hi'},
{'device_model': 'iMac19,2', 'system_version': '13.5.1', 'app_version': '10.4.0', 'lang_code': 'tr', 'system_lang_code': 'tr'},
{'device_model': 'iMac18,3', 'system_version': '13.5.0', 'app_version': '10.3.9', 'lang_code': 'pl', 'system_lang_code': 'pl'},
{'device_model': 'iMac17,1', 'system_version': '13.4.1', 'app_version': '10.3.8', 'lang_code': 'nl', 'system_lang_code': 'nl'},
{'device_model': 'iMac16,2', 'system_version': '13.4.0', 'app_version': '10.3.7', 'lang_code': 'sv', 'system_lang_code': 'sv'},
{'device_model': 'iMac15,1', 'system_version': '13.3.1', 'app_version': '10.3.6', 'lang_code': 'da', 'system_lang_code': 'da'},
{'device_model': 'Macmini9,1', 'system_version': '13.3.0', 'app_version': '10.3.5', 'lang_code': 'no', 'system_lang_code': 'no'},
{'device_model': 'Macmini8,1', 'system_version': '13.2.1', 'app_version': '10.3.4', 'lang_code': 'fi', 'system_lang_code': 'fi'},
{'device_model': 'Macmini7,1', 'system_version': '13.2.0', 'app_version': '10.3.3', 'lang_code': 'cs', 'system_lang_code': 'cs'},
{'device_model': 'MacPro7,1', 'system_version': '13.1.1', 'app_version': '10.3.2', 'lang_code': 'hu', 'system_lang_code': 'hu'},
{'device_model': 'MacPro6,1', 'system_version': '13.1.0', 'app_version': '10.3.1', 'lang_code': 'ro', 'system_lang_code': 'ro'},
{'device_model': 'MacPro5,1', 'system_version': '13.0.1', 'app_version': '10.3.0', 'lang_code': 'bg', 'system_lang_code': 'bg'},
{'device_model': 'MacPro4,1', 'system_version': '13.0.0', 'app_version': '10.2.9', 'lang_code': 'sk', 'system_lang_code': 'sk'},
{'device_model': 'MacStudio1,1', 'system_version': '12.7.2', 'app_version': '10.2.8', 'lang_code': 'hr', 'system_lang_code': 'hr'},
{'device_model': 'MacStudio1,2', 'system_version': '12.7.1', 'app_version': '10.2.7', 'lang_code': 'sl', 'system_lang_code': 'sl'},
{'device_model': 'MacBook10,1', 'system_version': '12.7.0', 'app_version': '10.2.6', 'lang_code': 'et', 'system_lang_code': 'et'},
{'device_model': 'MacBook9,1', 'system_version': '12.6.9', 'app_version': '10.2.5', 'lang_code': 'lv', 'system_lang_code': 'lv'},
{'device_model': 'MacBook8,1', 'system_version': '12.6.8', 'app_version': '10.2.4', 'lang_code': 'lt', 'system_lang_code': 'lt'},
{'device_model': 'MacBook7,1', 'system_version': '12.6.7', 'app_version': '10.2.3', 'lang_code': 'uk', 'system_lang_code': 'uk'},
{'device_model': 'MacBook6,1', 'system_version': '12.6.6', 'app_version': '10.2.2', 'lang_code': 'be', 'system_lang_code': 'be'},
{'device_model': 'MacBook5,2', 'system_version': '12.6.5', 'app_version': '10.2.1', 'lang_code': 'mk', 'system_lang_code': 'mk'},
{'device_model': 'MacBook5,1', 'system_version': '12.6.4', 'app_version': '10.2.0', 'lang_code': 'sq', 'system_lang_code': 'sq'},
{'device_model': 'MacBook4,1', 'system_version': '12.6.3', 'app_version': '10.1.9', 'lang_code': 'sr', 'system_lang_code': 'sr'},
{'device_model': 'MacBook3,1', 'system_version': '12.6.2', 'app_version': '10.1.8', 'lang_code': 'bs', 'system_lang_code': 'bs'},
{'device_model': 'MacBook2,1', 'system_version': '12.6.1', 'app_version': '10.1.7', 'lang_code': 'mt', 'system_lang_code': 'mt'},
{'device_model': 'MacBook1,1', 'system_version': '12.6.0', 'app_version': '10.1.6', 'lang_code': 'cy', 'system_lang_code': 'cy'},
{'device_model': 'iMac14,2', 'system_version': '12.5.1', 'app_version': '10.1.5', 'lang_code': 'ga', 'system_lang_code': 'ga'},
{'device_model': 'iMac13,2', 'system_version': '12.5.0', 'app_version': '10.1.4', 'lang_code': 'eu', 'system_lang_code': 'eu'},
{'device_model': 'iMac12,1', 'system_version': '12.4.1', 'app_version': '10.1.3', 'lang_code': 'ca', 'system_lang_code': 'ca'},
{'device_model': 'iMac11,3', 'system_version': '12.4.0', 'app_version': '10.1.2', 'lang_code': 'gl', 'system_lang_code': 'gl'},
{'device_model': 'iMac10,1', 'system_version': '12.3.1', 'app_version': '10.1.1', 'lang_code': 'he', 'system_lang_code': 'he'},
{'device_model': 'iMac9,1', 'system_version': '12.3.0', 'app_version': '10.1.0', 'lang_code': 'th', 'system_lang_code': 'th'},
{'device_model': 'iMac8,1', 'system_version': '12.2.1', 'app_version': '10.0.9', 'lang_code': 'vi', 'system_lang_code': 'vi'},
{'device_model': 'iMac7,1', 'system_version': '12.2.0', 'app_version': '10.0.8', 'lang_code': 'id', 'system_lang_code': 'id'},
{'device_model': 'iMac6,1', 'system_version': '12.1.1', 'app_version': '10.0.7', 'lang_code': 'ms', 'system_lang_code': 'ms'},
{'device_model': 'iMac5,2', 'system_version': '12.1.0', 'app_version': '10.0.6', 'lang_code': 'tl', 'system_lang_code': 'tl'},
{'device_model': 'iMac4,2', 'system_version': '12.0.1', 'app_version': '10.0.5', 'lang_code': 'bn', 'system_lang_code': 'bn'},
{'device_model': 'iMac4,1', 'system_version': '12.0.0', 'app_version': '10.0.4', 'lang_code': 'ur', 'system_lang_code': 'ur'},
{'device_model': 'iMac3,6', 'system_version': '11.7.10', 'app_version': '10.0.3', 'lang_code': 'fa', 'system_lang_code': 'fa'},
{'device_model': 'iMac3,4', 'system_version': '11.7.9', 'app_version': '10.0.2', 'lang_code': 'ta', 'system_lang_code': 'ta'},
{'device_model': 'iMac3,2', 'system_version': '11.7.8', 'app_version': '10.0.1', 'lang_code': 'te', 'system_lang_code': 'te'},
{'device_model': 'iMac3,1', 'system_version': '11.7.7', 'app_version': '10.0.0', 'lang_code': 'ml', 'system_lang_code': 'ml'},
{'device_model': 'MacBookPro11,5', 'system_version': '11.7.6', 'app_version': '10.0.9', 'lang_code': 'en', 'system_lang_code': 'en'},
{'device_model': 'MacBookPro10,2', 'system_version': '11.7.5', 'app_version': '10.0.8', 'lang_code': 'zh', 'system_lang_code': 'zh-CN'},
{'device_model': 'MacBookPro9,2', 'system_version': '11.7.4', 'app_version': '10.0.7', 'lang_code': 'es', 'system_lang_code': 'es'},
{'device_model': 'MacBookPro8,3', 'system_version': '11.7.3', 'app_version': '10.0.6', 'lang_code': 'fr', 'system_lang_code': 'fr'},
{'device_model': 'MacBookPro7,1', 'system_version': '11.7.2', 'app_version': '10.0.5', 'lang_code': 'de', 'system_lang_code': 'de'},
{'device_model': 'MacBookPro6,2', 'system_version': '11.7.1', 'app_version': '10.0.4', 'lang_code': 'ru', 'system_lang_code': 'ru'},
{'device_model': 'MacBookPro5,5', 'system_version': '11.7.0', 'app_version': '10.0.3', 'lang_code': 'pt', 'system_lang_code': 'pt'},
{'device_model': 'MacBookPro4,1', 'system_version': '11.6.9', 'app_version': '10.0.2', 'lang_code': 'it', 'system_lang_code': 'it'},
{'device_model': 'MacBookPro3,1', 'system_version': '11.6.8', 'app_version': '10.0.1', 'lang_code': 'ja', 'system_lang_code': 'ja'},
{'device_model': 'MacBookPro2,2', 'system_version': '11.6.7', 'app_version': '10.0.0', 'lang_code': 'ko', 'system_lang_code': 'ko'},
{'device_model': 'MacBookPro1,1', 'system_version': '11.6.6', 'app_version': '10.0.9', 'lang_code': 'ar', 'system_lang_code': 'ar'},
{'device_model': 'MacBookAir7,1', 'system_version': '11.6.5', 'app_version': '10.0.8', 'lang_code': 'hi', 'system_lang_code': 'hi'},
{'device_model': 'MacBookAir6,1', 'system_version': '11.6.4', 'app_version': '10.0.7', 'lang_code': 'tr', 'system_lang_code': 'tr'},
{'device_model': 'MacBookAir5,2', 'system_version': '11.6.3', 'app_version': '10.0.6', 'lang_code': 'pl', 'system_lang_code': 'pl'},
{'device_model': 'MacBookAir4,2', 'system_version': '11.6.2', 'app_version': '10.0.5', 'lang_code': 'nl', 'system_lang_code': 'nl'},
{'device_model': 'MacBookAir3,2', 'system_version': '11.6.1', 'app_version': '10.0.4', 'lang_code': 'sv', 'system_lang_code': 'sv'},
{'device_model': 'MacBookAir2,1', 'system_version': '11.6.0', 'app_version': '10.0.3', 'lang_code': 'da', 'system_lang_code': 'da'},
{'device_model': 'MacBookAir1,1', 'system_version': '11.5.2', 'app_version': '10.0.2', 'lang_code': 'no', 'system_lang_code': 'no'},
{'device_model': 'iMac12,2', 'system_version': '11.5.1', 'app_version': '10.0.1', 'lang_code': 'fi', 'system_lang_code': 'fi'},
{'device_model': 'iMac11,2', 'system_version': '11.5.0', 'app_version': '10.0.0', 'lang_code': 'cs', 'system_lang_code': 'cs'},
{'device_model': 'iMac10,2', 'system_version': '11.4.9', 'app_version': '10.0.9', 'lang_code': 'hu', 'system_lang_code': 'hu'},
{'device_model': 'iMac9,2', 'system_version': '11.4.8', 'app_version': '10.0.8', 'lang_code': 'ro', 'system_lang_code': 'ro'},
{'device_model': 'iMac8,2', 'system_version': '11.4.7', 'app_version': '10.0.7', 'lang_code': 'bg', 'system_lang_code': 'bg'},
{'device_model': 'iMac7,2', 'system_version': '11.4.6', 'app_version': '10.0.6', 'lang_code': 'sk', 'system_lang_code': 'sk'},
{'device_model': 'iMac6,2', 'system_version': '11.4.5', 'app_version': '10.0.5', 'lang_code': 'hr', 'system_lang_code': 'hr'},
{'device_model': 'iMac5,1', 'system_version': '11.4.4', 'app_version': '10.0.4', 'lang_code': 'sl', 'system_lang_code': 'sl'},
{'device_model': 'iMac4,1', 'system_version': '11.4.3', 'app_version': '10.0.3', 'lang_code': 'et', 'system_lang_code': 'et'},
{'device_model': 'iMac3,1', 'system_version': '11.4.2', 'app_version': '10.0.2', 'lang_code': 'lv', 'system_lang_code': 'lv'},
{'device_model': 'iMac2,1', 'system_version': '11.4.1', 'app_version': '10.0.1', 'lang_code': 'lt', 'system_lang_code': 'lt'},
{'device_model': 'iMac1,1', 'system_version': '11.4.0', 'app_version': '10.0.0', 'lang_code': 'uk', 'system_lang_code': 'uk'},
            ]
        }
    
    def generate_device_id(self, phone):
        """为账号生成唯一的设备ID"""
        # 使用手机号生成固定的hash，确保同一账号总是得到相同的设备信息
        return hashlib.md5(phone.encode()).hexdigest()
    
    def get_device_info(self, phone, preferred_type=None):
        """获取账号的设备信息"""
        device_id = self.generate_device_id(phone)
        
        # 检查是否已经为该账号分配了设备
        if phone in self.used_devices:
            return self.used_devices[phone]
        
        # 根据设备ID选择设备类型
        if preferred_type:
            device_type = preferred_type
        else:
            # 根据hash值分配设备类型（保证一致性）
            hash_int = int(device_id[:8], 16)
            if hash_int % 100 < 90:      # 90% Desktop (更符合宽带环境)
                device_type = 'desktop'
            elif hash_int % 100 < 95:    # 5% Android
                device_type = 'android'  
            else:                        # 5% iOS
                device_type = 'ios'
        
        # 选择具体设备
        templates = self.device_templates[device_type]
        device_index = int(device_id[8:12], 16) % len(templates)
        device_info = templates[device_index].copy()
        
        # 为设备信息添加一些随机性
        device_info = self.randomize_device_info(device_info, device_id)
        
        # 记录已使用的设备
        self.used_devices[phone] = device_info
        
        return device_info
    
    def randomize_device_info(self, device_info, device_id):
        """为设备信息添加随机性"""
        info = device_info.copy()
        
        # 使用设备ID的不同部分生成一致的随机性
        hash_parts = [device_id[i:i+4] for i in range(0, len(device_id), 4)]
        
        # 随机化系统版本（小幅调整）
        if 'android' in info['device_model'].lower() or 'samsung' in info['device_model'].lower() or 'xiaomi' in info['device_model'].lower():
            # Android设备
            base_version = int(info['system_version'])
            patch_level = int(hash_parts[0], 16) % 10
            info['system_version'] = f"{base_version}.{patch_level}"
        elif 'iphone' in info['device_model'].lower() or 'ipad' in info['device_model'].lower():
            # iOS设备
            version_parts = info['system_version'].split('.')
            if len(version_parts) >= 2:
                patch = int(hash_parts[1], 16) % 10
                info['system_version'] = f"{version_parts[0]}.{version_parts[1]}.{patch}"
        
        # 随机化应用版本
        app_parts = info['app_version'].split('.')
        if len(app_parts) >= 2:
            minor_update = int(hash_parts[2], 16) % 10
            info['app_version'] = f"{app_parts[0]}.{app_parts[1]}.{minor_update}"
        
        return info
    
    def save_device_assignments(self, file_path='resources/device_assignments.json'):
        """保存设备分配记录"""
        try:
            Path(file_path).parent.mkdir(exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.used_devices, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存设备分配记录失败: {e}")
            return False
    
    def load_device_assignments(self, file_path='resources/device_assignments.json'):
        """加载设备分配记录"""
        try:
            if Path(file_path).exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.used_devices = json.load(f)
                return True
        except Exception as e:
            print(f"加载设备分配记录失败: {e}")
            self.used_devices = {}
        return False
    
    def get_device_summary(self):
        """获取设备分配摘要"""
        summary = {
            'total_devices': len(self.used_devices),
            'android_count': 0,
            'ios_count': 0,
            'desktop_count': 0,
            'device_models': {}
        }
        
        for phone, device_info in self.used_devices.items():
            device_model = device_info['device_model']
            
            # 统计设备类型
            if any(brand in device_model.lower() for brand in ['samsung', 'xiaomi', 'oppo', 'vivo', 'huawei', 'oneplus', 'pixel']):
                summary['android_count'] += 1
            elif 'iphone' in device_model.lower() or 'ipad' in device_model.lower():
                summary['ios_count'] += 1
            elif 'desktop' in device_model.lower():
                summary['desktop_count'] += 1
            
            # 统计设备型号
            if device_model not in summary['device_models']:
                summary['device_models'][device_model] = 0
            summary['device_models'][device_model] += 1
        
        return summary
    
    def print_device_summary(self):
        """打印设备分配摘要"""
        summary = self.get_device_summary()
        
        print("设备伪装分配摘要：")
        print(f"总设备数：{summary['total_devices']}")
        print(f"Android设备：{summary['android_count']}")
        print(f"iOS设备：{summary['ios_count']}")
        print(f"桌面设备：{summary['desktop_count']}")
        print("\n设备型号分布：")
        
        for model, count in sorted(summary['device_models'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {model}: {count}个")

# 使用示例
if __name__ == "__main__":
    device_spoofing = DeviceSpoofing()
    
    # 测试账号设备分配
    test_phones = [
        "1234567890", "9876543210", "5555555555", 
        "1111111111", "2222222222", "3333333333"
    ]
    
    print("测试设备分配：")
    for phone in test_phones:
        device_info = device_spoofing.get_device_info(phone)
        print(f"{phone}: {device_info['device_model']} - {device_info['system_version']} - {device_info['app_version']}")
    
    print("\n" + "="*50)
    device_spoofing.print_device_summary()