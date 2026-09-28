// 웹사이트/Node.js(18+)에서 호출하는 예시.
// 브라우저에서 직접 부를 경우 .env 의 CORS_ORIGINS 에 사이트 주소를 넣어야 합니다.
// 주의: 공개 웹페이지 JS에 API 키를 넣으면 누구나 볼 수 있습니다 → 가능하면 내 서버(백엔드)에서 호출하세요.

const URL = process.env.LOCALAPI_URL ?? "http://127.0.0.1:8000";
const KEY = process.env.LOCALAPI_KEY;
const headers = { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" };

// 1) 단순 호출
const res = await fetch(`${URL}/v1/generate`, {
  method: "POST",
  headers,
  body: JSON.stringify({ prompt: "이 문장을 존댓말로 바꿔줘: 내일 봐" }),
});
console.log((await res.json()).response);

// 2) 스트리밍 (OpenAI 호환 SSE) — 글자가 생성되는 대로 표시
const stream = await fetch(`${URL}/v1/chat/completions`, {
  method: "POST",
  headers,
  body: JSON.stringify({ stream: true, messages: [{ role: "user", content: "자기소개 3줄" }] }),
});
const reader = stream.body.getReader();
const decoder = new TextDecoder();
let buf = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  const lines = buf.split("\n");
  buf = lines.pop();
  for (const line of lines) {
    if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
    process.stdout.write(JSON.parse(line.slice(6)).choices?.[0]?.delta?.content ?? "");
  }
}
console.log();

// 3) OpenAI SDK를 그대로 쓰고 싶다면:
//   import OpenAI from "openai";
//   const client = new OpenAI({ baseURL: `${URL}/v1`, apiKey: KEY });
//   await client.chat.completions.create({ model: "qwen3.5:4b", messages: [...] });
