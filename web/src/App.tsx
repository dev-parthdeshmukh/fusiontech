import { useEffect, useState } from "react";
import { api } from "./api";
import { About } from "./pages/About";
import { Validation } from "./pages/Validation";
import { Workspace } from "./pages/Workspace";
import type { Colormaps, Health } from "./types";

type Route = "workspace" | "validation" | "about";

function routeFromHash(): Route {
  const h = location.hash.replace(/^#\/?/, "").split("?")[0];
  return h === "validation" || h === "about" ? h : "workspace";
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [health, setHealth] = useState<Health | null>(null);
  const [colormaps, setColormaps] = useState<Colormaps | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        setOffline(false);
      })
      .catch(() => setOffline(true));
    api.colormaps().then(setColormaps).catch(() => undefined);
  }, []);

  const vxm = health?.models.voxelmorph.available;
  const enh = health?.models.enhancer.available;
  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/workspace" style={{ color: "inherit", textDecoration: "none" }}>
          <img src="/favicon.svg" alt="" />
          <span>
            FusionMap <small>AI PET/MRI fusion</small>
          </span>
        </a>
        <nav className="nav">
          <a href="#/workspace" className={route === "workspace" ? "active" : ""}>
            Workspace
          </a>
          <a href="#/validation" className={route === "validation" ? "active" : ""}>
            Validation
          </a>
          <a href="#/about" className={route === "about" ? "active" : ""}>
            How it works
          </a>
        </nav>
        <div className="spacer" />
        <div className="row chips">
          {offline ? (
            <span className="chip warn">
              <span className="dot" style={{ background: "var(--critical)" }} /> API offline — run <code>fusionmap serve</code>
            </span>
          ) : (
            <>
              <span className={`chip ${vxm ? "ok" : ""}`} title={health?.models.voxelmorph.card?.architecture ?? "not trained"}>
                <span className="dot" /> VoxelMorph
              </span>
              <span className={`chip ${enh ? "ok" : ""}`} title={health?.models.enhancer.card?.architecture ?? "not trained"}>
                <span className="dot" /> ViT enhancer
              </span>
            </>
          )}
          <span className="chip warn" title={health?.disclaimer}>
            Research prototype · not for clinical use
          </span>
        </div>
      </header>
      {route === "workspace" && <Workspace health={health} colormaps={colormaps} />}
      {route === "validation" && <Validation health={health} />}
      {route === "about" && <About />}
    </div>
  );
}
