#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import struct
import json
import subprocess
import os
import time
import tempfile

HOST = '0.0.0.0'
PORT = 8000
BACKLOG = 5

# MMP ヘッダのサイズ：8 バイト
MMP_HEADER_SIZE = 8
"""
ヘッダ構造 (8 bytes):
  [2 bytes: json_size (unsigned short)]
  [1 byte: media_type_size (0~4)]
  [5 bytes: payload_size (0~1TB)]
"""

# 同時処理制限: IP アドレス毎に1件のみ許可
current_tasks = {}  # key=ip, value=bool (True=処理中)

lock = threading.Lock()


def main():
    print(f"=== MMP Media Server running on {HOST}:{PORT} ===")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(BACKLOG)
        print("[INFO] Listening for connections...")

        try:
            while True:
                conn, addr = s.accept()
                threading.Thread(target=handle_client, args=(
                    conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            print("\n[INFO] Server shutdown requested.")


def handle_client(conn, addr):
    """
    クライアント1つのセッションを処理
    """
    ip = addr[0]
    print(f"[INFO] Connected: {addr}")
    with lock:
        if current_tasks.get(ip, False):
            # すでにこの IP で処理中
            send_mmp_error(conn, "ERR_CONCURRENT_TASK",
                           "Another task is running", "Wait or cancel previous task")
            conn.close()
            return
        else:
            current_tasks[ip] = True

    try:
        # 1) MMP ヘッダ受信 (8バイト)
        header = recv_exact(conn, MMP_HEADER_SIZE)
        if not header:
            print("[ERROR] No header received.")
            return

        # ヘッダ分解
        # 2 bytes: json_size (ushort), 1 byte: media_type_size, 5 bytes: payload_size
        json_size, media_type_size = struct.unpack('!HB', header[:3])
        payload_size = struct.unpack('!Q', b'\x00\x00\x00' + header[3:8])[0]
        # 上のように 5 バイトを 8 バイトに拡張して 64bit (Q) で読み込む
        #  b'\x00\x00\x00' + (5バイト) => 合計8バイト

        # 2) ボディ受信
        # JSON 部分
        json_bytes = recv_exact(conn, json_size)
        if not json_bytes and json_size > 0:
            print("[ERROR] JSON part not received fully.")
            return

        # メディアタイプ
        media_type_bytes = recv_exact(conn, media_type_size)
        if not media_type_bytes and media_type_size > 0:
            print("[ERROR] MediaType part not received fully.")
            return

        # ペイロード
        file_bytes = recv_exact(conn, payload_size)
        if not file_bytes and payload_size > 0:
            print("[ERROR] Payload not received fully.")
            return

        # JSON パース
        try:
            json_str = json_bytes.decode('utf-8') if json_bytes else "{}"
            request_info = json.loads(json_str)
        except Exception as e:
            print("[ERROR] JSON parse error:", e)
            send_mmp_error(conn, "ERR_JSON", "Invalid JSON format",
                           "Check request JSON structure")
            return

        # メディアタイプ
        media_type = media_type_bytes.decode(
            'utf-8') if media_type_bytes else ""

        print(f"[DEBUG] JSON: {request_info}")
        print(f"[DEBUG] MediaType: {media_type}, payload_size={payload_size}")

        # 3) 一時ファイルに保存
        if payload_size > 0:
            temp_input = tempfile.NamedTemporaryFile(
                delete=False, suffix=f".{media_type}", prefix="input_", dir=".")
            input_path = temp_input.name
            temp_input.write(file_bytes)
            temp_input.close()
        else:
            input_path = None

        # 4) リクエストを処理 (FFMPEG)
        output_path = None
        try:
            output_path = process_media(request_info, input_path)
        except Exception as e:
            print(f"[ERROR] FFMPEG process failed: {e}")
            send_mmp_error(conn, "ERR_FFMPEG",
                           "Failed to process media", str(e))
            return

        # 5) 処理結果ファイルを MMP 形式で返却
        if output_path and os.path.isfile(output_path):
            # 返すファイルの拡張子をメディアタイプにする (例: mp4, mp3, webm, gif etc.)
            out_ext = os.path.splitext(output_path)[1].lstrip(".")  # 例: "mp4"
            with open(output_path, "rb") as f:
                out_data = f.read()

            resp_json = {
                "status": "OK",
                "message": "Conversion done",
                "operation": request_info.get("operation", "")
            }
            resp_json_bytes = json.dumps(resp_json).encode('utf-8')
            json_len = len(resp_json_bytes)
            out_type_bytes = out_ext.encode('utf-8')
            out_type_size = len(out_type_bytes)
            payload_len = len(out_data)

            # ヘッダ作成 (8バイト)
            # json_size (2bytes), media_type_size(1byte), payload_size(5bytes)
            header = struct.pack('!HB', json_len, out_type_size)
            # payload_size は 5 バイトに収まる形で作る
            # → 先頭3バイト捨てた64bit(8byte)を構築
            payload_5 = struct.pack('!Q', payload_len)[3:]  # 8バイトのうち後ろ5バイト
            header += payload_5

            # 送信: ヘッダ + JSON + メディアタイプ + ファイルデータ
            conn.sendall(header)
            conn.sendall(resp_json_bytes)
            conn.sendall(out_type_bytes)
            conn.sendall(out_data)
        else:
            send_mmp_error(
                conn, "ERR_NO_OUTPUT", "No output file was generated", "Check the FFMPEG parameters")

    finally:
        # クリーンアップ
        with lock:
            current_tasks[ip] = False
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
        if output_path and os.path.exists(output_path):
            os.remove(output_path)
        conn.close()
        print(f"[INFO] Disconnected: {addr}")


def process_media(request_info, input_path):
    """
    FFMPEG を使ってメディアを変換し、出力ファイルパスを返す。
    request_info には operation, 各種パラメータ (width, height, aspect, start, duration, etc.) が入っている想定。
    """
    if not input_path:
        raise ValueError("No input file provided.")

    operation = request_info.get("operation", "").lower()
    if not operation:
        raise ValueError("No operation specified.")

    # 出力ファイル（拡張子は ffmpeg コマンドからある程度推定）
    suffix_map = {
        "compress": ".mp4",
        "resize": ".mp4",
        "aspect": ".mp4",
        "audio": ".mp3",
        "gifwebm": ".gif",  # 後で request_info の output_format に応じて変える
    }

    out_suffix = suffix_map.get(operation, ".mp4")
    if operation == "gifwebm":
        fmt = request_info.get("output_format", "gif")
        if fmt not in ["gif", "webm"]:
            fmt = "gif"
        out_suffix = f".{fmt}"

    temp_out = tempfile.NamedTemporaryFile(
        delete=False, suffix=out_suffix, prefix="output_", dir=".")
    output_path = temp_out.name
    temp_out.close()  # ファイルを閉じて ffmpeg で書き込み可能に

    if operation == "compress":
        # 例: 単純にビットレートを落とす (800k) とか
        bitrate = request_info.get("bitrate", "800k")
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-b:v", bitrate,
            output_path
        ]
    elif operation == "resize":
        # 幅高さ指定
        width = request_info.get("width", 1280)
        height = request_info.get("height", 720)
        scale_str = f"{width}:{height}"
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={scale_str}",
            output_path
        ]
    elif operation == "aspect":
        # アスペクト比指定 (例: 16:9 → "16:9")
        aspect = request_info.get("aspect", "16:9")
        # scale で縦横どちらかを計算するか、あるいは setdar を使う等
        # 簡易的に setdar を使う例
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"setdar={aspect}",
            output_path
        ]
    elif operation == "audio":
        # 動画→音声抽出 (mp3)
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vn",   # no video
            "-acodec", "mp3",
            output_path
        ]
    elif operation == "gifwebm":
        # 時間範囲を切り出して GIF か WEBM
        start = request_info.get("start", 0)   # 秒
        duration = request_info.get("duration", 5)  # 秒
        fmt = request_info.get("output_format", "gif")  # "gif" or "webm"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", input_path,
            output_path
        ]
    else:
        raise ValueError(f"Unsupported operation: {operation}")

    # FFMPEG 実行
    print("[DEBUG] Running cmd:", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode('utf-8', errors='ignore'))

    return output_path


def send_mmp_error(conn, code, description, solution):
    """
    エラー時に JSON ({"error_code": code, "description":..., "solution":...}) を返す。
    MMP でメディアタイプサイズ＝0、ペイロードサイズ＝0 とする。
    """
    error_json = {
        "error_code": code,
        "description": description,
        "solution": solution
    }
    err_bytes = json.dumps(error_json).encode('utf-8')
    json_len = len(err_bytes)

    # ヘッダ: [2bytes:json_size][1byte:media_type_size=0][5bytes:payload_size=0]
    header = struct.pack('!HB', json_len, 0) + \
        b'\x00\x00\x00\x00\x00'  # payload=0

    conn.sendall(header)
    conn.sendall(err_bytes)
    # media_type_size=0 → 送らない
    # payload_size=0 → 送らない


def recv_exact(conn, size):
    """
    size バイト正確に受信するヘルパー
    """
    buf = b''
    while len(buf) < size:
        chunk = conn.recv(size - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


if __name__ == "__main__":
    main()
