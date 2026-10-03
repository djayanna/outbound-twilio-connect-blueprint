import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

type JobRun = {
  job_id: string;
  attempt: number;
  status: string;
  twilio_call_sid: string | null;
  twilio_message_sid: string | null;
  started_at: string | null;
  ended_at: string | null;
  terminal_reason: string | null;
};
type JobRow = { id: string; status: string; scenario: string; channel: string; to: string };
type AuditEvt = { at: string; actor: string; action: string; subject: string; data: string };

const SCENARIOS = ["appointment-confirmation", "payment-reminder", "promotion"] as const;

async function postJob(body: unknown): Promise<{ decision: { outcome: string; reason: string | null } }> {
  const r = await fetch("/api/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

function nowId() {
  return `job-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

export function App() {
  const [tab, setTab] = useState<"single" | "batch" | "bulk">("single");
  const [log, setLog] = useState<string[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tick = async () => {
      try {
        const r = await fetch("/api/jobs").then((x) => x.json());
        setJobs(r.jobs ?? []);
      } catch {}
    };
    tick();
    const h = setInterval(tick, 2000);
    return () => clearInterval(h);
  }, []);

  function appendLog(line: string) {
    setLog((l) => [...l.slice(-199), `${new Date().toLocaleTimeString()}  ${line}`]);
    requestAnimationFrame(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight));
  }

  return (
    <div className="app">
      <main>
        <h1>test harness</h1>
        <div className="tabs" role="tablist">
          {(["single", "batch", "bulk"] as const).map((t) => (
            <button
              key={t}
              className="tab"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>

        <section className="panel">
          {tab === "single" && <SingleForm onPost={appendLog} />}
          {tab === "batch" && <BatchForm onPost={appendLog} />}
          {tab === "bulk" && <BulkForm onPost={appendLog} />}
        </section>

        <section className="panel" style={{ marginTop: 16 }}>
          <h2>call history ({jobs.length})</h2>
          <div className="history">
            {jobs.map((j) => (
              <div
                key={j.id}
                className={`row${j.id === selected ? " selected" : ""}`}
                onClick={() => setSelected(j.id)}
              >
                <code>{j.id.slice(0, 10)}</code>
                <span>
                  {j.scenario} · {j.channel} · <code>{j.to}</code>
                </span>
                <span className={`badge ${j.status}`}>{j.status}</span>
              </div>
            ))}
          </div>
        </section>
      </main>

      <aside className="panel">
        <h2>inspector</h2>
        {selected ? <Inspector jobId={selected} /> : <p className="notice">click a row to inspect.</p>}
        <h2 style={{ marginTop: 24 }}>recent posts</h2>
        <div className="log" ref={logRef}>
          {log.join("\n")}
        </div>
      </aside>
    </div>
  );
}

function SingleForm({ onPost }: { onPost: (s: string) => void }) {
  const [to, setTo] = useState("+15551110001");
  const [channel, setChannel] = useState<"sms" | "voice">("sms");
  const [scenario, setScenario] = useState<string>(SCENARIOS[0]);
  const [ctx, setCtx] = useState("{}");
  const [busy, setBusy] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        let context: unknown;
        try {
          context = JSON.parse(ctx);
        } catch (err) {
          onPost(`context parse error: ${(err as Error).message}`);
          setBusy(false);
          return;
        }
        const id = nowId();
        const res = await postJob({ id, channel, to, scheduled_for: "now", scenario, context });
        onPost(`POST /jobs ${id} → ${res?.decision?.outcome ?? "?"}`);
        setBusy(false);
      }}
    >
      <label>
        to (E.164)
        <input value={to} onChange={(e) => setTo(e.target.value)} required />
      </label>
      <label>
        channel
        <select value={channel} onChange={(e) => setChannel(e.target.value as "sms" | "voice")}>
          <option value="sms">sms</option>
          <option value="voice">voice</option>
        </select>
      </label>
      <label>
        scenario
        <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
          {SCENARIOS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <label>
        context (JSON)
        <textarea value={ctx} onChange={(e) => setCtx(e.target.value)} />
      </label>
      <button className="primary" type="submit" disabled={busy}>
        {busy ? "posting…" : "submit"}
      </button>
    </form>
  );
}

function BatchForm({ onPost }: { onPost: (s: string) => void }) {
  const [numbers, setNumbers] = useState("+15551110001\n+15551110002\n+15551110003");
  const [channel, setChannel] = useState<"sms" | "voice">("sms");
  const [scenario, setScenario] = useState<string>(SCENARIOS[0]);
  const [busy, setBusy] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        const list = numbers.split(/\s+/).filter((n) => n.startsWith("+"));
        setBusy(true);
        for (const to of list) {
          const id = nowId();
          const res = await postJob({ id, channel, to, scheduled_for: "now", scenario, context: {} });
          onPost(`POST /jobs ${id} to ${to} → ${res?.decision?.outcome ?? "?"}`);
        }
        setBusy(false);
      }}
    >
      <label>
        numbers (one per line, E.164)
        <textarea value={numbers} onChange={(e) => setNumbers(e.target.value)} />
      </label>
      <label>
        channel
        <select value={channel} onChange={(e) => setChannel(e.target.value as "sms" | "voice")}>
          <option value="sms">sms</option>
          <option value="voice">voice</option>
        </select>
      </label>
      <label>
        scenario
        <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
          {SCENARIOS.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <button className="primary" type="submit" disabled={busy}>
        {busy ? "posting…" : "submit batch"}
      </button>
    </form>
  );
}

function BulkForm({ onPost }: { onPost: (s: string) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <form>
      <label>
        upload a jobs.json file (shape: {`{"jobs":[...]}`})
        <input
          type="file"
          accept="application/json"
          disabled={busy}
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setBusy(true);
            try {
              const payload = JSON.parse(await f.text());
              for (const job of payload.jobs ?? []) {
                const res = await postJob(job);
                onPost(`POST /jobs ${job.id} → ${res?.decision?.outcome ?? "?"}`);
              }
            } catch (err) {
              onPost(`bulk upload error: ${(err as Error).message}`);
            }
            setBusy(false);
            e.target.value = "";
          }}
        />
      </label>
      <p className="notice">matches examples/jobs.sample.json.</p>
    </form>
  );
}

function Inspector({ jobId }: { jobId: string }) {
  const [detail, setDetail] = useState<{ job: Record<string, unknown>; runs: JobRun[] } | null>(null);
  const [audit, setAudit] = useState<AuditEvt[]>([]);
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [d, a] = await Promise.all([
          fetch(`/api/jobs/${jobId}`).then((r) => r.json()),
          fetch(`/api/audit?limit=200`).then((r) => r.json()),
        ]);
        if (cancelled) return;
        setDetail(d);
        setAudit((a.events ?? []).filter((e: AuditEvt) => e.subject === jobId));
      } catch {}
    };
    tick();
    const h = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(h);
    };
  }, [jobId]);

  const intel = useMemo(
    () =>
      audit.filter(
        (e) => e.action.includes("operator-result") || e.action.includes("intelligence"),
      ),
    [audit],
  );

  if (!detail) return <p className="notice">loading…</p>;
  return (
    <div>
      <pre>{JSON.stringify(detail.job, null, 2)}</pre>
      <h2>runs ({detail.runs.length})</h2>
      {detail.runs.map((r, i) => (
        <div key={i} className="row">
          <code>#{r.attempt}</code>
          <span>{r.twilio_call_sid ?? r.twilio_message_sid ?? "—"}</span>
          <span className={`badge ${r.status}`}>{r.status}</span>
        </div>
      ))}
      <h2>audit for this job</h2>
      <pre>{audit.map((e) => `${e.at} ${e.action}`).join("\n") || "—"}</pre>
      {intel.length > 0 && (
        <>
          <h2>intelligence</h2>
          <pre>{intel.map((e) => e.data).join("\n\n")}</pre>
        </>
      )}
    </div>
  );
}
