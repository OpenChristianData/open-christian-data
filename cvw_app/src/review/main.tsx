import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import "./read-mode.css";
import "./compare.css";
const root = document.getElementById("review-root");
if (!root) throw new Error("Corpus Review Viewer root is missing");
createRoot(root).render(<StrictMode><App /></StrictMode>);
