import React, { useState } from "react";

// AES-GCM パラメータ
const AES_ALGORITHM = {
  name: "AES-GCM",
  length: 256,
};

// RSA-OAEP パラメータ
const RSA_PARAMS = {
  name: "RSA-OAEP",
  modulusLength: 2048,
  publicExponent: new Uint8Array([0x01, 0x00, 0x01]),
  hash: { name: "SHA-256" },
};

function App() {
  const [serverPubKeyPem, setServerPubKeyPem] = useState("");
  const [clientKeyPair, setClientKeyPair] = useState(null);
  const [clientId, setClientId] = useState("user123");
  const [file, setFile] = useState(null);
  const [encryptedResult, setEncryptedResult] = useState(null);
  const [encryptedKey, setEncryptedKey] = useState(null); // 新しいステート変数
  const [aesKey, setAesKey] = useState(null);

  // API サーバのベースURL
  const baseUrl = "http://localhost:8000";

  // 1) サーバ公開鍵取得
  const fetchServerPubKey = async () => {
    try {
      const res = await fetch(`${baseUrl}/public-key`);
      const data = await res.json();
      setServerPubKeyPem(data.serverPublicKey);
      alert("サーバ公開鍵を取得しました。");
    } catch (error) {
      console.error("Error fetching server public key:", error);
      alert("サーバ公開鍵の取得に失敗しました。");
    }
  };

  // 2) クライアント側で RSA キーペア生成
  const generateClientKeyPair = async () => {
    try {
      const keyPair = await window.crypto.subtle.generateKey(RSA_PARAMS, true, ["encrypt", "decrypt"]);
      setClientKeyPair(keyPair);
      alert("クライアント鍵ペアを生成しました。");
    } catch (error) {
      console.error("Error generating client key pair:", error);
      alert("クライアント鍵ペアの生成に失敗しました。");
    }
  };

  // 3) クライアント公開鍵をサーバに登録
  const sendClientPublicKey = async () => {
    if (!clientKeyPair) {
      alert("先に鍵ペアを生成してください。");
      return;
    }
    try {
      // 公開鍵を SPKI 形式でエクスポートし、PEM化
      const spki = await window.crypto.subtle.exportKey("spki", clientKeyPair.publicKey);
      const pubPem = spkiToPem(spki);

      const res = await fetch(`${baseUrl}/client-public-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clientId,
          publicKeyPem: pubPem,
        }),
      });
      const data = await res.json();
      if (data.error) {
        alert("公開鍵の登録に失敗しました: " + data.error);
      } else {
        alert("クライアント公開鍵をサーバに登録しました。");
      }
    } catch (error) {
      console.error("Error sending client public key:", error);
      alert("公開鍵の登録に失敗しました。");
    }
  };

  // 4) 動画ファイルを選択
  const handleFileChange = (e) => {
    if (e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  };

  // 5) 暗号化してアップロード
  const uploadEncrypted = async () => {
    if (!serverPubKeyPem || !clientKeyPair || !file) {
      alert("サーバ公開鍵、クライアント鍵ペア、またはファイルが不足しています。");
      return;
    }

    try {
      // サーバ公開鍵を CryptoKey にインポート
      const serverPublicKey = await importServerPublicKey(serverPubKeyPem);

      // AES鍵を生成
      const generatedAesKey = await window.crypto.subtle.generateKey(AES_ALGORITHM, true, ["encrypt", "decrypt"]);
      setAesKey(generatedAesKey);

      // ファイルをArrayBufferで読み込み
      const fileData = await file.arrayBuffer();

      // AES-GCMでファイルデータを暗号化
      const iv = window.crypto.getRandomValues(new Uint8Array(12)); // 96ビットのIV
      const encryptedArrayBuffer = await window.crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv: iv,
        },
        generatedAesKey,
        fileData
      );

      // encryptedArrayBuffer は Ciphertext + Tag の組み合わせ
      const encryptedDataBytes = new Uint8Array(encryptedArrayBuffer);
      const ciphertextBytes = encryptedDataBytes.slice(0, encryptedDataBytes.length - 16);
      const tagBytes = encryptedDataBytes.slice(encryptedDataBytes.length - 16);

      // Base64エンコード
      const ciphertextB64 = arrayBufferToBase64(ciphertextBytes.buffer);
      const tagB64 = arrayBufferToBase64(tagBytes.buffer);
      const ivB64 = arrayBufferToBase64(iv.buffer);

      // AES鍵をエクスポートし、バイナリデータとして取得
      const rawAesKey = await window.crypto.subtle.exportKey("raw", generatedAesKey);
      // RSA-OAEPでAES鍵を暗号化
      const encryptedAesKey = await window.crypto.subtle.encrypt(
        {
          name: "RSA-OAEP",
        },
        serverPublicKey,
        rawAesKey
      );
      const encryptedKeyB64 = arrayBufferToBase64(encryptedAesKey);

      // encryptedData を JSON オブジェクトとして作成
      const encryptedDataJson = JSON.stringify({
        nonce: ivB64,
        ciphertext: ciphertextB64,
        tag: tagB64,
      });

      // JSON 文字列をBase64エンコード
      const encryptedDataEncoded = arrayBufferToBase64(new TextEncoder().encode(encryptedDataJson));

      // サーバに送信するJSONデータ
      const payload = {
        clientId,
        encryptedKey: encryptedKeyB64,
        encryptedData: encryptedDataEncoded,
      };

      // サーバにPOSTリクエスト
      const res = await fetch(`${baseUrl}/upload-encrypted`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.error) {
        alert("アップロードエラー: " + data.error);
      } else {
        setEncryptedResult(data.encryptedResult);
        setEncryptedKey(data.encryptedKey); // encryptedKey を保存
        alert("サーバーからの暗号化済み結果を受信しました。");
      }
    } catch (error) {
      console.error("Error during encryption/upload:", error);
      alert("暗号化またはアップロード中にエラーが発生しました。");
    }
  };

  // 6) 結果を復号しダウンロード
  const decryptResult = async () => {
    if (!encryptedResult || !encryptedKey || !clientKeyPair) {
      alert("暗号化された結果、暗号化キー、またはクライアント鍵ペアがありません。");
      return;
    }

    try {
      // 暗号化されたAES鍵をBase64からArrayBufferに変換
      const encryptedAesKeyBytes = base64ToArrayBuffer(encryptedKey);
      // クライアント秘密鍵でAES鍵を復号
      const decryptedAesKey = await window.crypto.subtle.decrypt(
        {
          name: "RSA-OAEP",
        },
        clientKeyPair.privateKey,
        encryptedAesKeyBytes
      );

      // AES鍵をCryptoKeyオブジェクトにインポート
      const aesKey = await window.crypto.subtle.importKey(
        "raw",
        decryptedAesKey,
        {
          name: "AES-GCM",
        },
        true,
        ["decrypt"]
      );

      // 暗号化された結果をBase64からArrayBufferに変換
      const encryptedDataBytes = base64ToArrayBuffer(encryptedResult);

      // encryptedDataBytes は Base64 デコード後の JSON 文字列
      const encryptedDataJson = new TextDecoder().decode(encryptedDataBytes);
      const encryptedData = JSON.parse(encryptedDataJson);
      const nonce = base64ToArrayBuffer(encryptedData.nonce);
      const ciphertext = base64ToArrayBuffer(encryptedData.ciphertext);
      const tag = base64ToArrayBuffer(encryptedData.tag);

      // ciphertextとtagを結合
      const ciphertextWithTag = new Uint8Array(ciphertext.byteLength + tag.byteLength);
      ciphertextWithTag.set(new Uint8Array(ciphertext), 0);
      ciphertextWithTag.set(new Uint8Array(tag), ciphertext.byteLength);

      // AES-GCMでデータを復号
      const decryptedArrayBuffer = await window.crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv: new Uint8Array(nonce),
        },
        aesKey,
        ciphertextWithTag
      );

      // 復号したデータをBlobとして作成
      const blob = new Blob([decryptedArrayBuffer], { type: "audio/mpeg" });
      const url = URL.createObjectURL(blob);

      // ダウンロードリンクを作成してクリック
      const link = document.createElement("a");
      link.href = url;
      link.download = "converted_audio.mp3";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      alert("MP3ファイルを復号し、ダウンロードしました。");
    } catch (error) {
      console.error("Error during decryption:", error);
      alert("復号中にエラーが発生しました。");
    }
  };

  return (
    <div style={{ margin: "1rem" }}>
      <h1>RSA + ハイブリッド暗号化動画処理デモ</h1>
      <div>
        <button onClick={fetchServerPubKey}>1) サーバ公開鍵取得</button>
        {serverPubKeyPem && (
          <div>
            <h3>サーバ公開鍵:</h3>
            <pre>{serverPubKeyPem}</pre>
          </div>
        )}
      </div>
      <hr />
      <div>
        <button onClick={generateClientKeyPair}>2) クライアント鍵ペア生成</button>
      </div>
      <hr />
      <div>
        <input type="text" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="clientId" />
        <button onClick={sendClientPublicKey}>3) クライアント公開鍵をサーバに登録</button>
      </div>
      <hr />
      <div>
        <input type="file" accept="video/*" onChange={handleFileChange} />
        <button onClick={uploadEncrypted}>4) 暗号化してアップロード</button>
      </div>
      <hr />
      <div>
        <button onClick={decryptResult} disabled={!encryptedResult || !encryptedKey}>
          5) 結果を復号しダウンロード
        </button>
      </div>
    </div>
  );
}

// ============================================================
// ユーティリティ関数
// ============================================================

// PEM形式の公開鍵を CryptoKey にインポート
async function importServerPublicKey(pem) {
  const pemHeader = "-----BEGIN PUBLIC KEY-----";
  const pemFooter = "-----END PUBLIC KEY-----";
  const pemContents = pem
    .substring(pem.indexOf(pemHeader) + pemHeader.length, pem.indexOf(pemFooter))
    .replace(/\s/g, "");
  const binaryDer = base64ToArrayBuffer(pemContents);

  return await window.crypto.subtle.importKey(
    "spki",
    binaryDer,
    {
      name: "RSA-OAEP",
      hash: "SHA-256",
    },
    true,
    ["encrypt"]
  );
}

// SPKIバイナリを PEM形式に変換
function spkiToPem(spki) {
  const b64 = arrayBufferToBase64(spki);
  const pem = `-----BEGIN PUBLIC KEY-----\n${b64.match(/.{1,64}/g).join("\n")}\n-----END PUBLIC KEY-----\n`;
  return pem;
}

// ArrayBuffer を Base64に変換
function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary);
}

// Base64 を ArrayBufferに変換
function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

export default App;
