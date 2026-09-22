import React from "react";
import ReactDOM from "react-dom/client";

function App() {
  return (
    <main>
      <h1>AFDD Platform</h1>
      <p>Application shell ready. Dashboard implementation is intentionally deferred.</p>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

