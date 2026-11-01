import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { AtRiskPage } from "./AtRiskPage";
import { DealPage } from "./DealPage";
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
    const update = () => {
      setHash(location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);

  const dealId = readDealId(hash);
  return (
    <>
      <header><a href="#/">Pipeline Pulse</a></header>
      <main>{dealId ? <DealPage key={dealId} id={dealId} /> : <AtRiskPage />}</main>
      <footer>Demo: deal records are real sample data, and activity is simulated. Scores show what moved the model, not what caused a deal's trouble.</footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
