#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import struct
import os
import sys

# 送信時に先頭 32 バイトのうち、先頭4バイトでファイルサイズを伝える
FILESIZE_HEADER_LEN = 32
# ステータス応答 (16 バイト) を受け取る
STATUS_MSG_LEN = 16

# 1 パケットあたりの送信バイト数
SEND_CHUNK_SIZE = 1400


def main():

    host = "127.0.0.1"
    port = 8000
    filename = "sample.mp4"

    # 1) mp4ファイルかどうか軽くチェック (拡張子チェックのみ、実内容は未検証)
    if not filename.lower().endswith('.mp4'):
        print("[ERROR] This client only supports .mp4 uploads.")
        sys.exit(1)

    if not os.path.isfile(filename):
        print(f"[ERROR] File not found: {filename}")
        sys.exit(1)

    # 2) ファイルサイズを取得
    file_size = os.path.getsize(filename)
    if file_size > 0xFFFFFFFF:  # 4GB 超え
        print("[ERROR] File size exceeds 4GB limit.")
        sys.exit(1)

    print(f"[INFO] Uploading {filename} ({file_size} bytes) to {host}:{port}")

    # 3) TCP ソケットで接続
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))

        # 4) まず 32 バイトのヘッダを送信
        #    - 先頭4バイトにファイルサイズを格納 (unsigned 32bit big-endian)
        #    - 残り28バイトはパディング (0埋め)
        header = struct.pack('!I', file_size) + b'\x00' * \
            (FILESIZE_HEADER_LEN - 4)
        s.sendall(header)

        # 5) ファイル本体を 1400 バイトずつ送信
        sent_bytes = 0
        with open(filename, 'rb') as f:
            while True:
                chunk = f.read(SEND_CHUNK_SIZE)
                if not chunk:
                    break
                s.sendall(chunk)
                sent_bytes += len(chunk)

        print(f"[INFO] Finished sending {sent_bytes} bytes.")

        # 6) サーバから 16 バイトのステータスを受け取る
        status_data = recv_exact(s, STATUS_MSG_LEN)
        if status_data:
            status_str = status_data.decode(
                'utf-8', errors='ignore').rstrip('\x00')
            print(f"[INFO] Server response: {status_str}")
        else:
            print("[ERROR] No status received from server.")


def recv_exact(sock, size):
    """
    size バイトちょうど受信する
    """
    buf = b''
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


if __name__ == "__main__":
    main()
