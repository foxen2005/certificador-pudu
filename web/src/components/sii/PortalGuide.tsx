import { ExternalLink } from "lucide-react";

interface PortalStep {
  text: string;
  url?: string;
  highlight?: boolean;
}

interface Props {
  title: string;
  url: string;
  steps: PortalStep[];
  note?: string;
}

export function PortalGuide({ title, url, steps, note }: Props) {
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-lg">🌐</span>
        <span className="font-semibold text-blue-900">{title}</span>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto flex items-center gap-1 rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700"
        >
          Abrir portal <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      <ol className="space-y-2">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-2 text-sm text-blue-800">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-200 text-xs font-bold text-blue-700">
              {i + 1}
            </span>
            <span className={s.highlight ? "font-semibold" : ""}>{s.text}</span>
          </li>
        ))}
      </ol>
      {note && (
        <div className="mt-3 rounded border-l-4 border-amber-400 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠️ {note}
        </div>
      )}
    </div>
  );
}
