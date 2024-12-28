#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import time
import sys

# サーバのアドレスとポートを設定
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 50000
BUFFER_SIZE = 4096


class UDPChatClient:
    def __init__(self, server_host, server_port, username):
        self.server_address = (server_host, server_port)
        self.username = username
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = True

    def start(self):
        print(f"Connected to UDP chat server {self.server_address}")
        print("Type your message and press Enter to send.")
        print("Press Ctrl+C to exit.\n")

        # サーバからのメッセージ受信を別スレッドで開始
        receiver_thread = threading.Thread(
            target=self.receive_loop, daemon=True)
        receiver_thread.start()

        # メインスレッドでユーザーの入力を送信
        try:
            while self.running:
                message = sys.stdin.readline().rstrip('\n')
                if not message:
                    continue
                self.send_message(message)
        except KeyboardInterrupt:
            print("\nExiting chat client...")

        self.running = False
        self.sock.close()

    def receive_loop(self):
        """
        サーバからのメッセージを受信して表示する。
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
            except OSError:
                break

            if not data:
                continue

            # メッセージをパース
            usernamelen = data[0]
            username_bytes = data[1: 1 + usernamelen]
            message_bytes = data[1 + usernamelen:]

            try:
                from_username = username_bytes.decode('utf-8')
                message = message_bytes.decode('utf-8')
            except UnicodeDecodeError:
                continue

            # コンソールに表示
            print(f"{from_username}: {message}")

    def send_message(self, message):
        """
        サーバにメッセージを送信する。
        """
        username_encoded = self.username.encode('utf-8')
        message_encoded = message.encode('utf-8')

        usernamelen = len(username_encoded)
        packet = bytes([usernamelen]) + username_encoded + message_encoded

        self.sock.sendto(packet, self.server_address)


if __name__ == "__main__":
    # 起動時にユーザー名を入力
    print("==== UDP Chat Client ====")
    username = input("Enter your username: ")

    client = UDPChatClient(SERVER_HOST, SERVER_PORT, username)
    client.start()
