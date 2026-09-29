// Frontend helper: submit a prompt to Django, then poll until the laptop finishes.
//
//   const answer = await askLocalAI("이 메모를 요약해줘: ...", {
//     onStatus: (status, seconds) => (statusEl.textContent = `${status} · ${seconds}초`),
//   });

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : "";
}

async function askLocalAI(prompt, { onStatus, intervalMs = 3000, timeoutMs = 10 * 60 * 1000, baseUrl = "/localai" } = {}) {
  const submit = await fetch(`${baseUrl}/jobs/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
    body: JSON.stringify({ prompt }),
  });
  const job = await submit.json();
  if (!submit.ok) throw new Error(job.error || "요청 실패");

  const started = Date.now();
  onStatus?.("queued", 0);
  while (Date.now() - started < timeoutMs) {
    await new Promise((r) => setTimeout(r, intervalMs));
    const res = await fetch(`${baseUrl}/jobs/${job.job_id}/`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "조회 실패");
    onStatus?.(data.status, Math.round((Date.now() - started) / 1000));
    if (data.status === "done") return data.response;
    if (data.status === "error") throw new Error(data.error);
  }
  throw new Error("응답 시간이 너무 오래 걸립니다. 잠시 후 다시 시도해 주세요.");
}
