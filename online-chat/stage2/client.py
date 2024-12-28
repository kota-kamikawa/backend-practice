#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import struct
import sys

##
# 設定
##
TCP_HOST = '127.0.0.1'
TCP_PORT = 6000      # サーバの TCRP ポート
UDP_PORT = 6001      # サーバの UDP ポート
TCRP_HEADER_SIZE = 32
UDP_BUFFER_SIZE = 4096


def build_tcrp_header(roomNameSize, operation, state, opPayloadSize):
    """
    TCRP ヘッダを 32 バイトで構築
    """
    opPayloadSizeRaw = bytes([opPayloadSize]) + b'\x00' * 28
    return struct.pack('BBB29s', roomNameSize, operation, state, opPayloadSizeRaw)


def parse_tcrp_header(data):
    """
    TCRP ヘッダをパース
    戻り値: (roomNameSize, operation, state, opPayloadSize)
    """
    if len(data) < TCRP_HEADER_SIZE:
        raise ValueError("Invalid TCRP header length")
    roomNameSize, operation, state, opPayloadSizeRaw = struct.unpack(
        'BBB29s', data[:TCRP_HEADER_SIZE])
    opPayloadSize = opPayloadSizeRaw[0]
    return roomNameSize, operation, state, opPayloadSize


class UDPChatClient:
    """
    UDP でチャットを行うクライアント
    """

    def __init__(self, room_name, token):
        self.room_name = room_name
        self.token = token
        self.running = True

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # OSに任せてポートを割り当て ('0.0.0.0', 0)
        self.sock.bind(('0.0.0.0', 0))

    def start(self):
        """
        受信スレッドを立ち上げて、メインループは送信を担当
        """
        th = threading.Thread(target=self.receive_loop, daemon=True)
        th.start()

        print(f"\n[INFO] Joined room '{
              self.room_name}' with token '{self.token}'!")
        print("[INFO] Type messages to send. Ctrl+C to quit.\n")

        try:
            while self.running:
                line = sys.stdin.readline()
                if not line:
                    break
                message = line.strip()
                if message:
                    self.send_message(message)
        except KeyboardInterrupt:
            pass

        self.running = False
        self.sock.close()

    def receive_loop(self):
        """
        サーバからのブロードキャスト(UDP)を受信して表示
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(UDP_BUFFER_SIZE)
            except OSError:
                break
            if not data:
                continue

            try:
                text = data.decode('utf-8')
            except:
                text = "[decode error]"
            print(text)

    def send_message(self, message):
        """
        UDP パケットを作成してサーバへ送信
         [RoomNameSize(1byte)][TokenSize(1byte)][RoomName][Token][Message]
        """
        room_bytes = self.room_name.encode('utf-8')
        token_bytes = self.token.encode('utf-8')
        msg_bytes = message.encode('utf-8')

        packet = (bytes([len(room_bytes)]) +
                  bytes([len(token_bytes)]) +
                  room_bytes +
                  token_bytes +
                  msg_bytes)

        self.sock.sendto(packet, (TCP_HOST, UDP_PORT))


def tcrp_handshake_create_room(room_name, username, password=""):
    """
    ルーム作成 (Operation=1)
    """
    return tcrp_handshake(room_name, 1, username, password)


def tcrp_handshake_join_room(room_name, username, password=""):
    """
    ルーム参加 (Operation=2)
    """
    return tcrp_handshake(room_name, 2, username, password)


def tcrp_handshake(room_name, operation, username, password):
    """
    TCRP ハンドシェイク (TCP) を用いてトークンを取得
    返値: (成功時: (True, token文字列), 失敗時: (False, エラーメッセージ))
    """
    room_name_bytes = room_name.encode('utf-8')
    payload_str = f"{username} {password}".strip()  # 簡易
    payload_bytes = payload_str.encode('utf-8')

    roomNameSize = len(room_name_bytes)
    opPayloadSize = len(payload_bytes)
    state = 0  # 0=リクエスト

    header = build_tcrp_header(roomNameSize, operation, state, opPayloadSize)
    body = room_name_bytes + payload_bytes
    packet = header + body

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((TCP_HOST, TCP_PORT))
            s.sendall(packet)

            # 応答受信
            resp_header = s.recv(TCRP_HEADER_SIZE)
            if not resp_header:
                return (False, "No response header from server")

            r_roomNameSize, r_operation, r_state, r_opPayloadSize = parse_tcrp_header(
                resp_header)
            resp_body_len = r_roomNameSize + r_opPayloadSize
            resp_body = b''
            while len(resp_body) < resp_body_len:
                chunk = s.recv(resp_body_len - len(resp_body))
                if not chunk:
                    break
                resp_body += chunk

            # body を分解
            r_room_name_bytes = resp_body[:r_roomNameSize]
            r_payload_bytes = resp_body[r_roomNameSize:]

            try:
                r_payload_dec = r_payload_bytes.decode('utf-8')
            except:
                r_payload_dec = ""

            if r_state == 2:
                # 成功 -> r_payload_dec がトークン
                return (True, r_payload_dec)
            else:
                # 失敗 -> エラーメッセージ
                return (False, r_payload_dec)
    except Exception as e:
        return (False, f"Handshake failed: {e}")


def main():
    print("=== TCRP + UDP Chat Client (Stage 2) - with port tracking ===")
    print("1) Create room")
    print("2) Join room")
    choice = input("Select operation [1/2]: ").strip()
    if choice not in ['1', '2']:
        print("Invalid choice.")
        return

    room_name = input("Room Name: ").strip()
    username = input("Username: ").strip()
    password = input("(Optional) Password: ").strip()

    if choice == '1':
        ok, result = tcrp_handshake_create_room(room_name, username, password)
        if not ok:
            print(f"[ERROR] Failed to create room: {result}")
            return
        token = result
        print(f"[INFO] Room '{room_name}' created. Token={token}")
    else:
        ok, result = tcrp_handshake_join_room(room_name, username, password)
        if not ok:
            print(f"[ERROR] Failed to join room: {result}")
            return
        token = result
        print(f"[INFO] Joined room '{room_name}'. Token={token}")

    # UDP チャット開始
    client = UDPChatClient(room_name, token)
    client.start()


if __name__ == "__main__":
    main()
