import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const API = ["/alerts", "/risk", "/score", "/parity", "/health"];

export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
        proxy: Object.fromEntries(
            API.map((p) => [p, { target: "http://localhost:5000", changeOrigin: true}])
        ),
    },
    build: {
        outDir: path.resolve(__dirname, "../csharp/RiskSignalApi/wwwroot"),
        emptyOutDir: true,
    },
});