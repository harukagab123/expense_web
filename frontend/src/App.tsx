import { useCallback, useEffect, useState } from "react";

import "./App.css";
import { getHealth } from "./api/health";

type ConnectionState = "checking" | "connected" | "unavailable";

type StatusState = {
  backend: ConnectionState;
  database: ConnectionState;
  message: string;
  isError: boolean;
};

const checkingState: StatusState = {
  backend: "checking",
  database: "checking",
  message: "Checking application...",
  isError: false,
};

function badgeLabel(state: ConnectionState): string {
  if (state === "connected") {
    return "Connected";
  }

  if (state === "checking") {
    return "Checking";
  }

  return "Unavailable";
}

function StatusBadge({ state }: { state: ConnectionState }) {
  return <span className={`status-badge status-badge--${state}`}>{badgeLabel(state)}</span>;
}

export default function App() {
  const [status, setStatus] = useState<StatusState>(checkingState);
  const [isChecking, setIsChecking] = useState(true);

  const checkApplication = useCallback(async () => {
    setIsChecking(true);
    setStatus(checkingState);

    try {
      const health = await getHealth();
      const databaseConnected = health.database === "connected";

      setStatus({
        backend: "connected",
        database: databaseConnected ? "connected" : "unavailable",
        message: databaseConnected
          ? "Backend and database are ready."
          : "Backend is running, but the database check failed.",
        isError: !databaseConnected,
      });
    } catch {
      setStatus({
        backend: "unavailable",
        database: "unavailable",
        message: "Backend unavailable. Start the backend and retry.",
        isError: true,
      });
    } finally {
      setIsChecking(false);
    }
  }, []);

  useEffect(() => {
    void checkApplication();
  }, [checkApplication]);

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div className="top-bar__inner">
          <h1>Personal Financial File Manager</h1>
        </div>
      </header>

      <section className="content" aria-label="Application status">
        <div className="status-panel">
          <div className="status-panel__header">
            <div>
              <h2>Application Status</h2>
              <p>Live foundation check for the backend API and database connection.</p>
            </div>
            <button className="retry-button" onClick={checkApplication} disabled={isChecking}>
              Retry
            </button>
          </div>

          <div className="status-grid">
            <div className="status-row">
              <span className="status-row__label">Backend</span>
              <StatusBadge state={status.backend} />
            </div>
            <div className="status-row">
              <span className="status-row__label">Database</span>
              <StatusBadge state={status.database} />
            </div>
          </div>

          <p className={`status-message ${status.isError ? "status-message--error" : ""}`}>
            {status.message}
          </p>
        </div>
      </section>
    </main>
  );
}
