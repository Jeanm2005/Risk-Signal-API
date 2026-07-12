import React from "react";
import { Flame, AlertTriangle, Gauge, Layers } from "lucide-react";

const CONFIG = {
    all: { icon: Layers, ring: "from-violet-500 to-cyan-400", glow: "shadow-violet-500/10" },
    high: { icon: Flame, ring: "from-red-500 to-orange-400", glow: "shadow-red-500/10" },
    medium: { icon: AlertTriangle, ring: "from-amber-500 to-yellow-400", glow: "shadow-amber-500/10" },
    low: { icon: Gauge, ring: "from-emeral-500 to-teal-400", glow: "shadow-emerald-500/10" },
};

export default function StatCard({ type, count, label}) {
    const cfg = CONFIG[type] || CONFIG.all;
    const Icon = cfg.icon;
    return (
        <div className={`flex-1 min-w-[130px] bg-[#12151d]/80 backdrop-blur border border-[#232936] rounded-2xl p-4 flex items-center gap-3 shadow-lg ${cfg.glow}`}>
            <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${cfg.ring} flex items-center justify-center shrink-0`}>
                <Icon className="w-4.5 h-4.5 text-[#0a0c11]" strokeWidth={2.5} />
            </div>
            <div>
                <div className="font-mono text-xl font-bold tracking-tight text-[#eaedf3] leading-none">{count}</div>
                <div className="text-[11px] uppercase tracking-wider text-[#8b95a6] mt-1">{label}</div>
            </div>
        </div>
    );
}