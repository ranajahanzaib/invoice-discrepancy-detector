import React from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
type Case = {
  id: string;
  result: { status: string; exceptions: { type: string; message: string }[] };
  review: string;
  invoice: { number?: string; supplier?: string };
};
function App() {
  const [cases, setCases] = React.useState<Case[]>([]),
    [busy, setBusy] = React.useState(false),
    [message, setMessage] = React.useState("");
  const refresh = () =>
    fetch("/api/cases")
      .then((r) => r.json())
      .then(setCases)
      .catch(() =>
        setMessage(
          "API is not connected. Start the backend with uvicorn backend.main:app --reload.",
        ),
      );
  React.useEffect(() => {
    refresh();
  }, []);
  async function demo() {
    setBusy(true);
    setMessage("");
    const body = {
      invoice: {
        number: "INV-350",
        po_number: "PO-100",
        supplier: "Northwind Supply",
        currency: "USD",
        subtotal: "4850",
        tax: "0",
        total: "4850",
        lines: [
          {
            sku: "WID-01",
            description: "Industrial widget",
            quantity: "10",
            unit_price: "485",
          },
        ],
      },
      po: {
        number: "PO-100",
        supplier: "Northwind Supply",
        currency: "USD",
        lines: [
          {
            sku: "WID-01",
            description: "Industrial widget",
            quantity: "10",
            unit_price: "450",
          },
        ],
      },
      receipt: {
        number: "GRN-100",
        po_number: "PO-100",
        currency: "USD",
        lines: [
          { sku: "WID-01", description: "Industrial widget", quantity: "10" },
        ],
      },
    };
    try {
      await fetch("/api/reconcile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      await refresh();
    } catch {
      setMessage("Could not reach the API.");
    } finally {
      setBusy(false);
    }
  }
  async function review(id: string, status: string) {
    await fetch(`/api/cases/${id}/review`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    refresh();
  }
  return (
    <main>
      <aside>
        <div className="brand">
          IE<span>●</span>
        </div>
        <nav>
          <b>Overview</b>
          <a>Review queue</a>
          <a>Documents</a>
          <a>Evaluation</a>
        </nav>
        <div className="asidefoot">
          LOCAL WORKSPACE
          <br />
          <small>SQLite · AI optional</small>
        </div>
      </aside>
      <section>
        <header>
          <div>
            <small>ACCOUNTS PAYABLE / INVESTIGATION</small>
            <h1>Invoice exceptions</h1>
            <p>Investigate discrepancies with traceable evidence.</p>
          </div>
          <button onClick={demo} disabled={busy}>
            {busy ? "Running…" : "Run $350 demo"}
          </button>
        </header>
        <div className="stats">
          <article>
            <small>OPEN CASES</small>
            <strong>{cases.filter((c) => c.review === "open").length}</strong>
          </article>
          <article>
            <small>WITH EXCEPTIONS</small>
            <strong>
              {cases.filter((c) => c.result.status === "exception").length}
            </strong>
          </article>
          <article>
            <small>REVIEWED</small>
            <strong>{cases.filter((c) => c.review !== "open").length}</strong>
          </article>
        </div>
        <h2>Review queue</h2>
        {message && <p className="notice">{message}</p>}
        <div className="table">
          <div className="row heading">
            <span>INVOICE</span>
            <span>SUPPLIER</span>
            <span>FINDING</span>
            <span>STATUS</span>
            <span>ACTION</span>
          </div>
          {cases.map((c) => (
            <div className="row" key={c.id}>
              <span>{c.invoice.number || c.id.slice(0, 8)}</span>
              <span>{c.invoice.supplier || "—"}</span>
              <span>
                {c.result.exceptions.map((e) => e.message).join("; ") ||
                  "No discrepancy"}
              </span>
              <span className={c.review === "open" ? "pill" : "pill done"}>
                {c.review}
              </span>
              <span>
                {c.review === "open" ? (
                  <>
                    <button
                      className="quiet"
                      onClick={() => review(c.id, "resolved")}
                    >
                      Resolve
                    </button>{" "}
                    <a href={`/api/cases/${c.id}/export.json`}>JSON</a>
                  </>
                ) : (
                  <a href={`/api/cases/${c.id}/export.json`}>Export</a>
                )}
              </span>
            </div>
          ))}
          {!cases.length && (
            <div className="empty">
              No cases yet. Run the demo or use the API to reconcile an invoice.
            </div>
          )}
        </div>
        <p className="foot">
          Financial checks are deterministic. Review actions are explicit; this
          app does not initiate payments.
        </p>
      </section>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
