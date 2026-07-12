import React from "react";
import SeverityBadge from "@/components/risk/SeverityBadge";
import { Search, ExternalLink, Sparkles, ShieldCheck } from "lucide-react";

function HeadlineRow({ h, cited }) {
  const val = h.sentimentScore != null ? Number(h.sentimentScore) : null;
  const pct = val != null ? Math.round(val * 100) : 0;
  const text = h.headline || "";
  return (
    <div
      className={`grid grid-cols-[1fr_46px] gap-3 items-center py-2.5 border-t border-[#1b2029] first:border-t-0 ${
        cited ? "pl-2 -ml-2 border-l-2 border-l-violet-400/60 bg-violet-500/[0.04] rounded-r" : ""
      }`}
    >
      <div>
        {h.url ? (
          <a href={h.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-start gap-1 text-[12.5px] text-[#dbe1ea] hover:text-white hover:underline leading-snug">
            {text} <ExternalLink className="w-3 h-3 mt-0.5 shrink-0 text-[#5f6a7c]" />
          </a>
        ) : (
          <span className="text-[12.5px] text-[#dbe1ea] leading-snug">{text}</span>
        )}
        <div className="flex items-center gap-2 mt-0.5">
          {h.source && <span className="text-[10.5px] text-[#5f6a7c]">{h.source}</span>}
          {cited && <span className="text-[9.5px] uppercase tracking-wider text-violet-300/80 font-semibold">cited</span>}
        </div>
      </div>
      <div>
        <div className="h-[5px] rounded-full bg-[#232a36] overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-red-300 to-red-500" style={{ width: `${pct}%` }} />
        </div>
        <div className="font-mono text-[10px] text-[#8b95a6] text-right mt-0.5">
          {val != null ? val.toFixed(2) : "—"}
        </div>
      </div>
    </div>
  );
}

function ExplanationBlock({ narrative }) {
  const parts = narrative.split(/(\[id=[^\]]+\])/g);
  return (
    <div className="rounded-xl border border-violet-500/25 bg-gradient-to-br from-violet-500/[0.08] to-transparent p-3.5 mb-3">
      <div className="flex items-center gap-1.5 mb-2">
        <Sparkles className="w-3.5 h-3.5 text-violet-300" />
        <span className="text-[10px] uppercase tracking-wider text-violet-200/90 font-semibold">Explanation</span>
        <span className="flex items-center gap-1 ml-auto text-[9.5px] text-[#6f7a8c]">
          <ShieldCheck className="w-3 h-3 text-emerald-400/70" /> verified against sources
        </span>
      </div>
      <p className="text-[13px] text-[#dfe4ec] leading-relaxed m-0">
        {parts.map((p, i) =>
          /^\[id=/.test(p) ? (
            <span key={i} className="inline-block font-mono text-[10px] text-violet-300/90 bg-violet-500/10 rounded px-1 mx-0.5 align-middle">
              {p.replace(/[[\]]/g, "").replace("id=", "#")}
            </span>
          ) : (
            <span key={i}>{p}</span>
          )
        )}
      </p>
      <p className="text-[10px] text-[#6f7a8c] mt-2 mb-0 leading-normal">
        Generated from the headlines below and checked for faithful, cited claims. Describes past
        activity — not a prediction or investment advice.
      </p>
    </div>
  );
}

export default function EvidencePanel({ data, loading, error }) {
  if (loading) {
    return <div className="text-[#5f6a7c] text-sm py-16 text-center animate-pulse">Loading…</div>;
  }
  if (error) {
    return <div className="text-red-400 text-sm p-5">{error}</div>;
  }
  if (!data) {
    return (
      <div className="text-[#5f6a7c] text-sm py-16 text-center leading-relaxed flex flex-col items-center gap-3">
        <div className="w-11 h-11 rounded-full bg-[#161a23] flex items-center justify-center">
          <Search className="w-5 h-5 text-[#3a4150]" />
        </div>
        Select a company from the feed<br />to see what drove its anomaly.
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3">
      <div className="pb-1">
        <h2 className="text-lg font-bold tracking-tight text-[#eaedf3] m-0">
          {data.companyName}
          <span className="font-mono bg-gradient-to-r from-violet-400 to-cyan-300 bg-clip-text text-transparent text-[15px] ml-2">{data.ticker}</span>
        </h2>
        <p className="text-[#8b95a6] text-[12.5px] mt-0.5 mb-0">
          {data.alertCount} anomaly {data.alertCount === 1 ? "day" : "days"} on record
        </p>
      </div>

      <div className="relative pl-3 space-y-3 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-px before:bg-[#232936]">
        {data.alerts?.map((al, i) => {
          const citedSet = new Set(al.llmCitedIds || []);
          const hasNarrative = al.llmStatus === "generated" && al.llmNarrative;
          return (
            <div key={i} className="relative border border-[#232936] rounded-xl p-3.5 bg-[#161a23]">
              <div className="flex items-center gap-2.5 mb-2.5">
                <SeverityBadge severity={al.severity} />
                <span className="font-mono text-xs text-[#8b95a6]">{al.triggeredAt ? al.triggeredAt.slice(0, 10) : ""}</span>
              </div>

              {hasNarrative && <ExplanationBlock narrative={al.llmNarrative} />}

              <p className="text-[11.5px] text-[#7f8a99] leading-relaxed m-0 mb-3 font-mono">{al.explanation || ""}</p>

              {al.headlines?.length > 0 ? (
                <>
                  <div className="text-[10px] uppercase tracking-wider text-[#5f6a7c] mb-1.5">Top negative headlines that day</div>
                  {al.headlines.map((h, j) => <HeadlineRow key={j} h={h} cited={citedSet.has(h.articleId)} />)}
                </>
              ) : (
                <div className="text-[10.5px] text-[#5f6a7c]">No headlines recorded for this day.</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}