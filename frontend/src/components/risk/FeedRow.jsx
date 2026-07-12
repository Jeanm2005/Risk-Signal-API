import React from "react";
import SeverityBadge from "@/components/risk/SeverityBadge";
import { ChevronRight } from "lucide-react";

const dotColors = {
    high: "bg-red-500 shadow-[0_0_8px_rgba(255,93,93,.6)]",
    medium: "bg-amber-400 shadow-[0_0_8px_rgba(245,166,35,.6)]",
    low: "bg-emeral-400 shadow-[0_0_8px_rgba(121,207,160,.6)]",
};

export default function FeedRow({ alert, selected, onClick }) {
    const sev = (alert.severity || "low").toLowerCase();
    return (
        <div
            onClick={onClick}
            className={`group flex items-center gap-3.5 py-3.5 px-4 border-b border-[#1b2029] last:border-b-0 cursor-pointer transition-all ${
                selected ? "bg-gradient-to-r from-violet-500/10 to-transparent border-l-2 border-l-violet-400" : "border-l-2 border-l-transparent hover:bg-[#161a23]"
            }`}
        >
            <span className={`w-2 h-2 rounded-full shrink-0 ${dotColors[sev] || dotColors.low}`} />
            <div className="w-16 shrink-0">
                <div className="font-mono font-bold textt-[13.5px] tracking-tight text-[#eaedf3]">{alert.ticker}</div>
                <div className="font-mono text-[10.5px] text-[#5f6a7c] mt-0.5">{alert.triggeredAt ? alert.triggeredAt.slice(0, 10) : ""}</div>
            </div>
            <div className="min-w-0 flex-1">
                <div className="text-[13px] text-[#eaedf3] truncate">{alert.companyName}</div>
                <div className="text-[11.5px] text-[#8b95a6] truncate mt-0.5">{alert.explanation || ""}</div>
            </div>
            <SeverityBadge severity={alert.severity} />
            <ChevronRight className="w-4 h-4 text-[#3a4150] group-hover:text-[#8b95a6] transition-colors shrink-0" />
        </div>
    );
}