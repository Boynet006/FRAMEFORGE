import { Projects } from "@/components/Projects";
import { SystemStatus } from "@/components/SystemStatus";

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="text-accent">FRAME</span>FORGE
          </h1>
          <p className="text-sm text-muted">Local AI video studio · Phase 1 foundation</p>
        </div>
        <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted">
          v0.1.0
        </span>
      </header>

      <SystemStatus />
      <Projects />
    </div>
  );
}
