import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { DealPage } from "./DealPage";
import { LiveStrip } from "./LiveStrip";
import { readFilters } from "./filters";
import { PipelinePage } from "./PipelinePage";
import "./styles.css";

function readDealId(hash: string) {
  const match = hash.match(/^#\/deals\/(.+)$/)?.[1];
  try {
    return match && decodeURIComponent(match);
  } catch {
    return match; // a hand-typed bad address: the API answers that the deal doesn't exist
  }
}

function App() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const update = () => setHash(location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);

  const [theme, setTheme] = useState(localStorage.getItem("theme") === "dark" ? "dark" : "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  const dealId = readDealId(hash);
  return (
    <>
      <header>
        <a className="brand" href="#/">Forecastly</a>
        <div className="header-side">
          <button className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
          <span className="demo-for">Demo for <img src="/outreach-logo.svg" alt="Outreach" /></span>
        </div>
      </header>
      <LiveStrip />
      <main>{dealId ? <DealPage key={dealId} id={dealId} /> : <PipelinePage filters={readFilters(hash)} />}</main>
      <footer>Demo: deal records are sample data, and activity is simulated. Forecastly is an independent project, not an Outreach product.</footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
