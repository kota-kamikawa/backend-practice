#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import time

# サーバ設定
HOST = '0.0.0.0'  # すべてのインターフェースで待受
PORT = 50000      # 任意のポート番号
BUFFER_SIZE = 4096
CLIENT_TIMEOUT = 60  # 最終メッセージ受信から 60 秒経過で削除


class UDPChatServer:
    def __init__(self, host, port):
        self.server_address = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(self.server_address)

        # クライアント情報を保存する辞書
        # key: (ip, port)
        # value: {
        #   'username': str,
        #   'last_active': float (UNIX タイムスタンプ)
        # }
        self.clients = {}

        # 終了フラグ
        self.running = True

    def start(self):
        print(f"UDP Chat Server started on {self.server_address} ...")

        # 受信ループは別スレッドで動かす
        receiver_thread = threading.Thread(
            target=self.receive_loop, daemon=True)
        receiver_thread.start()

        # クライアントを定期的に掃除するスレッド
        cleaner_thread = threading.Thread(
            target=self.cleanup_inactive_clients_loop, daemon=True)
        cleaner_thread.start()

        # メインスレッドはキーボード入力などでサーバ終了のための待機をする想定
        # ここではシンプルに無限ループ
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down server...")

        self.running = False
        self.sock.close()

    def receive_loop(self):
        """
        クライアントからのメッセージを受信し、
        ほかのクライアントへブロードキャストする。
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
            except OSError:
                # ソケットがクローズされるなどしてエラーになる可能性あり
                break

            if not data:
                continue

            # メッセージからユーザー名と本文を取り出す
            usernamelen = data[0]  # 最初の 1 バイト
            username_bytes = data[1: 1 + usernamelen]
            message_bytes = data[1 + usernamelen:]

            try:
                username = username_bytes.decode('utf-8')
                message = message_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # デコード失敗した場合
                continue

            # クライアントリストに登録 or 更新
            self.clients[addr] = {
                'username': username,
                'last_active': time.time()
            }

            # 受信メッセージをコンソールに表示（サーバ側ログ）
            print(f"[{addr}] {username}: {message}")

            # 全クライアントにメッセージを転送
            self.broadcast(username, message)

    def broadcast(self, username, message):
        """
        現在登録されているすべてのクライアントに対し、メッセージを送信する。
        """
        # 送信用データにエンコード
        username_encoded = username.encode('utf-8')
        message_encoded = message.encode('utf-8')
        usernamelen = len(username_encoded)

        packet = bytes([usernamelen]) + username_encoded + message_encoded

        # self.clients に格納されているアドレスすべてに送信
        for addr in list(self.clients.keys()):
            try:
                self.sock.sendto(packet, addr)
            except OSError:
                # ネットワーク障害などで送れなかった場合
                pass

    def cleanup_inactive_clients_loop(self):
        """
        定期的にクライアントの最終アクティブ時刻をチェックし、
        一定時間経過したクライアントを削除する。
        """
        while self.running:
            now = time.time()
            # タイムアウトしたクライアントは削除
            for addr, info in list(self.clients.items()):
                if now - info['last_active'] > CLIENT_TIMEOUT:
                    print(f"Removing inactive client: {
                          addr}, username={info['username']}")
                    del self.clients[addr]
            time.sleep(5)  # 5 秒おきにチェック


if __name__ == "__main__":
    server = UDPChatServer(HOST, PORT)
    server.start()
