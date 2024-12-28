const net = require("net");

// 接続先 (Python サーバ)
const HOST = "127.0.0.1";
const PORT = 4000;

// 例として、複数のリクエストを順に送る
const requests = [
  {
    method: "floor",
    params: [42.7],
    param_types: ["float"],
    id: 1,
  },
  {
    method: "nroot",
    params: [2, 9],
    param_types: ["int", "int"],
    id: 2,
  },
  {
    method: "reverse",
    params: ["Hello"],
    param_types: ["string"],
    id: 3,
  },
  {
    method: "validAnagram",
    params: ["listen", "silent"],
    param_types: ["string", "string"],
    id: 4,
  },
  {
    method: "sort",
    params: [["banana", "apple", "orange"]],
    param_types: ["string[]"],
    id: 5,
  },
  {
    method: "unknownMethod",
    params: [],
    param_types: [],
    id: 6,
  },
];

const client = new net.Socket();

client.connect(PORT, HOST, () => {
  console.log(`[INFO] Connected to server ${HOST}:${PORT}`);

  // 順番にリクエストを送信 (適当にタイミングをずらしてみる)
  let i = 0;

  const interval = setInterval(() => {
    if (i >= requests.length) {
      clearInterval(interval);

      // 全部送信し終わったら少し待って接続を終了
      setTimeout(() => {
        console.log("[INFO] Close client socket");
        client.end();
      }, 500);
      return;
    }

    const reqJson = JSON.stringify(requests[i]);
    console.log("[SEND]", reqJson);
    client.write(reqJson);
    i++;
  }, 1000);
});

// サーバからのデータ受信
client.on("data", (data) => {
  // サーバが返す JSON をパースして表示
  try {
    const response = JSON.parse(data.toString());
    console.log("[RECV]", response);
  } catch (e) {
    console.error("[ERROR] JSON parse failed:", e, data.toString());
  }
});

// エラー処理
client.on("error", (err) => {
  console.error("[ERROR] ", err);
});
