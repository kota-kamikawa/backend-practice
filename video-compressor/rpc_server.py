# rpc_server.py
import socket
import threading
import json
import math
from rpc_functions import floor_func, nroot, reverse_str, valid_anagram, sort_strings

# サーバが提供するメソッド (string -> callable)
RPC_METHODS = {
    "floor": floor_func,
    "nroot": nroot,
    "reverse": reverse_str,
    "validAnagram": valid_anagram,
    "sort": sort_strings
}


def handle_client(client_socket, address):
    """クライアントとの通信を担当する関数 (スレッドで実行想定)"""
    print(f"[INFO] Client connected: {address}")
    with client_socket:
        while True:
            data = client_socket.recv(4096)
            if not data:
                print(f"[INFO] Client disconnected: {address}")
                break

            # JSON をパース
            try:
                request = json.loads(data.decode('utf-8'))
            except json.JSONDecodeError as e:
                # JSON が壊れている場合はエラー応答
                error_response = {
                    "id": None,
                    "error": f"JSON decode error: {str(e)}"
                }
                client_socket.sendall(json.dumps(
                    error_response).encode('utf-8'))
                continue

            # リクエストから method / params / param_types / id を取得
            method = request.get("method")
            params = request.get("params", [])
            param_types = request.get("param_types", [])
            request_id = request.get("id")

            # メソッドが辞書に存在するか確認
            if method not in RPC_METHODS:
                error_response = {
                    "id": request_id,
                    "error": f"Method '{method}' not found."
                }
                client_socket.sendall(json.dumps(
                    error_response).encode('utf-8'))
                continue

            # パラメータの型変換を行う (簡易的)
            # param_types = ["int", "float", "string", "bool", ...] などを想定
            try:
                converted_params = []
                for p, t in zip(params, param_types):
                    if t == "int":
                        converted_params.append(int(p))
                    elif t == "float" or t == "double":
                        converted_params.append(float(p))
                    elif t == "string":
                        converted_params.append(str(p))
                    elif t == "bool":
                        # 文字列 "true"/"false" で来るかどうかは要設計
                        # ここでは Python の真偽値に変換する例
                        converted_params.append(bool(p))
                    elif t == "string[]":
                        # p は配列前提
                        if not isinstance(p, list):
                            raise ValueError("Expected list of strings")
                        str_list = [str(s) for s in p]
                        converted_params.append(str_list)
                    else:
                        # それ以外は未対応としてエラー
                        raise ValueError(f"Unsupported param type: {t}")
            except Exception as e:
                error_response = {
                    "id": request_id,
                    "error": f"Parameter type conversion error: {str(e)}"
                }
                client_socket.sendall(json.dumps(
                    error_response).encode('utf-8'))
                continue

            # RPC 関数実行
            func = RPC_METHODS[method]
            try:
                result = func(*converted_params)
                # 結果の型を適宜判定 (細かくやるなら type(result) を見て分岐)
                result_type_str = type(result).__name__

                # JSON で送るため、list や bool などの場合も文字列化不要かもしれないが
                # ここでは一律文字列にせず、そのまま JSON 化
                response = {
                    "results": result,
                    "result_type": result_type_str,
                    "id": request_id
                }

            except Exception as e:
                # 関数内部でエラーが起きた場合
                response = {
                    "id": request_id,
                    "error": str(e)
                }

            # クライアントに返却 (JSON 化)
            client_socket.sendall(json.dumps(response).encode('utf-8'))


def start_server(host='127.0.0.1', port=4000):
    """サーバを起動し、クライアントからの接続を待受ける"""
    print(f"[INFO] Starting RPC Server on {host}:{port}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen()

        print("[INFO] Server listening for connections...")

        while True:
            client_socket, address = server_socket.accept()
            # スレッドで処理を並列化
            thread = threading.Thread(
                target=handle_client, args=(client_socket, address))
            thread.daemon = True
            thread.start()


if __name__ == "__main__":
    start_server()
