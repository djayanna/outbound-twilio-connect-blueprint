import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

type Stats = { jobs_by_status: Record<string, number>; runs_in_flight: number };
type Queues = { by_scenario: Record<string, number> };
type Lines = { by_from: Record<string, number> };
type AuditEvt = { at: string; actor: string; action: string; subject: string; data: string };

type Participant = { id: string; type: string | null; address: string | null; channel: string | null };
type Conversation = {
  id: string;
  status: string | null;
  name: string | null;
  created_at: string | null;
  last_event_at: string;
  participants: Participant[];
};
type Communication = {
  id: string;
  channel: string | null;
  author_address: string | null;
  participant_id: string | null;
  text: string | null;
  occurred_at: string | null;
};

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

function Dashboard() {
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
    <>
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
    </>
  );
}

// Agent-side participant types get a headset; the customer gets a person.
const AGENT_TYPES = new Set(["AI_AGENT", "HUMAN_AGENT", "AGENT"]);

function HeadsetIcon() {
  return (
    <svg className="avatar agent" viewBox="0 0 24 24" width="28" height="28" aria-label="agent">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        d="M4 13v-1a8 8 0 0 1 16 0v1M4 13a2 2 0 0 0-0 4 2 2 0 0 0 3-1.7V13a1.5 1.5 0 0 0-3 0Zm16 0a1.5 1.5 0 0 0-3 0v2.3A2 2 0 0 0 20 17a2 2 0 0 0 0-4Zm-2 5a4 4 0 0 1-4 3h-2"
      />
    </svg>
  );
}

