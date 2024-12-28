import socket
from faker import Faker


def start_server(host='localhost', port=8000):
    # Faker のインスタンスを生成
    faker = Faker()

    # ソケットを作成 (IPv4, TCP)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        # IPアドレスとポート番号をソケットに紐付け
        server_socket.bind((host, port))
        print(f"[INFO] サーバを起動しました: {host}:{port}")

        # 接続待ち (最大 1 つの未決接続をキューイング)
        server_socket.listen(1)
        print("[INFO] クライアントからの接続を待機しています...")

        # 無限ループでクライアントからの接続を待つ
        while True:
            # 接続が来たら受け付ける
            client_socket, addr = server_socket.accept()
            print(f"[INFO] 接続がありました: {addr}")

            # クライアントとの対話をハンドルする
            with client_socket:
                while True:
                    # クライアントからデータを受け取る (バイナリ)
                    data = client_socket.recv(1024)
                    if not data:
                        # クライアントが切断したとみなす
                        print("[INFO] クライアントが切断しました。")
                        break

                    # デコードしてメッセージを文字列化
                    message = data.decode('utf-8')
                    print(f"[RECV] クライアントからのメッセージ: {message}")

                    # faker で偽のメッセージや文章を生成して応答する
                    fake_response = faker.text(max_nb_chars=50)
                    print(f"[SEND] サーバからの返信: {fake_response}")

                    # クライアントに送信 (バイト列にエンコード)
                    client_socket.sendall(fake_response.encode('utf-8'))


if __name__ == "__main__":
    start_server()
