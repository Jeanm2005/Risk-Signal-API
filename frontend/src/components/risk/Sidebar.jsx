import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Activity, TerminalSquare, TriangleAlert } from "lucide-react";

const NAV = [
    { to: "/", label: "Monitor", icon: Activity },
    { to: "/score", label: "Score Text", icon: TerminalSquare },
];

export default function Sidebar() {
    const { pathname } = useLocation();
    return (
        <aside className="md:w-16 w-full md:h-screen md:sticky md:top-0 flex md:flex-col items-center justify-between md:justify-start gap-6 bg-[#0a0c11] border-b md:border-b-0 md:border-r border-[#1e2430] px-4 py-3 md:py-6">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-500 to-cyan-400 flex items-center justify-center shrink-0">
                <TriangleAlert className="w-4.5 h-4.5 text-[#0a0c11]" strokeWidth={2.5} />
            </div>
            <nav className="flex md:flex-col gap-2">
                {NAV.map(({ to, label, icon: Icon }) => {
                    const active = pathname === to;
                    return (
                        <Link
                            key={to}
                            to={to}
                            title={label}
                            className={`group relative flex items-center justify-center w-10 h-10 rounded-lg transition-colors ${
                                active ? "bg-violet-500/15 text-violet-300" : "text-[#5f6a7c] hover:text-[#eaedf3] hover:bg-[#161a23]"
                            }`}
                        >
                        <Icon className="w-4.5 h-4.5" strokeWidth={2} />
                        <span className="hidden md:block absolute left-full ml-2 whitespace-nowrap text-xs bg-[#161a23] border border-[#232936] text-[#eaedf3] px-2 py-1 rounded-md opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10">
                            {label}
                        </span>
                        </Link>
                    );
                })}
            </nav>
            <div className="hidden md:block flex-1" />
        </aside>
    );
}