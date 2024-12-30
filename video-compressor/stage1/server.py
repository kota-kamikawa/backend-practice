#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import struct
import time
import os

HOST = '0.0.0.0'   # 全インターフェースで待受
PORT = 8000        # 任意のポート
BACKLOG = 5        # 同時待受可能数

# 32 バイトのうち先頭 4 バイトをファイルサイズ (unsigned 32-bit) として扱う
FILESIZE_HEADER_LEN = 32
# 最終的にクライアントへ返すステータスメッセージのサイズ
STATUS_MSG_LEN = 16

# 保存先ディレクトリ（実行時にカレントに作られる想定）
UPLOAD_DIR = "uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


def handle_client(conn, addr):
    """
    クライアント 1 台のファイル受信処理を行う
    """
    try:
        print(f"[INFO] Connected by {addr}")

        # 1) まず 32 バイト受信
        header_data = recv_exact(conn, FILESIZE_HEADER_LEN)
        if not header_data:
            print("[ERROR] Failed to receive file size header.")
            return

        # 先頭 4 バイトからファイルサイズを取得 (unsigned int)
        file_size = struct.unpack('!I', header_data[:4])[0]  # ネットワークバイトオーダー(!)

        # 残りの 28 バイトは今回は使わない (パディング扱い)

        print(f"[INFO] Declared file size: {file_size} bytes")

        # 2) file_size 分だけ受信してファイルに書き込む
        timestamp = int(time.time())
        out_filename = os.path.join(UPLOAD_DIR, f"uploaded_{timestamp}.mp4")

        received_bytes = 0
        with open(out_filename, 'wb') as f:
            while received_bytes < file_size:
                chunk_size = min(1400, file_size - received_bytes)
                data = conn.recv(chunk_size)
                if not data:
                    # 途中で切断されたらアップロード失敗
                    print("[ERROR] Connection lost during file upload.")
                    return
                f.write(data)
                received_bytes += len(data)

        print(f"[INFO] Received file saved: {
              out_filename}, total={received_bytes} bytes")

        # 3) 16 バイトのステータスを返す (例: "UPLOAD_OK" + パディング)
        status_str = "UPLOAD_OK"
        status_bytes = status_str.encode('utf-8')
        # 16 バイトにパディング
        status_bytes_padded = status_bytes + b'\x00' * \
            (STATUS_MSG_LEN - len(status_bytes))
        conn.sendall(status_bytes_padded)

    except Exception as e:
        print(f"[ERROR] {addr} - Exception: {e}")
    finally:
        conn.close()
        print(f"[INFO] Connection closed: {addr}")


def recv_exact(conn, size):
    """
    size バイトを正確に受信するための補助関数
    """
    buf = b''
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def main():
    print(f"=== File Upload Server (TCP) starting on port {PORT} ===")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(BACKLOG)
        print(f"[INFO] Listening on {HOST}:{PORT}")

        try:
            while True:
                conn, addr = s.accept()
                # クライアントごとにスレッドを立てて処理する
                threading.Thread(target=handle_client, args=(
                    conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            print("\n[INFO] Server shutting down...")


if __name__ == "__main__":
    main()
