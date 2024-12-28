#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import struct
import time
import uuid

##
# 設定
##
TCP_HOST = '0.0.0.0'
TCP_PORT = 6000      # TCRP 用の TCP ポート
UDP_PORT = 6001      # チャット用の UDP ポート
TCRP_HEADER_SIZE = 32

# TCRP (TCP) プロトコル仕様（簡易）
"""
ヘッダ (32 バイト):
  [roomNameSize(1バイト)] [operation(1バイト)] [state(1バイト)] [operationPayloadSize(29バイト相当)]
ボディ:
  - 最初の roomNameSize バイトがルーム名 (最大28バイト)
  - 続く operationPayloadSize バイトがペイロード (username, password等)
"""

# UDP チャット用パケット仕様
"""
先頭2バイト: [RoomNameSize(1バイト)][TokenSize(1バイト)]
続く RoomNameSize バイトがルーム名
続く TokenSize バイトがトークン
残りがメッセージ
"""

UDP_BUFFER_SIZE = 4096

# ルーム管理用データ構造
#   rooms[room_name] = {
#       'host_token': str,   # ホストのトークン
#       'participants': {
#           token: {
#               'username': str,
#               'ip': str or None,      # UDPで初回送信してきたアドレス
#               'last_active': float
#           },
#           ...
#       },
#       'password': str,
#       'active': bool
#   }
rooms = {}

# トークンから逆引きする辞書
#   token_map[token] = {
#       'room': room_name,
#       'username': str,
#       'ip': str or None,
#       'port': int or None
#   }
token_map = {}

# スレッド間でのデータ競合を防ぐためのロック
lock = threading.Lock()


def generate_token():
    """最大255バイト程度なら UUID 文字列で十分。"""
    return str(uuid.uuid4())


def parse_tcrp_header(header_bytes: bytes):
    """
    32バイトの TCRP ヘッダをパース
    戻り値: (roomNameSize, operation, state, opPayloadSize)
    """
    if len(header_bytes) < TCRP_HEADER_SIZE:
        raise ValueError("Invalid TCRP header length")
    # 'BBB29s' = 1byte + 1byte + 1byte + 29byte = 32byte
    roomNameSize, operation, state, opPayloadSizeRaw = struct.unpack(
        'BBB29s', header_bytes)
    # opPayloadSizeRaw[0] をペイロードサイズとして扱う
    opPayloadSize = opPayloadSizeRaw[0]
    return roomNameSize, operation, state, opPayloadSize


def build_tcrp_header(roomNameSize, operation, state, opPayloadSize):
    """
    TCRP ヘッダを 32 バイトで構築
    """
    # opPayloadSize は先頭1バイト、残り28バイトはゼロ詰め
    opPayloadSizeRaw = bytes([opPayloadSize]) + b'\x00' * 28
    return struct.pack('BBB29s', roomNameSize, operation, state, opPayloadSizeRaw)


def handle_tcp_client(conn, addr):
    """
    受け付けた TCP クライアントと TCRP でやり取りし、ルーム作成/参加を処理
    """
    try:
        header_data = conn.recv(TCRP_HEADER_SIZE)
        if not header_data:
            return

        roomNameSize, operation, state, opPayloadSize = parse_tcrp_header(
            header_data)

        body_size = roomNameSize + opPayloadSize
        body_data = b''
        while len(body_data) < body_size:
            chunk = conn.recv(body_size - len(body_data))
            if not chunk:
                return
            body_data += chunk

        # ボディを分割
        room_name_bytes = body_data[:roomNameSize]
        payload_bytes = body_data[roomNameSize:]
        try:
            room_name = room_name_bytes.decode('utf-8')
        except:
            room_name = "?"

        # payload には "username password" のように空白区切りで入れる例
        try:
            payload_decoded = payload_bytes.decode('utf-8')
        except:
            payload_decoded = ""
        parts = payload_decoded.split()
        username = parts[0] if len(parts) >= 1 else "unknown"
        password = parts[1] if len(parts) >= 2 else ""

        if operation == 1:  # Create room
            handle_create_room(conn, room_name, username, password)
        elif operation == 2:  # Join room
            handle_join_room(conn, room_name, username, password)
        else:
            # 無効オペレーション
            send_tcrp_response(conn, room_name, operation,
                               1, 0, b"INVALID_OPERATION")

    except Exception as e:
        print(f"[TCP] Error handling client {addr}: {e}")
    finally:
        conn.close()


def handle_create_room(conn, room_name, username, password):
    """
    新規ルーム作成
    """
    with lock:
        # 既存ルームがアクティブならエラーとする簡易方針
        if room_name in rooms and rooms[room_name]['active']:
            send_tcrp_response(conn, room_name, 1, 1, 0,
                               b"ROOM_ALREADY_EXISTS")
            return

        # 新しいトークン作成
        token = generate_token()

        rooms[room_name] = {
            'host_token': token,
            'participants': {
                token: {
                    'username': username,
                    'ip': None,
                    'last_active': time.time()
                }
            },
            'password': password,
            'active': True
        }

        token_map[token] = {
            'room': room_name,
            'username': username,
            'ip': None,
            'port': None
        }

    # 成功応答 (state=2) としてトークンを返す
    send_tcrp_response(conn, room_name, 1, 2,
                       len(token), token.encode('utf-8'))
    print(f"[TCP] Room '{room_name}' created by '{username}' (token={token})")


