import React from "react";

const colors ={
    high: "bg-red-500/15 text-red-400 ring-1 ring-red-500/30",
    medium: "bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/30",
    low: "bg-emeral-500/15 text-emerald-400 ring-1 ring-emerald-500/30",
};

export default function SeverityBadge({ severity }) {
    const key = (severity || "low").toLowerCase();
    return (
        <span className={`text-[10px] uppercase tracking-wider font-semibold px-2.5 py-1 rounded-full whitespace-nowrap ${colors[key] || colors.low}`}>
            {severity || "low"}
        </span>
    );
}