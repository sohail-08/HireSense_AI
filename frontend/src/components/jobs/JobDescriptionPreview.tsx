import { Fragment } from "react";

type Block = { kind: "heading" | "paragraph" | "bullets" | "numbers"; lines: string[]; start?: number };

// Render the JD writer's Markdown subset as React text, never HTML. The saved
// text is authoritative; structured fields can predate manual edits.
function blocksFor(content: string, title: string): Block[] {
  const blocks: Block[] = [];
  let firstContent = true;
  for (const line of content.replace(/\r\n?/g, "\n").split("\n")) {
    const text = line.trim();
    if (!text) { blocks.push({ kind: "paragraph", lines: [] }); continue; }
    const first = firstContent;
    firstContent = false;
    const heading = /^#{1,6}\s+(.+?)(?:\s+#+)?$/.exec(text);
    if (heading) {
      // The separate title field is canonical, including after manual edits.
      if (first && /^#\s/.test(text) && heading[1].replaceAll("**", "").trim().toLowerCase() === title.trim().toLowerCase()) continue;
      blocks.push({ kind: "heading", lines: [heading[1]] });
      continue;
    }
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(text)) { blocks.push({ kind: "paragraph", lines: [] }); continue; }
    const bullet = /^[-*+]\s+(.+)$/.exec(text);
    const number = /^(\d+)[.)]\s+(.+)$/.exec(text);
    const kind = bullet ? "bullets" : number ? "numbers" : "paragraph";
    const value = bullet?.[1] ?? number?.[2] ?? text;
    const previous = blocks.at(-1);
    if (previous?.kind === kind) previous.lines.push(value);
    else blocks.push({ kind, lines: [value], start: number ? Number(number[1]) : undefined });
  }
  return blocks.filter(block => block.lines.length);
}

function inline(text: string) {
  return text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index} className="font-semibold text-slate-800">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index} className="rounded bg-blue-50 px-1 py-0.5 text-[0.9em] text-blue-800">{part.slice(1, -1)}</code>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function JobDescriptionPreview({ title, content }: { title: string; content: string }) {
  return <article aria-label="Job description preview" className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <header className="border-b border-blue-100 bg-linear-to-br from-blue-50 via-white to-violet-50/60 px-5 py-6 sm:px-7">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-blue-700">
        <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="7" width="18" height="14" rx="3" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a24 24 0 0 0 18 0M10 13h4" /></svg>Job description
      </div>
      <h3 className="break-words text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">{title}</h3>
    </header>
    <div className="space-y-4 px-5 py-6 text-sm leading-7 text-slate-600 [overflow-wrap:anywhere] sm:px-7">
      {blocksFor(content, title).map((block, index) => {
        if (block.kind === "heading") return <h4 key={index} className="flex items-center gap-2 border-t border-slate-100 pt-5 text-base font-semibold text-slate-900"><span aria-hidden="true" className="h-4 w-1 shrink-0 rounded-full bg-blue-600" />{inline(block.lines[0])}</h4>;
        if (block.kind === "bullets") return <ul key={index} className="list-disc space-y-2 pl-5 marker:text-blue-500">{block.lines.map((line, i) => <li key={i} className="pl-1">{inline(line)}</li>)}</ul>;
        if (block.kind === "numbers") return <ol key={index} start={block.start} className="list-decimal space-y-2 pl-5 marker:font-semibold marker:text-blue-700">{block.lines.map((line, i) => <li key={i} className="pl-1">{inline(line)}</li>)}</ol>;
        return <p key={index} className="whitespace-pre-line">{inline(block.lines.join("\n"))}</p>;
      })}
    </div>
  </article>;
}
