import { useEffect, useMemo, useState } from "react";
import "./App.css";

type Stats = { jobs_by_status: Record<string, number>; runs_in_flight: number };
type Queues = { by_scenario: Record<string, number> };
type Lines = { by_from: Record<string, number> };
type AuditEvt = { at: string; actor: string; action: string; subject: string; data: string };

async function getJson<T>(url: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(url);
    return (await r.json()) as T;
  } catch {
    return fallback;
  }
}

function Tile({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="tile">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

function Bars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  if (!entries.length) return <p className="dim">no data</p>;
  return (
    <>
      {entries.map(([k, n]) => (
        <div className="bar" key={k}>
          <span>{k}</span>
          <div className="track">
            <div className="fill" style={{ width: `${Math.round((n / max) * 100)}%` }} />
          </div>
          <span style={{ textAlign: "right" }}>{n}</span>
        </div>
      ))}
    </>
  );
}

export function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [queues, setQueues] = useState<Queues>({ by_scenario: {} });
  const [lines, setLines] = useState<Lines>({ by_from: {} });
  const [audit, setAudit] = useState<AuditEvt[]>([]);

  useEffect(() => {
    const tick = async () => {
      const [s, q, l, a] = await Promise.all([
        getJson<Stats | null>("/api/stats", null),
        getJson<Queues>("/api/stats/queues", { by_scenario: {} }),
        getJson<Lines>("/api/stats/lines", { by_from: {} }),
        getJson<{ events: AuditEvt[] }>("/api/audit?limit=100", { events: [] }),
      ]);
      setStats(s);
      setQueues(q);
      setLines(l);
      setAudit(a.events ?? []);
    };
    tick();
    const h = setInterval(tick, 2000);
    return () => clearInterval(h);
  }, []);

  const inProgress = useMemo(
    () =>
      audit.filter((e) => e.action === "run.in-progress" && Date.now() - new Date(e.at).getTime() < 60_000)
        .length,
    [audit],
  );
  const dropRate = useMemo(() => {
    const since = Date.now() - 5 * 60_000;
    const recent = audit.filter((e) => new Date(e.at).getTime() >= since);
    const completed = recent.filter((e) => e.action === "run.completed").length;
    const failed = recent.filter((e) => e.action === "run.failed").length;
    const total = completed + failed;
    return total ? Math.round((failed / total) * 100) : 0;
  }, [audit]);

  return (
    <div className="wb">
      <h1>wallboard</h1>

      <div className="tiles">
        <Tile k="jobs: scheduled" v={stats?.jobs_by_status?.scheduled ?? 0} />
        <Tile k="jobs: firing" v={stats?.jobs_by_status?.firing ?? 0} />
        <Tile k="runs in-flight" v={stats?.runs_in_flight ?? 0} />
        <Tile k="in-conversation (1m)" v={inProgress} />
        <Tile k="5m drop rate" v={`${dropRate}%`} />
      </div>

      <div className="grid">
        <div className="panel">
          <h2>queue depth by scenario</h2>
          <Bars data={queues.by_scenario} />
        </div>
        <div className="panel">
          <h2>line capacity</h2>
          <Bars data={lines.by_from} />
        </div>
      </div>

      <div className="panel">
        <h2>recent audit</h2>
        <table className="audit">
          <thead>
            <tr>
              <th>at</th>
              <th>actor</th>
              <th>action</th>
              <th>subject</th>
            </tr>
          </thead>
          <tbody>
            {audit.slice(0, 50).map((e, i) => (
              <tr key={i}>
                <td className="dim">{e.at.slice(11, 19)}</td>
                <td>{e.actor}</td>
                <td>{e.action}</td>
                <td>
                  <code className="subject">{e.subject}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
