import { useEffect, useState } from "react";
import { explainDeal, type Explanation } from "./api";

type State = { status: "idle" | "loading" | "failed" } | { status: "done"; result: Explanation; asOf: string };

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export function Explain({ id, asOf }: { id: string; asOf: string }) {
  const [state, setState] = useState<State>({ status: "idle" });
  const [steps, setSteps] = useState<string[]>([]);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (state.status !== "loading") return;
    const started = Date.now();
    setSeconds(0);
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [state.status]);

  const run = async () => {
    const started = asOf;
    setState({ status: "loading" });
    setSteps([]);
    try {
      const result = await explainDeal(id, (step) => setSteps((seen) => [...seen, step]));
      setState({ status: "done", result, asOf: started });
    } catch {
      setState({ status: "failed" });
    }
  };

  if (state.status === "loading") {
    return (
      <section className="card explain">
        <h2>AI explanation</h2>
        <ol className="steps" aria-live="polite">
          {steps.map((step, index) => (
            <li key={index} className={index === steps.length - 1 ? "current" : "finished"}>
              {step}
              {index === steps.length - 1 ? <span aria-hidden="true"> {clock(seconds)}</span> : null}
            </li>
          ))}
        </ol>
        {steps.length ? null : <p className="note">Starting…</p>}
      </section>
    );
  }

  if (state.status !== "done") {
    return (
      <section className="card explain">
        <h2>AI explanation</h2>
        <p className="note">Get a fact-checked summary and one next step.</p>
        {state.status === "failed" ? <p role="alert">The agent couldn't be reached. Please try again.</p> : null}
        <button onClick={run}>Explain this deal</button>
      </section>
    );
  }

  const { grounded, answer } = state.result;
  return (
    <section className="card explain">
      <h2>AI explanation</h2>
      {grounded ? null : <p role="alert">A fact-checked explanation wasn't available, so these are the plain facts.</p>}
      <p>{answer.summary}</p>
      <ul>{answer.reasons.map((reason) => <li key={reason.feature + reason.text}>{reason.text}</li>)}</ul>
      {answer.next_step ? <p className="next"><strong>Next step:</strong> {answer.next_step.text}</p> : null}
      {state.asOf === asOf ? null : (
        <p className="note outdated">The score has changed since this explanation. <button onClick={run}>Explain again</button></p>
      )}
      <small>{grounded ? "Written by AI. Numbers were checked against the deal's data, and the next step comes from the sales playbook." : ""}</small>
    </section>
  );
}
