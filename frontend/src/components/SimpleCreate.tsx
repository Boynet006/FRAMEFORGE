"use client";

import { useState, type FormEvent } from "react";

import { api, type Project } from "@/lib/api";
import { Card } from "./Card";

const LENGTHS: Array<[number, string]> = [[30, "30 sec"], [60, "1 min"], [120, "2 min"], [300, "5 min"], [600, "10 min"]];
const LOOKS: Array<[string, string]> = [
  ["3d-animated", "3D animated"], ["cartoon", "Cartoon"], ["cinematic", "Cinematic"], ["photoreal", "Photoreal"], ["anime", "Anime"],
];
const QUALITIES: Array<[string, string]> = [["draft", "Quick preview"], ["final", "HD 720p"]];

const EXAMPLES = [
  "Two cats in a cosy café argue about why humans are terrible at choosing food. One is a smug orange tabby in sunglasses, the other a cheerful calico in a chef's hat.",
  "A nervous young robot interviews for a job at a bakery run by a grumpy old badger in a flour-covered apron.",
  "Two penguins on an ice floe plan a holiday somewhere warm, but can't agree on where to go.",
];

export function Chips<T extends string | number>({
  label, options, value, onChange,
}: { label: string; options: Array<[T, string]>; value: T; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted">{label}</span>
      <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
        {options.map(([v, text]) => (
          <button
            key={String(v)}
            type="button"
            role="radio"
            aria-checked={v === value}
            onClick={() => onChange(v)}
            className={`rounded-full border px-3 py-1 text-sm transition-colors ${
              v === value ? "border-accent bg-accent/15 text-foreground" : "border-border bg-surface-2 text-muted hover:text-foreground"
            }`}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

export function SimpleCreate({ onCreated }: { onCreated: (p: Project) => void }) {
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(60);
  const [style, setStyle] = useState("3d-animated");
  const [quality, setQuality] = useState("draft");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const text = prompt.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.createProject({
        title: text.split(/[.!?\n]/)[0].slice(0, 60),
        prompt: text,
        settings: { duration_s: duration, aspect_ratio: "16:9", style, quality },
      });
      try {
        await api.generateFull(p.id);
      } catch (err) {
        setError(`The project was saved, but making the video could not start: ${err instanceof Error ? err.message : String(err)}`);
      }
      setPrompt("");
      onCreated(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Make a video">
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">What happens in your video?</span>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={4}
            required
            placeholder="Describe the characters, where they are and what they talk about…"
            className="resize-y rounded-md border border-border bg-surface-2 px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-accent/60"
          />
          <span className="text-xs text-muted">
            Tip: say what each character is (a cat, a robot, an old man), their colours and clothes, the place and
            the mood. Conversations between two characters work best.
          </span>
        </label>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
          Try an example:
          {EXAMPLES.map((ex, i) => (
            <button key={i} type="button" onClick={() => setPrompt(ex)}
              className="rounded-full border border-border px-2.5 py-0.5 hover:border-accent/60 hover:text-foreground">
              {["Café cats", "Robot interview", "Penguin holiday"][i]}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-3">
          <Chips label="Length" options={LENGTHS} value={duration} onChange={setDuration} />
          <Chips label="Look" options={LOOKS} value={style} onChange={setStyle} />
          <Chips label="Quality" options={QUALITIES} value={quality} onChange={setQuality} />
        </div>
        {error && <p className="text-sm text-bad break-words">{error}</p>}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted">Everything runs on this computer. Longer videos take longer to make.</p>
          <button
            type="submit"
            disabled={busy || !prompt.trim()}
            className="rounded-md bg-accent px-5 py-2.5 text-sm font-semibold text-black hover:brightness-110 disabled:opacity-40"
          >
            {busy ? "Starting…" : "Make my video"}
          </button>
        </div>
      </form>
    </Card>
  );
}
