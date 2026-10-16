export type Tone = "ok" | "warn" | "bad" | "idle";

const toneClass: Record<Tone, string> = {
  ok: "bg-ok shadow-[0_0_8px_var(--ok)]",
  warn: "bg-warn shadow-[0_0_8px_var(--warn)]",
  bad: "bg-bad shadow-[0_0_8px_var(--bad)]",
  idle: "bg-muted",
};

export function StatusDot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-2.5 w-2.5 rounded-full ${toneClass[tone]} ${
        pulse ? "animate-pulse" : ""
      }`}
    />
  );
}
