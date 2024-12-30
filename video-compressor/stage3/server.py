#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
import os
import subprocess
import tempfile

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

# cryptography ライブラリ (RSA と AES を扱う)
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# CORS ミドルウェアをインポート
from fastapi.middleware.cors import CORSMiddleware

# Uvicorn サーバを起動するための import (mainブロックで使用)
import uvicorn

# ============================================================
# データモデル
# ============================================================


class ClientPublicKeyModel(BaseModel):
    """
    クライアントから公開鍵を送信する際に使うデータモデル
    """
    clientId: str
    publicKeyPem: str


class EncryptedUploadModel(BaseModel):
    """
    クライアントから暗号化された共通鍵とデータをアップロードする際のデータモデル
    """
    clientId: str
    encryptedKey: str  # Base64 文字列
    encryptedData: str  # Base64 文字列（Base64エンコードされたJSON形式）


# ============================================================
# FastAPI アプリケーション本体
# ============================================================
app = FastAPI()

# CORS 設定
origins = [
    "http://localhost:5173",  # React (Vite) クライアントのオリジン
    # 必要に応じて他のオリジンを追加
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,           # 許可するオリジン
    allow_credentials=True,          # クッキーなどの資格情報を許可
    allow_methods=["*"],             # 許可するHTTPメソッド（全て）
    allow_headers=["*"],             # 許可するHTTPヘッダー（全て）
)

# サーバ起動時に RSA 鍵ペア（サーバ用）を作成
# ※ 実運用ではファイルに保存し、再起動時に読み込むことを推奨
server_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048
)
server_public_key = server_private_key.public_key()

# クライアントごとの公開鍵を保持するための辞書
#   key: clientId (str)
#   value: 公開鍵オブジェクト (cryptography.hazmat.primitives.asymmetric.rsa.RSAPublicKey)
client_public_keys = {}


# ============================================================
# ハイブリッド暗号化のヘルパー関数
# ============================================================
def decrypt_aes_key(encrypted_key: bytes) -> bytes:
    """
    RSA-OAEPで暗号化されたAES鍵を復号します。
    """
    aes_key = server_private_key.decrypt(
        encrypted_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return aes_key


def encrypt_aes_key(aes_key: bytes, client_pubkey) -> bytes:
    """
    AES鍵をクライアントの公開鍵でRSA-OAEPを用いて暗号化します。
    """
    encrypted_aes_key = client_pubkey.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return encrypted_aes_key


def decrypt_data_aes(aes_key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    """
    AES-GCMモードでデータを復号します。
    """
    decryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(nonce, tag),
        backend=default_backend()
    ).decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext


def encrypt_data_aes(aes_key: bytes, plaintext: bytes) -> dict:
    """
    AES-GCMモードでデータを暗号化します。
    戻り値は辞書形式で、`nonce`, `ciphertext`, `tag` を含みます。
    """
    nonce = os.urandom(12)  # 96ビットのnonce
    encryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(nonce),
        backend=default_backend()
    ).encryptor()
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    return {
        "nonce": base64.b64encode(nonce).decode('utf-8'),
        "ciphertext": base64.b64encode(ciphertext).decode('utf-8'),
        "tag": base64.b64encode(encryptor.tag).decode('utf-8')
    }


# ============================================================
# FFmpeg で MP3 に変換する関数
# ============================================================
def do_ffmpeg_convert_to_mp3(input_path: str) -> str:
    """
    FFmpegを使って入力動画から音声を抽出し、
    MP3ファイルを生成して返す。
    """
    # 出力用の一時ファイルを作成
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        output_path = tmp.name

    # ffmpeg コマンド:
    #  -vn        : 映像を無視
    #  -acodec mp3: 音声を mp3 でエンコード
    #  -b:a 128k  : 音声ビットレートを128kbpsに設定
    cmd = [
        "ffmpeg",
        "-y",            # 上書き
        "-i", input_path,
        "-vn",           # 動画無視
        "-acodec", "mp3",
        "-b:a", "128k",  # ビットレート設定
        output_path
    ]

    # 実行
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        # エラー発生時、stderr を表示するなど
        error_msg = proc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"FFmpeg failed: {error_msg}")

    return output_path


# ============================================================
# エンドポイント
# ============================================================

@app.get("/public-key")
def get_server_public_key():
    """
    サーバの公開鍵を PEM 形式で返す。
    クライアントはこの鍵を使ってAES鍵を暗号化します。
    """
    # 公開鍵を PEM (SubjectPublicKeyInfo) としてエンコード
    pub_bytes = server_public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return {"serverPublicKey": pub_bytes.decode("utf-8")}


