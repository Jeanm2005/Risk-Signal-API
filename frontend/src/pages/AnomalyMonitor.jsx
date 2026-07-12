import React, { useState, useEffect, useCallback } from "react";
import Sidebar from "@/components/risk/Sidebar";
import StatCard from "@/components/risk/StatCard";
import FeedRow from "@/components/risk/FeedRow";
import EvidencePanel from "@/components/risk/EvidencePanel";

const SEVERITIES = ["", "high", "medium", "low"];
const SEV_LABELS = { "": "All", high: "High", medium: "Medium", low: "Low" };

export default function AnomalyMonitor() {
    const [currentSev, setCurrentSev] = useState("");
    const [alerts, setAlerts] = useState([]);
    const [feedLoading, setFeedLoading] = useState(true);
    const [feedError, setFeedError] = useState(null);
    const [stats, setStats] = useState({ total: 0, high: 0, medium: 0, low: 0 });
    const [selectedTicker, setSelectedTicker] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState(null);

    const loadFeed = useCallback(async (sev) => {
        setFeedLoading(true);
        setFeedError(null);
        try {
            const q = sev ? `?severity=${sev}&limit=100` : "?limit=100";
            const res = await fetch("/alerts" + q);
            if (!res.ok) throw new Error(res.status);
            setAlerts(await res.json());
        } catch {
            setFeedError("Couldn't reach the API. Check server connection.");
            setAlerts([]);
        } finally {
            setFeedLoading(false);
        }
    }, []);

    const loadStats = useCallback(async () => {
        try {
            const res = await fetch("/alerts?limit=1000");
            if (!res.ok) return;
            const all = await res.json();
            const c = { high: 0, medium: 0, low: 0 };
            all.forEach((a) => {
                const s = (a.severity || "low").toLowerCase();
                if (c[s] != null) c[s]++;
            });
            setStats({ total: all.length, ...c });
        } catch {}
    }, []);

    useEffect(() => {
        loadStats();
        loadFeed(currentSev);
    }, []);

    const handleSevChange = (sev) => {
        setCurrentSev(sev);
        loadFeed(sev);
    };

    const selectCompany = async (ticker) => {
        setSelectedTicker(ticker);
        setDetailLoading(true);
        setDetailError(null);
        setDetail(null);
        try {
            const res = await fetch("/risk/" + encodeURIComponent(ticker));
            if (!res.ok) throw new Error(res.status);
            setDetail(await res.json());
        } catch {
            setDetailError(`Couldn't load ${ticker}.`);
        } finally {
            setDetailLoading(false);
        }
    };

    return (
    <div className="min-h-screen bg-[#0a0c11] text-[#eaedf3] flex flex-col md:flex-row" style={{
      backgroundImage: "radial-gradient(1000px 500px at 85% -10%, rgba(139,92,246,.10), transparent 60%), radial-gradient(800px 400px at -10% 20%, rgba(56,189,248,.06), transparent 60%)"
    }}>
      <Sidebar />

      <div className="flex-1 max-w-[1240px] mx-auto w-full px-5 md:px-8">
        <header className="pt-8 pb-2">
          <div className="flex items-start justify-between gap-4 mb-1">
            <div>
              <div className="flex items-center gap-2.5 mb-1">
                <span className="w-2 h-2 rounded-full bg-red-500 shadow-[0_0_10px_rgba(255,93,93,.7)] animate-pulse" />
                <span className="text-[11px] uppercase tracking-[0.15em] text-[#5f6a7c]">Live monitoring</span>
              </div>
              <h1 className="text-2xl font-bold tracking-tight m-0 bg-gradient-to-r from-white to-[#9aa4b8] bg-clip-text text-transparent">
                Anomaly Monitor
              </h1>
              <p className="text-[#8b95a6] text-[13px] mt-1 m-0">Companies with statistically unusual activity, and the news behind each flag.</p>
            </div>
          </div>

          <div className="text-[#aab4c4] text-xs py-3 px-4 my-4 rounded-xl border border-[#1b2029] bg-gradient-to-r from-violet-500/[0.06] to-transparent">
            This surfaces what is <strong className="text-[#c9cfdb]">abnormal</strong> and why — to point a human toward what to review.
            It describes past activity. It does not predict prices or offer investment advice.
          </div>

          <div className="flex gap-3 flex-wrap">
            <StatCard type="all" count={stats.total} label="Total flagged" />
            <StatCard type="high" count={stats.high} label="High" />
            <StatCard type="medium" count={stats.medium} label="Medium" />
            <StatCard type="low" count={stats.low} label="Low" />
          </div>
        </header>

        <div className="flex items-center gap-2 py-5 flex-wrap">
          <span className="text-[11px] uppercase tracking-wider text-[#5f6a7c] mr-1">Severity</span>
          {SEVERITIES.map((sev) => (
            <button
              key={sev}
              onClick={() => handleSevChange(sev)}
              className={`rounded-full px-4 py-1.5 text-[12.5px] font-medium border transition-all duration-150 ${
                currentSev === sev
                  ? "bg-gradient-to-r from-violet-500/20 to-cyan-400/10 text-white border-violet-400/50"
                  : "bg-transparent text-[#8b95a6] border-[#232936] hover:text-[#eaedf3] hover:border-[#313a4a]"
              }`}
            >
              {SEV_LABELS[sev]}
            </button>
          ))}
          <span className="ml-auto text-[#5f6a7c] text-xs font-mono">{alerts.length} shown</span>
        </div>

        <main className="grid grid-cols-1 md:grid-cols-[0.92fr_1.08fr] gap-4 pb-10 items-start">
          <section className="bg-[#12151d]/80 backdrop-blur border border-[#232936] rounded-2xl overflow-hidden shadow-xl shadow-black/20">
            <div className="text-[11px] uppercase tracking-wider text-[#8b95a6] px-4 py-3.5 border-b border-[#1b2029] flex justify-between items-center">
              <span>Universe feed</span>
              <span className="text-[#5f6a7c] normal-case tracking-normal">click a row →</span>
            </div>
            <div className="max-h-[70vh] overflow-y-auto">
              {feedLoading ? (
                <div className="text-[#5f6a7c] text-sm py-16 text-center animate-pulse">Loading…</div>
              ) : feedError ? (
                <div className="text-red-400 text-sm p-5">{feedError}</div>
              ) : alerts.length === 0 ? (
                <div className="text-[#5f6a7c] text-sm py-16 text-center">No anomalies at this severity.</div>
              ) : (
                alerts.map((a) => (
                  <FeedRow
                    key={a.ticker + a.triggeredAt}
                    alert={a}
                    selected={selectedTicker === a.ticker}
                    onClick={() => selectCompany(a.ticker)}
                  />
                ))
              )}
            </div>
          </section>

          <section className="bg-[#12151d]/80 backdrop-blur border border-[#232936] rounded-2xl overflow-hidden shadow-xl shadow-black/20">
            <div className="text-[11px] uppercase tracking-wider text-[#8b95a6] px-4 py-3.5 border-b border-[#1b2029]">
              Evidence
            </div>
            <div className="min-h-[240px]">
              <EvidencePanel data={detail} loading={detailLoading} error={detailError} />
            </div>
          </section>
        </main>

        <footer className="text-[#5f6a7c] text-[11px] pb-8 leading-relaxed">
          Anomalies detected by an Isolation Forest over per-company news volume, negativity, and returns —
          standardized within each company. Scores are negative-sentiment probabilities (0–1).
        </footer>
      </div>
    </div>
  );
}