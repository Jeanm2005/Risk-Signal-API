import React from "react";

const barConfig = {
  positive: { label: "positive", color: "#37c98b" },
  negative: { label: "negative", color: "#ff5c5c" },
  neutral:  { label: "neutral",  color: "#8a93a3" },
};

function Bar({ label, value, color }) {
  const num = typeof value === "number" && isFinite(value) ? value : 0;
  const pct = Math.max(0, Math.min(100, num * 100));

  return (
    <div className="grid grid-cols-[74px_1fr_52px] items-center gap-2.5 my-1.5 text-[13px]">
      <span className="text-[#9aa4b2]">{label}</span>

      {/* track — inline styles only, so nothing depends on Tailwind resolving */}
      <div style={{
        height: "8px",
        width: "100%",
        background: "#0e1116",
        borderRadius: "9999px",
        overflow: "hidden",
        position: "relative",
      }}>
        {/* fill */}
        <div style={{
          height: "8px",
          width: `${pct}%`,
          background: color,
          borderRadius: "9999px",
          transition: "width 400ms ease",
        }} />
      </div>

      <span className="text-right text-[#9aa4b2] tabular-nums">{pct.toFixed(1)}%</span>
    </div>
  );
}

export default function ScoreResult({ data, latencyMs }) {
  if (!data) return null;

  const pillColors = {
    negative: "bg-red-500/15 text-red-400 ring-1 ring-red-500/30",
    positive: "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30",
    neutral: "bg-[#8a93a3]/15 text-[#8a93a3] ring-1 ring-[#8a93a3]/30",
  };

  return (
    <div className="bg-[#12151d]/80 backdrop-blur border border-[#232936] rounded-2xl p-5 mt-4 shadow-lg shadow-violet-500/5">
      <div className="flex items-baseline justify-between mb-4">
        <span className={`text-lg font-bold capitalize px-3.5 py-1 rounded-full ${pillColors[data.label] || pillColors.neutral}`}>
          {data.label}
        </span>
        <span className="text-[#9aa4b2] text-[13px]">
          risk score <strong className="text-[#eaedf3] text-[15px]">{(data.riskScore ?? 0).toFixed(3)}</strong>
        </span>
      </div>

      {Object.entries(barConfig).map(([key, cfg]) => (
        <Bar key={key} label={cfg.label} value={data.scores?.[key]} color={cfg.color} />
      ))}

      <div className="text-[#9aa4b2] text-xs mt-3.5 pt-3 border-t border-[#232936]">
        {data.tokenCount} tokens · {latencyMs} ms round trip · finbert-base · onnx
      </div>
    </div>
  );
}