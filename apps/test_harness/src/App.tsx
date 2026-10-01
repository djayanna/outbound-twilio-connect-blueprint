import { useState } from "react";

export function App() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [log, setLog] = useState<string[]>([]);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const payload = JSON.parse(text);
    const posted: any[] = [];
    for (const job of payload.jobs ?? []) {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(job),
      });
      const body = await res.json();
      posted.push(body);
      setLog((l) => [...l, `POST /jobs ${job.id} → ${body?.decision?.outcome ?? res.status}`]);
    }
    setJobs(posted);
  }

  return (
    <div style={{ fontFamily: "system-ui", padding: 24 }}>
      <h1>test harness</h1>
      <input type="file" accept="application/json" onChange={onUpload} />
      <h2>recent posts</h2>
      <pre style={{ background: "#f6f6f6", padding: 12 }}>{log.join("\n")}</pre>
      <h2>jobs</h2>
      <pre style={{ background: "#f6f6f6", padding: 12 }}>{JSON.stringify(jobs, null, 2)}</pre>
    </div>
  );
}