def handle_join_room(conn, room_name, username, password):
    """
    既存ルーム参加
    """
    with lock:
        if room_name not in rooms or not rooms[room_name]['active']:
            send_tcrp_response(conn, room_name, 2, 1, 0, b"ROOM_NOT_FOUND")
            return
        # パスワードチェック
        if rooms[room_name]['password'] != password:
            send_tcrp_response(conn, room_name, 2, 1, 0, b"WRONG_PASSWORD")
            return

        # トークン発行
        token = generate_token()
        rooms[room_name]['participants'][token] = {
            'username': username,
            'ip': None,
            'last_active': time.time()
        }
        token_map[token] = {
            'room': room_name,
            'username': username,
            'ip': None,
            'port': None
        }

    send_tcrp_response(conn, room_name, 2, 2,
                       len(token), token.encode('utf-8'))
    print(f"[TCP] Room '{room_name}' joined by '{username}' (token={token})")


def send_tcrp_response(conn, room_name, operation, state, payload_size, payload_bytes):
    """
    TCRP 用の応答パケットを送信
    """
    room_name_bytes = room_name.encode('utf-8')
    roomNameSize = len(room_name_bytes)
    header = build_tcrp_header(roomNameSize, operation, state, payload_size)
    body = room_name_bytes + payload_bytes
    conn.sendall(header + body)


def tcp_server_loop():
    """
    TCP サーバループ: TCRP ハンドシェイク受け付け
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((TCP_HOST, TCP_PORT))
        s.listen(5)
        print(f"[TCP] Listening on {TCP_HOST}:{TCP_PORT} ...")

        while True:
            conn, addr = s.accept()
            print(f"[TCP] Connection from {addr}")
            threading.Thread(target=handle_tcp_client, args=(
                conn, addr), daemon=True).start()


def udp_server_loop():
    """
    UDP サーバループ: チャットメッセージ受け取り & ブロードキャスト
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((TCP_HOST, UDP_PORT))
        print(f"[UDP] Listening on {TCP_HOST}:{UDP_PORT} ...")

        while True:
            try:
                data, addr = s.recvfrom(UDP_BUFFER_SIZE)
            except OSError:
                break

            if not data:
                continue

            # パケット解析
            roomNameSize = data[0]
            tokenSize = data[1]
            offset = 2

            room_name_bytes = data[offset: offset + roomNameSize]
            offset += roomNameSize

            token_bytes = data[offset: offset + tokenSize]
            offset += tokenSize

            message_bytes = data[offset:]

            try:
                room_name = room_name_bytes.decode('utf-8')
                token = token_bytes.decode('utf-8')
                message = message_bytes.decode('utf-8')
            except:
                continue

            with lock:
                # token が有効か
                if token not in token_map:
                    continue
                mapped_room = token_map[token]['room']
                if mapped_room != room_name:
                    continue
                if not rooms.get(room_name, {}).get('active', False):
                    continue

                # IP, Port 未設定なら登録
                if token_map[token]['ip'] is None:
                    token_map[token]['ip'] = addr[0]
                if token_map[token]['port'] is None:
                    token_map[token]['port'] = addr[1]

                # IP が一致するか (仕様: トークンと IP の組み合わせが合わないと無視)
                if token_map[token]['ip'] != addr[0]:
                    continue
                # (必要に応じてポートの変化も許容 or 不許容にする)

                # last_active 更新
                rooms[room_name]['participants'][token]['last_active'] = time.time()
                username = rooms[room_name]['participants'][token]['username']

            print(f"[UDP] Room={room_name}, User={
                  username}, addr={addr}: {message}")

            # ブロードキャスト
            broadcast_udp_message(s, room_name, username, message)


def broadcast_udp_message(sock, room_name, username, message):
    """
    同じルームの全参加者に (username: message) を送信
    """
    with lock:
        if room_name not in rooms or not rooms[room_name]['active']:
            return

        send_data = f"{username}: {message}".encode('utf-8')

        for tkn in rooms[room_name]['participants'].keys():
            # 送信先の IP, Port を token_map から取得
            ip = token_map[tkn].get('ip')
            port = token_map[tkn].get('port')
            if ip and port:
                recipient_addr = (ip, port)
                try:
                    sock.sendto(send_data, recipient_addr)
                except:
                    pass


def cleanup_rooms_loop():
    """
    定期的にルームや参加者のタイムアウト処理を実行
    """
    while True:
        time.sleep(5)
        now = time.time()

        with lock:
            for room_name, room_info in list(rooms.items()):
                if not room_info['active']:
                    continue

                # ホストがいなければルームを終了
                host_token = room_info['host_token']
                if host_token not in room_info['participants']:
                    close_room(room_name)
                    continue

                # 参加者の last_active が一定時間超過なら削除
                remove_list = []
                for tkn, pinfo in room_info['participants'].items():
                    if (now - pinfo['last_active']) > 60:  # 60秒以上アイドル
                        remove_list.append(tkn)

                for tkn in remove_list:
                    print(f"[CLEANUP] Removing inactive participant {
                          tkn} in {room_name}")
                    del room_info['participants'][tkn]
                    if tkn in token_map:
                        del token_map[tkn]

                # ホストが消えたか再チェック
                if host_token not in room_info['participants']:
                    close_room(room_name)


def close_room(room_name):
    """
    ルームをクローズし、関連するトークンを削除
    """
    print(f"[CLEANUP] Closing room {room_name}")
    if room_name not in rooms:
        return

    for tkn in list(rooms[room_name]['participants'].keys()):
        if tkn in token_map:
            del token_map[tkn]
    rooms[room_name]['participants'].clear()
    rooms[room_name]['active'] = False


def main():
    print("=== TCRP + UDP Chat Server (Stage 2) - with port tracking ===")
    # スレッド起動
    threading.Thread(target=tcp_server_loop, daemon=True).start()
    threading.Thread(target=udp_server_loop, daemon=True).start()
    threading.Thread(target=cleanup_rooms_loop, daemon=True).start()

    # メインスレッドは単純に待機
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")


if __name__ == "__main__":
    main()
