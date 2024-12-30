#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import struct
import json
import sys
import os
import time

MMP_HEADER_SIZE = 8

"""
MMP 送信時:
  ヘッダ(8バイト) = [2bytes:json_size][1byte:media_type_size][5bytes:payload_size]
  ボディ = [JSON (json_sizeバイト)] + [media_type (media_type_sizeバイト)] + [payload (payload_sizeバイト)]
"""


def main():

    host = "127.0.0.1"
    port = 8000

    print("=== MMP Client ===")
    print("Operations:")
    print("1) compress  -> (bitrate)   e.g. 800k")
    print("2) resize    -> (width,height) e.g. 1280,720")
    print("3) aspect    -> (aspect)    e.g. 16:9")
    print("4) audio     -> (extract mp3)")
    print("5) gifwebm   -> (start, duration, output_format=gif|webm)")
    choice = input("Select operation [1..5]: ").strip()
    if choice not in ['1', '2', '3', '4', '5']:
        print("Invalid choice.")
        return

    operation_map = {
        '1': 'compress',
        '2': 'resize',
        '3': 'aspect',
        '4': 'audio',
        '5': 'gifwebm'
    }
    operation = operation_map[choice]

    media_path = "sample.mp4"
    if not os.path.isfile(media_path):
        print("File not found.")
        return

    # パラメータ入力
    req_json = {"operation": operation}
    if operation == "compress":
        bitrate = input("Bitrate? (e.g. 800k): ").strip()
        if not bitrate:
            bitrate = "800k"
        req_json["bitrate"] = bitrate
    elif operation == "resize":
        width = input("Width? (e.g. 1280): ").strip()
        height = input("Height? (e.g. 720): ").strip()
        req_json["width"] = int(width) if width.isdigit() else 1280
        req_json["height"] = int(height) if height.isdigit() else 720
    elif operation == "aspect":
        aspect = input("Aspect ratio? (e.g. 16:9): ").strip()
        if not aspect:
            aspect = "16:9"
        req_json["aspect"] = aspect
    elif operation == "gifwebm":
        start = input("Start time (seconds)? e.g. 0: ").strip()
        duration = input("Duration (seconds)? e.g. 5: ").strip()
        out_fmt = input("Output format [gif|webm]? ").strip()
        req_json["start"] = float(start) if start else 0
        req_json["duration"] = float(duration) if duration else 5
        req_json["output_format"] = out_fmt if out_fmt in [
            "gif", "webm"] else "gif"

    # 送信前 JSON 作成
    json_bytes = json.dumps(req_json).encode('utf-8')
    json_size = len(json_bytes)

    # メディアタイプは拡張子から推定
    ext = os.path.splitext(media_path)[1].lstrip('.')  # mp4, mov, mkv, etc.
    if not ext:
        ext = "mp4"
    media_type_bytes = ext.encode('utf-8')
    media_type_size = len(media_type_bytes)

    # ペイロード準備
    with open(media_path, 'rb') as f:
        file_data = f.read()
    payload_size = len(file_data)

    # MMP ヘッダ作成
    #  [2bytes: json_size] [1byte: media_type_size] [5bytes: payload_size]
    #  5 bytes of payload_size: we store it in 8 bytes then take the last 5
    header_part1 = struct.pack('!HB', json_size, media_type_size)
    payload_8 = struct.pack('!Q', payload_size)   # 64-bit
    payload_5 = payload_8[3:]  # 後ろ5バイトを抽出
    mmp_header = header_part1 + payload_5

    # サーバへ送信
    print(f"[INFO] Connecting to {host}:{port}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        # 送信
        s.sendall(mmp_header)
        s.sendall(json_bytes)
        s.sendall(media_type_bytes)
        s.sendall(file_data)
        print("[INFO] Request sent. Waiting for response...")

        # サーバ応答を受信: まずヘッダ (8バイト)
        resp_header = recv_exact(s, MMP_HEADER_SIZE)
        if not resp_header:
            print("[ERROR] No response header.")
            return

        r_json_size, r_media_type_size = struct.unpack('!HB', resp_header[:3])
        r_payload_size = struct.unpack(
            '!Q', b'\x00\x00\x00' + resp_header[3:8])[0]

        # JSON
        resp_json_bytes = recv_exact(
            s, r_json_size) if r_json_size > 0 else None
        resp_json = {}
        if resp_json_bytes:
            try:
                resp_json = json.loads(resp_json_bytes.decode('utf-8'))
            except:
                pass

        # メディアタイプ
        r_media_type_bytes = recv_exact(
            s, r_media_type_size) if r_media_type_size > 0 else b""
        r_media_type = r_media_type_bytes.decode(
            'utf-8') if r_media_type_bytes else ""

        if r_payload_size == 0:
            # エラーの場合、JSON にエラー情報が入っているはず
            print("[ERROR] Server responded with error.")
            print(" Details:", resp_json)
            return
        else:
            # ファイル受信
            out_data = recv_exact(s, r_payload_size)
            if not out_data:
                print("[ERROR] Failed to receive output file data.")
                return

            # 保存ファイル名
            out_filename = f"result_{int(time.time())}.{r_media_type}"
            with open(out_filename, "wb") as fout:
                fout.write(out_data)

            print("[INFO] Received output file saved as:", out_filename)
            print("[INFO] Response JSON:", resp_json)


def recv_exact(sock, size):
    """
    指定サイズを正確に受信する
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