function PersonIcon() {
  return (
    <svg className="avatar customer" viewBox="0 0 24 24" width="28" height="28" aria-label="customer">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="10" r="2.6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        d="M7 17.5a5 5 0 0 1 10 0"
      />
    </svg>
  );
}

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function ConversationList({
  conversations,
  selectedId,
  onSelect,
}: {
  conversations: Conversation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (!conversations.length) return <p className="dim">no conversations yet</p>;
  return (
    <ul className="conv-list">
      {conversations.map((c) => {
        const customer = c.participants.find((p) => p.type === "CUSTOMER");
        const channels = Array.from(new Set(c.participants.map((p) => p.channel).filter(Boolean)));
        const label = customer?.address ?? c.name ?? c.id;
        return (
          <li
            key={c.id}
            className={c.id === selectedId ? "conv selected" : "conv"}
            onClick={() => onSelect(c.id)}
          >
            <div className="conv-top">
              <span className="conv-addr">{label}</span>
              <span className={`status ${(c.status ?? "").toLowerCase()}`}>{c.status ?? "—"}</span>
            </div>
            <div className="conv-sub">
              {channels.map((ch) => (
                <span className="chan" key={ch}>
                  {ch}
                </span>
              ))}
              <span className="dim">{fmtTime(c.last_event_at)}</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Transcript({ conversation }: { conversation: Conversation | null }) {
  const [comms, setComms] = useState<Communication[]>([]);
  const [loading, setLoading] = useState(false);
  const convId = conversation?.id ?? null;

  // Resolve a communication's author to agent-vs-customer. Prefer the
  // participant type (joined by participant_id, else by address); default to
  // customer when the author isn't a known participant.
  const typeByParticipant = useMemo(() => {
    const m = new Map<string, string>();
    conversation?.participants.forEach((p) => p.type && m.set(p.id, p.type));
    return m;
  }, [conversation]);
  const typeByAddress = useMemo(() => {
    const m = new Map<string, string>();
    conversation?.participants.forEach((p) => p.address && p.type && m.set(p.address, p.type));
    return m;
  }, [conversation]);

  const isAgent = (c: Communication): boolean => {
    const t =
      (c.participant_id && typeByParticipant.get(c.participant_id)) ||
      (c.author_address && typeByAddress.get(c.author_address)) ||
      "";
    return AGENT_TYPES.has(t);
  };

  useEffect(() => {
    if (!convId) {
      setComms([]);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const load = async () => {
      const data = await getJson<{ communications: Communication[] }>(
        `/api/conversations/${convId}/communications`,
        { communications: [] },
      );
      if (!cancelled) setComms(data.communications ?? []);
    };

    setLoading(true);
    load().finally(() => !cancelled && setLoading(false));

    // Live updates: refetch this transcript when its conversation changes.
    // Debounced because ConversationRelay writes 3–5 fragments per utterance.
    const onDelta = (e: Event) => {
      const detail = (e as CustomEvent<{ conversation_id: string }>).detail;
      if (detail?.conversation_id !== convId) return;
      clearTimeout(timer);
      timer = setTimeout(load, 400);
    };
    window.addEventListener("conv-delta", onDelta);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      window.removeEventListener("conv-delta", onDelta);
    };
  }, [convId]);

  if (!conversation) return <p className="dim">select a conversation</p>;

  return (
    <div className="transcript">
      {loading && !comms.length ? <p className="dim">loading…</p> : null}
      {!loading && !comms.length ? <p className="dim">no messages yet</p> : null}
      {comms.map((c) => {
        const agent = isAgent(c);
        return (
          <div className="msg" key={c.id}>
            <div className="msg-time dim">{fmtTime(c.occurred_at)}</div>
            <div className="msg-avatar">{agent ? <HeadsetIcon /> : <PersonIcon />}</div>
            <div className="msg-body">
              <div className="msg-who">{c.author_address ?? (agent ? "agent" : "customer")}</div>
              <div className="msg-text">{c.text}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Conversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selectedId;

  useEffect(() => {
    let closed = false;
    let listTimer: ReturnType<typeof setTimeout> | undefined;

    const loadList = async () => {
      const data = await getJson<{ conversations: Conversation[] }>("/api/conversations", {
        conversations: [],
      });
      if (closed) return;
      setConversations(data.conversations ?? []);
      // Auto-select the most-recently-active conversation on first load.
      if (!selectedRef.current && data.conversations?.length) {
        setSelectedId(data.conversations[0].id);
      }
    };

    loadList();

    // Push: Server-Sent Events of {type, conversation_id} deltas. Each delta
    // refreshes the list (debounced) and re-broadcasts to the open transcript
    // via a window event. EventSource reconnects on its own.
    const es = new EventSource("/api/conversations/stream");
    es.onopen = () => !closed && setConnected(true);
    es.onerror = () => !closed && setConnected(false);
    es.onmessage = (ev) => {
      let detail: { conversation_id: string } | null = null;
      try {
        detail = JSON.parse(ev.data);
      } catch {
        return;
      }
      window.dispatchEvent(new CustomEvent("conv-delta", { detail }));
      clearTimeout(listTimer);
      listTimer = setTimeout(loadList, 400);
    };

    return () => {
      closed = true;
      clearTimeout(listTimer);
      es.close();
    };
  }, []);

  const selected = conversations.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="conv-view">
      <div className="panel conv-left">
        <h2>
          conversations
          <span className={connected ? "live on" : "live off"}>{connected ? "live" : "offline"}</span>
        </h2>
        <ConversationList
          conversations={conversations}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      </div>
      <div className="panel conv-right">
        <h2>transcript</h2>
        <Transcript conversation={selected} />
      </div>
    </div>
  );
}

export function App() {
  const [tab, setTab] = useState<"dashboard" | "conversations">("dashboard");
  return (
    <div className="wb">
      <header className="wb-head">
        <h1>wallboard</h1>
        <nav className="tabs">
          <button
            className={tab === "dashboard" ? "active" : ""}
            onClick={() => setTab("dashboard")}
          >
            dashboard
          </button>
          <button
            className={tab === "conversations" ? "active" : ""}
            onClick={() => setTab("conversations")}
          >
            conversations
          </button>
        </nav>
      </header>

      {tab === "dashboard" ? <Dashboard /> : <Conversations />}
    </div>
  );
}
