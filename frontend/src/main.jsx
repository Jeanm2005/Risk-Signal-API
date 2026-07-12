import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import AnomalyMonitor from "@/pages/AnomalyMonitor";
import ScoreText from "@/pages/ScoreText";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AnomalyMonitor />} />
        <Route path="/score" element={<ScoreText />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);