import React, { useState } from "react";
import Sidebar from "@/components/risk/Sidebar";
import ScoreResult from "@/components/risk/ScoreResult";

const EXAMPLES = {
  neg: "Shares plunged after the company slashed guidance and disclosed an SEC probe.",
  pos: "The company reported record quarterly revenue and raised its full-year guidance.",
  neu: "The board of directors will convene on Thursday to review the quarterly report.",
};

export default function ScoreText() {
  const [apiKey, setApiKey] = useState("");
  const [text, setText] = useState("");
  const [scoring, setScoring] = useState(false);
  const [result, setResult] = useState(null);
  const [latency, setLatency] = useState(0);
  const [error, setError] = useState("");
  const [parityStatus, setParityStatus] = useState("idle");
  const [keyLoading, setKeyLoading] = useState(false);
  const [keyNote, setKeyNote] = useState("");

  const getDemoKey = async () => {
    setError("");
    setKeyNote("");
    setKeyLoading(true);
    try {
      const res = await fetch("/keys/demo", { method: "POST" });
      if (res.status === 429) { setError("Too many demo keys from your network — try again later."); return; }
      if (!res.ok) { setError(`Couldn't mint a demo key (${res.status}).`); return; }
      const d = await res.json();
      setApiKey(d.apiKey);
      const when = d.expiresAt ? new Date(d.expiresAt).toLocaleString() : "24h";
      setKeyNote(`Demo key ready — ~${d.requestsPerHour}/hr, expires ${when}.`);
    } catch {
      setError("Could not reach the API. Is the server running?");
    } finally {
      setKeyLoading(false);
    }
  };

  const score = async () => {
    setError("");
    if (!text.trim()) { setError("Enter some text to score."); return; }
    if (!apiKey.trim()) { setError("Paste your API key first."); return; }

    setScoring(true);
    const t0 = performance.now();
    try {
      const res = await fetch("/score", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": apiKey.trim() },
        body: JSON.stringify({ text: text.trim() }),
      });
      const ms = Math.round(performance.now() - t0);
      if (res.status === 401) { setError("Unauthorized — check your API key."); return; }
      if (!res.ok) { setError(`Server error (${res.status}).`); return; }
      const d = await res.json();
      setResult(d);
      setLatency(ms);
    } catch {
      setError("Could not reach the API. Is the server running?");
    } finally {
      setScoring(false);
    }
  };

  const checkParity = async () => {
    setParityStatus("checking");
    try {
      const r = await fetch("/parity");
      const d = await r.json();
      setParityStatus(d.all_pass ? "pass" : "fail");
    } catch {
      setParityStatus("idle");
    }
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") score();
  };

  return (
    <div className="min-h-screen bg-[#0a0c11] text-[#e6e9ef] flex flex-col md:flex-row" style={{
      backgroundImage: "radial-gradient(900px 450px at 90% -10%, rgba(139,92,246,.09), transparent 60%)"
    }}>
      <Sidebar />
      <div className="flex-1 flex justify-center px-4 py-10">
      <div className="w-full max-w-[640px]">
        <div className="flex justify-between items-start mb-5">
          <div>
            <h1 className="text-2xl font-bold tracking-tight m-0 bg-gradient-to-r from-white to-[#9aa4b8] bg-clip-text text-transparent">Risk Signal API</h1>
            <p className="text-[#9aa4b2] text-[13.5px] mt-1 m-0">
              Financial text → risk sentiment, served from an ONNX model proven identical to its Python original.
            </p>
          </div>
          <button
            onClick={checkParity}
            className={`text-xs border rounded-full px-2.5 py-1 bg-transparent cursor-pointer transition-colors shrink-0 ${
              parityStatus === "pass"
                ? "text-emerald-400 border-emerald-500/40"
                : "text-[#9aa4b2] border-[#262b36] hover:border-violet-400 hover:text-[#e6e9ef]"
            }`}
          >
            {parityStatus === "checking" ? "checking…" : parityStatus === "pass" ? "✓ parity verified" : parityStatus === "fail" ? "parity FAILED" : "verify parity"}
          </button>
        </div>

        <div className="bg-[#12151d]/80 backdrop-blur border border-[#232936] rounded-2xl p-5 shadow-xl shadow-black/20">
          <div className="mb-3.5">
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-xs uppercase tracking-wide text-[#9aa4b2]">API key</label>
              <button
                onClick={getDemoKey}
                disabled={keyLoading}
                className="text-[11px] text-violet-300 border border-violet-500/30 rounded-full px-2.5 py-0.5 bg-violet-500/10 cursor-pointer hover:bg-violet-500/20 disabled:opacity-50 transition-colors"
              >
                {keyLoading ? "minting…" : "Get demo key"}
              </button>
            </div>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="rsk... (paste your key, or get a demo key →)"
              autoComplete="off"
              className="w-full bg-[#0e1116] text-[#e6e9ef] border border-[#262b36] rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500"
            />
            {keyNote && <div className="text-[11px] text-emerald-400/80 mt-1.5">{keyNote}</div>}
            <div className="text-[10.5px] text-[#6f7a8c] mt-1 leading-normal">
              Scoring is authenticated. This mints a short-lived, rate-limited demo key — no signup.
              In production, keys are provisioned per consumer.
            </div>
          </div>

          <div className="mb-3.5">
            <label className="block text-xs uppercase tracking-wide text-[#9aa4b2] mb-1.5">Financial text</label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Paste a headline or a sentence from a filing..."
              className="w-full bg-[#0e1116] text-[#e6e9ef] border border-[#262b36] rounded-lg px-3 py-2.5 text-sm min-h-[96px] resize-y focus:outline-none focus:border-blue-500"
            />
            <div className="flex gap-2 mt-2 flex-wrap">
              {Object.entries(EXAMPLES).map(([key, val]) => (
                <button
                  key={key}
                  onClick={() => setText(val)}
                  className="bg-[#10141b] border border-[#262b36] text-[#9aa4b2] rounded-full px-3 py-1 text-[12.5px] cursor-pointer hover:border-blue-500 hover:text-[#e6e9ef] transition-colors"
                >
                  {key === "neg" ? "negative" : key === "pos" ? "positive" : "neutral"} example
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={score}
            disabled={scoring}
            className="bg-gradient-to-r from-violet-500 to-cyan-400 text-[#0a0c11] border-none rounded-lg px-5 py-2.5 font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-default hover:brightness-110 transition-all"
          >
            {scoring ? "Scoring…" : "Score"}
          </button>

          {error && <div className="text-red-400 text-sm mt-2.5">{error}</div>}
        </div>

        <ScoreResult data={result} latencyMs={latency} />
      </div>
      </div>
    </div>
  );
}