import socket


def start_client(host='localhost', port=8000):
    # ソケットを作成
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        # サーバに接続
        client_socket.connect((host, port))
        print(f"[INFO] サーバ({host}:{port})に接続しました。")

        while True:
            # コマンドラインからメッセージを入力
            message = input("メッセージを入力してください (終了: q または quit): ")

            # 終了用コマンドか判定
            if message.lower() in ('q', 'quit'):
                print("[INFO] 接続を終了します。")
                break

            # サーバに送信
            client_socket.sendall(message.encode('utf-8'))

            # サーバからの返答を受け取る
            data = client_socket.recv(1024)
            if not data:
                print("[ERROR] サーバからの応答がありません。")
                break

            # サーバのメッセージをデコードして表示
            response = data.decode('utf-8')
            print(f"[RECV] サーバからの返信: {response}")


if __name__ == "__main__":
    start_client()
