import { useState } from "react";
import { explainDeal, type Explanation } from "./api";

type State = { status: "idle" | "loading" | "failed" } | { status: "done"; result: Explanation };

export function Explain({ id }: { id: string }) {
  const [state, setState] = useState<State>({ status: "idle" });

  const run = async () => {
    setState({ status: "loading" });
    try {
      setState({ status: "done", result: await explainDeal(id) });
    } catch {
      setState({ status: "failed" });
    }
  };

  if (state.status !== "done") {
    return (
      <section className="card explain">
        <h2>AI explanation</h2>
        <p className="note">Get a fact-checked summary and one next step.</p>
        {state.status === "failed" ? <p role="alert">The agent couldn't be reached. Please try again.</p> : null}
        <button onClick={run} disabled={state.status === "loading"}>
          {state.status === "loading" ? "Explaining… this can take a minute" : "Explain this deal"}
        </button>
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
      <small>{grounded ? "Written by AI. Numbers were checked against the deal's data, and the next step comes from the sales playbook." : ""}</small>
    </section>
  );
}
