import { useEffect, useState } from "react";

export function App() {
  const [stats, setStats] = useState<any>(null);
  const [audit, setAudit] = useState<any[]>([]);

  useEffect(() => {
    const tick = async () => {
      const [s, a] = await Promise.all([
        fetch("/api/stats").then((r) => r.json()).catch(() => null),
        fetch("/api/audit?limit=50").then((r) => r.json()).catch(() => ({ events: [] })),
      ]);
      setStats(s);
      setAudit(a.events ?? []);
    };
    tick();
    const h = setInterval(tick, 2000);
    return () => clearInterval(h);
  }, []);

  return (
    <div style={{ fontFamily: "system-ui", padding: 24 }}>
      <h1>wallboard</h1>
      <h2>stats</h2>
      <pre style={{ background: "#f6f6f6", padding: 12 }}>{JSON.stringify(stats, null, 2)}</pre>
      <h2>recent audit</h2>
      <table cellPadding={6} style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
            <th>at</th><th>actor</th><th>action</th><th>subject</th>
          </tr>
        </thead>
        <tbody>
          {audit.map((e, i) => (
            <tr key={i} style={{ borderBottom: "1px solid #eee" }}>
              <td>{e.at}</td><td>{e.actor}</td><td>{e.action}</td><td>{e.subject}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
