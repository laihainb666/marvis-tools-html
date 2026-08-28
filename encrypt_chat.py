#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
encrypt_chat —— 加密通道对话（有网络 / 无网络双模式）
=========================================================
- 有网络（在线）：TCP 点对点直连 / 局域网 / 公网中继，AES-GCM 加密
- 无网络（离线）：蓝牙 RFCOMM 点对点直连（Linux，需蓝牙硬件），AES-GCM 加密

加密：口令经 scrypt 派生 256-bit 密钥；每条消息 AES-GCM（随机 nonce + 认证标签），
     消息格式：BLCHAT|版本|nonce|密文|tag（十六进制），可防窃听与篡改。

用法：
  # 在线模式
  python3 encrypt_chat.py listen --channel tcp --port 9000 --key 你的口令
  python3 encrypt_chat.py chat   --channel tcp --host <IP> --port 9000 --key 你的口令

  # 离线蓝牙模式（双方在同一局域网/无网环境，Linux + 蓝牙）
  python3 encrypt_chat.py listen --channel ble --key 你的口令
  python3 encrypt_chat.py chat   --channel ble --mac <对方蓝牙MAC> --key 你的口令

  # 生成密钥提示词（可选）
  python3 encrypt_chat.py passwd

收发：输入消息回车发送；输入 /quit 退出；输入 /name 名字 设置昵称。
"""

import argparse
import getpass
import hashlib
import os
import socket
import sys
import threading

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    CRYPTO_OK = True
except ImportError:
    CRYPTO_OK = False

PROTO = "BLCHAT"
VERSION = "1"
HEADER = 1024 * 1024  # 单条消息上限 1MB

# ---------------------------------------------------------------- 加密

def derive_key(password: bytes, salt: bytes) -> bytes:
    if not CRYPTO_OK:
        sys.exit("[!] 需要 cryptography：python3 -m pip install cryptography")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password)

def encrypt_msg(plain: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plain, None)
    return nonce + ct  # 前 12 字节 nonce，其余密文+16B tag

def decrypt_msg(blob: bytes, key: bytes) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)

def frame(payload: bytes) -> bytes:
    """BLCHAT|1|<hex>"""
    return f"{PROTO}|{VERSION}|".encode() + payload.hex().encode() + b"\n"

def deframe(data: bytes):
    """解析帧，返回 (payload_bytes, rest_bytes)"""
    text = data.decode("utf-8", "replace")
    if not text.startswith(f"{PROTO}|{VERSION}|"):
        return None, data
    rest = text[len(f"{PROTO}|{VERSION}|"):]
    nl = rest.find("\n")
    if nl < 0:
        return None, data
    hexpart = rest[:nl]
    try:
        payload = bytes.fromhex(hexpart)
    except ValueError:
        return None, data
    return payload, b""

# ---------------------------------------------------------------- 会话

class ChatSession:
    def __init__(self, sock, key, nickname):
        self.sock = sock
        self.key = key
        self.nickname = nickname
        self.buf = b""
        self.lock = threading.Lock()

    def send_msg(self, text: str):
        payload = encrypt_msg(text.encode("utf-8"), self.key)
        with self.lock:
            self.sock.sendall(frame(payload))

    def read_loop(self):
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    print("\n[对端已断开]")
                    os._exit(0)
                self.buf += chunk
                payload, self.buf = deframe(self.buf)
                if payload is not None:
                    try:
                        msg = decrypt_msg(payload, self.key)
                        print(f"\n[对方] {msg.decode('utf-8', 'replace')}")
                        print("你> ", end="", flush=True)
                    except Exception:
                        print("\n[警告] 收到无法解密的消息（密钥不一致？）")
                        print("你> ", end="", flush=True)
        except Exception:
            print("\n[连接中断]")
            os._exit(0)

    def input_loop(self):
        print(f"已连接，加密通道已建立（AES-GCM）。输入消息回车发送，/quit 退出。")
        while True:
            try:
                line = input("你> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[退出]")
                os._exit(0)
            if not line:
                continue
            if line == "/quit":
                print("[退出]")
                os._exit(0)
            if line.startswith("/name "):
                self.nickname = line.split(" ", 1)[1].strip()
                print(f"[昵称已设为 {self.nickname}]")
                continue
            self.send_msg(f"{self.nickname}: {line}")

    def run(self):
        threading.Thread(target=self.read_loop, daemon=True).start()
        self.input_loop()

# ---------------------------------------------------------------- 通道

def tcp_listen(port, key, nickname):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    print(f"[在线监听] 0.0.0.0:{port}，等待对方连接（对端运行：encrypt_chat.py chat --host <本机IP> --port {port} --key 同一口令）…")
    conn, addr = srv.accept()
    print(f"[已连接] {addr}")
    ChatSession(conn, key, nickname).run()

def tcp_chat(host, port, key, nickname):
    print(f"[连接] {host}:{port} …")
    s = socket.create_connection((host, port), timeout=15)
    print("[已连接]")
    ChatSession(s, key, nickname).run()

def ble_listen(key, nickname):
    try:
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    except OSError as e:
        sys.exit(f"[!] 蓝牙不可用：{e}\n    无网络离线模式需要 Linux 蓝牙硬件（hciconfig 可见 hci0），当前环境不支持。")
    s.bind(("", 1))
    s.listen(1)
    print("[蓝牙监听] RFCOMM 通道 1，等待对方连接…")
    conn, addr = s.accept()
    print(f"[已连接] 蓝牙地址 {addr}")
    ChatSession(conn, key, nickname).run()

def ble_chat(mac, key, nickname):
    try:
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        s.connect((mac, 1))
    except OSError as e:
        sys.exit(f"[!] 蓝牙连接失败：{e}\n    请确认监听端已启动且 MAC 正确（hciconfig 查看）。")
    print("[已连接]")
    ChatSession(s, key, nickname).run()

# ---------------------------------------------------------------- 入口

def main():
    p = argparse.ArgumentParser(description="加密通道对话（有网 TCP / 无网蓝牙，AES-GCM）")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = lambda sp: sp.add_argument("--key", default=None, help="口令（不传则交互输入，两端必须一致）")
    nick = lambda sp: sp.add_argument("--nick", default="user", help="昵称（默认 user）")

    sp = sub.add_parser("listen", help="监听等待对方连接")
    sp.add_argument("--channel", choices=["tcp", "ble"], default="tcp")
    sp.add_argument("--port", type=int, default=9000)
    common(sp); nick(sp)

    sp = sub.add_parser("chat", help="主动连接对方")
    sp.add_argument("--channel", choices=["tcp", "ble"], default="tcp")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=9000)
    sp.add_argument("--mac", default=None)
    common(sp); nick(sp)

    sp = sub.add_parser("passwd", help="生成一段适合做口令的随机短语")
    sp.set_defaults(cmd="passwd")

    args = p.parse_args()

    if args.cmd == "passwd":
        print("建议口令：" + hashlib.sha256(os.urandom(32)).hexdigest()[:24])
        return

    if not CRYPTO_OK:
        sys.exit("[!] 缺少 cryptography：python3 -m pip install cryptography")

    key = args.key if args.key else getpass.getpass("口令（两端必须一致）: ")
    if not key:
        sys.exit("[!] 口令不能为空")
    salt = b"encrypt-chat-v1-salt"
    dk = derive_key(key.encode(), salt)
    nickname = args.nick or "user"

    if args.cmd == "listen":
        if args.channel == "ble":
            ble_listen(dk, nickname)
        else:
            tcp_listen(args.port, dk, nickname)
    else:
        if args.channel == "ble":
            if not args.mac:
                sys.exit("[!] 蓝牙模式需要 --mac 对方地址")
            ble_chat(args.mac, dk, nickname)
        else:
            tcp_chat(args.host, args.port, dk, nickname)

if __name__ == "__main__":
    main()