@app.post("/client-public-key")
def set_client_public_key(data: ClientPublicKeyModel):
    """
    クライアント側で生成した公開鍵をサーバに登録するエンドポイント。
    """
    client_id = data.clientId
    public_key_pem = data.publicKeyPem

    if not public_key_pem:
        return {"error": "No public key provided"}

    try:
        pubkey = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8"))
        client_public_keys[client_id] = pubkey
        return {"status": "ok"}
    except Exception as e:
        return {"error": f"Failed to load public key: {e}"}


@app.post("/upload-encrypted")
def upload_encrypted(payload: EncryptedUploadModel):
    """
    クライアントが暗号化した共通鍵とデータを送信してくるエンドポイント。
    1. サーバは自身の秘密鍵で共通鍵を復号
    2. 復号した共通鍵でデータを復号
    3. 復号データ（動画ファイル）をFFmpegでMP3に変換
    4. 変換後のMP3データを新しいAES鍵で暗号化
    5. 新しいAES鍵をクライアントの公開鍵で暗号化
    6. 暗号化されたAES鍵と暗号化データを返す
    """
    client_id = payload.clientId
    encrypted_key_b64 = payload.encryptedKey
    encrypted_data_b64 = payload.encryptedData

    # クライアントIDチェック
    if client_id not in client_public_keys:
        return {"error": f"clientId '{client_id}' not recognized. Please POST /client-public-key first."}

    # Base64 -> bytes
    try:
        encrypted_key_bytes = base64.b64decode(encrypted_key_b64)
        encrypted_data_bytes = base64.b64decode(encrypted_data_b64)
    except Exception as e:
        return {"error": f"Invalid Base64 data: {e}"}

    # サーバ秘密鍵でAES鍵を復号
    try:
        aes_key = decrypt_aes_key(encrypted_key_bytes)
    except Exception as e:
        return {"error": f"Decryption of AES key failed: {e}"}

    # AES鍵でデータを復号
    try:
        # encrypted_data_bytes は Base64 デコード後の JSON 文字列
        encrypted_data_json = encrypted_data_bytes.decode('utf-8')
        encrypted_data = json.loads(encrypted_data_json)
        nonce = base64.b64decode(encrypted_data['nonce'])
        ciphertext = base64.b64decode(encrypted_data['ciphertext'])
        tag = base64.b64decode(encrypted_data['tag'])
    except Exception as e:
        return {"error": f"Parsing encrypted data failed: {e}"}

    try:
        plaintext = decrypt_data_aes(aes_key, nonce, ciphertext, tag)
    except Exception as e:
        return {"error": f"AES decryption failed: {e}"}

    # 取得したプレーンテキストが動画ファイルのバイナリデータと想定
    input_path = ""
    try:
        # 一時ファイルに書き出し
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            input_path = tmp.name
            tmp.write(plaintext)

        # FFmpegでMP3に変換
        output_path = do_ffmpeg_convert_to_mp3(input_path)

        # 変換後ファイルを読み込み
        with open(output_path, "rb") as fin:
            mp3_data = fin.read()

        # 新しいAES鍵を生成
        new_aes_key = os.urandom(32)  # 256ビットのAES鍵

        # MP3データをAES-GCMで暗号化
        encrypt_result = encrypt_data_aes(new_aes_key, mp3_data)

        # 新しいAES鍵をクライアントの公開鍵で暗号化
        client_pubkey = client_public_keys[client_id]
        encrypted_new_aes_key = encrypt_aes_key(new_aes_key, client_pubkey)
        encrypted_new_aes_key_b64 = base64.b64encode(
            encrypted_new_aes_key).decode("utf-8")

        # 暗号化データをJSON形式にまとめ、Base64エンコード
        encrypted_data_to_send = json.dumps(encrypt_result)
        encrypted_data_to_send_b64 = base64.b64encode(
            encrypted_data_to_send.encode('utf-8')).decode('utf-8')

        # レスポンス
        return {
            "status": "ok",
            "encryptedKey": encrypted_new_aes_key_b64,
            "encryptedResult": encrypted_data_to_send_b64
        }

    except Exception as e:
        return {"error": f"Processing error: {e}"}
    finally:
        # 後始末（入力ファイル）
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
        # 後始末（出力ファイル）
        if "output_path" in locals() and output_path and os.path.exists(output_path):
            os.remove(output_path)


# ============================================================
# メインブロック (サーバ起動)
# ============================================================
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
