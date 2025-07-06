import os
import sys
import json
import base64
import sqlite3
import logging
from glob import glob
from shutil import copyfile
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2

logger = logging.getLogger(__name__)
__all__ = ['get_browsers_cookies']

class Decrypter:
    def __init__(self, key):
        self.key = key

    def decrypt(self, encrypted_value):
        if sys.platform == 'darwin':
            # macOS Chrome cookies don't have DPAPI or GCM tag
            cipher = AES.new(self.key, AES.MODE_GCM, nonce=encrypted_value[3:15])
            return cipher.decrypt(encrypted_value[15:]).decode('utf-8')
        else:
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:-16]
            tag = encrypted_value[-16:]
            cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode('utf-8')


def convert_chrome_utc(chrome_utc):
    second = int(chrome_utc / 1e6)
    if second > 0:
        second -= 11644473600
    return datetime.fromtimestamp(second)


def decrypt_key_win(local_state):
    import win32crypt
    with open(local_state, 'r', encoding='utf-8') as f:
        encrypted_key = json.load(f)['os_crypt']['encrypted_key']
    encrypted_key = base64.b64decode(encrypted_key)[5:]
    return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]


def decrypt_key_mac(local_state_path):
    import subprocess
    with open(local_state_path, 'r', encoding='utf-8') as f:
        local_state = json.load(f)
    encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]

    password = subprocess.check_output(
        ['security', 'find-generic-password', '-wa', 'Chrome'],
        text=True
    ).strip()

    salt = b'saltysalt'
    key = PBKDF2(password.encode(), salt, 16, 1003)
    iv = b' ' * 16
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted_key = cipher.decrypt(encrypted_key)
    return decrypted_key.rstrip(b'\x10')


def decrypt_key_linux(local_state):
    with open(local_state, 'r', encoding='utf-8') as f:
        encrypted_key = json.load(f)['os_crypt']['encrypted_key']
    encrypted_key = base64.b64decode(encrypted_key)[5:]
    return encrypted_key  # NOTE: Linux Gnome/KDE 不一定支持解密


# 根据平台动态选择解密函数
if sys.platform == 'win32':
    decrypt_key = decrypt_key_win
elif sys.platform == 'darwin':
    decrypt_key = decrypt_key_mac
else:
    decrypt_key = decrypt_key_linux


def get_cookies(cookies_file, decrypter, host_pattern='javdb%.com'):
    temp_dir = os.getenv('TMPDIR', os.getenv('TEMP', os.getenv('TMP', '.')))
    temp_cookie = os.path.join(temp_dir, 'Cookies')
    copyfile(cookies_file, temp_cookie)

    conn = sqlite3.connect(temp_cookie)
    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT host_key, name, encrypted_value, expires_utc 
        FROM cookies 
        WHERE host_key LIKE "{host_pattern}"
    ''')

    now = datetime.now()
    records = {}

    for host_key, name, encrypted_value, expires_utc in cursor.fetchall():
        if not encrypted_value:
            continue
        expires = convert_chrome_utc(expires_utc)
        if expires < now:
            continue
        try:
            value = decrypter.decrypt(encrypted_value)
            records.setdefault(host_key, {})[name] = value
        except Exception as e:
            logger.debug(f"Failed to decrypt cookie {name}@{host_key}: {e}")

    conn.close()
    os.remove(temp_cookie)

    return {k: v for k, v in records.items() if '_jdb_session' in v}


def get_browsers_cookies():
    browser_dirs = {
        'Chrome':        '/Google/Chrome/User Data',
        'Chrome Beta':   '/Google/Chrome Beta/User Data',
        'Chrome Canary': '/Google/Chrome SxS/User Data',
        'Chromium':      '/Google/Chromium/User Data',
        'Edge':          '/Microsoft/Edge/User Data',
        'Vivaldi':       '/Vivaldi/User Data'
    }

    if sys.platform == 'win32' or sys.platform == 'darwin':
        local_base = os.getenv('LOCALAPPDATA') if sys.platform == 'win32' else os.path.expanduser('~/Library/Application Support')
    else:
        local_base = os.path.expanduser('~/.config')  # Linux 默认

    all_browser_cookies = []
    exceptions = []

    for name, rel_path in browser_dirs.items():
        user_dir = os.path.normpath(local_base + rel_path)
        local_state = os.path.join(user_dir, 'Local State')
        cookies_files = glob(user_dir + '/*/Cookies') + glob(user_dir + '/*/Network/Cookies')

        if not os.path.exists(local_state):
            continue
        try:
            key = decrypt_key(local_state)
            decrypter = Decrypter(key)
        except Exception as e:
            logger.debug(f"无法解密Local State: {e}")
            continue

        for file in cookies_files:
            profile = f"{name}: {file.split('User Data')[-1].split(os.sep)[1]}"
            try:
                cookies = get_cookies(file, decrypter)
                for domain, ck in cookies.items():
                    all_browser_cookies.append({
                        'profile': profile,
                        'site': domain,
                        'cookies': ck
                    })
            except Exception as e:
                exceptions.append(e)
                logger.debug(f"解析失败: {file}: {e}", exc_info=True)

    if not all_browser_cookies and exceptions:
        raise exceptions[0]

    return all_browser_cookies


if __name__ == "__main__":
    all_cookies = get_browsers_cookies()
    if not all_cookies:
        print("❌ 未获取到任何浏览器 cookies。请确认是否已登录 JavDB 且未过期。")
    for d in all_cookies:
        print('{:<30}{}'.format(d["profile"], d["site"]))
