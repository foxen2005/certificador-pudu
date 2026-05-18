import { useRef, useState } from "react";
import { X } from "lucide-react";

interface UploadBoxProps {
  label: string;
  hint: string;
  icon: string;
  accept: string;
  optionalTag?: string;
  file: File | null;
  onChange: (file: File | null) => void;
}

export function UploadBox({
  label,
  hint,
  icon,
  accept,
  optionalTag,
  file,
  onChange,
}: UploadBoxProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  const filled = !!file;

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files[0];
        if (f) onChange(f);
      }}
      className={`relative cursor-pointer rounded-lg border-2 p-4 text-center transition-all ${
        filled
          ? "border-success bg-success/5 border-solid"
          : drag
            ? "border-primary bg-primary/5 border-dashed"
            : "border-border bg-muted/30 border-dashed hover:border-primary hover:bg-primary/5"
      }`}
    >
      {optionalTag && (
        <span className="absolute left-2 top-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
          {optionalTag}
        </span>
      )}
      {filled && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onChange(null);
            if (inputRef.current) inputRef.current.value = "";
          }}
          className="absolute right-1.5 top-1.5 rounded p-0.5 text-muted-foreground hover:text-primary"
          aria-label="Quitar archivo"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
      <div className="text-2xl leading-none">{icon}</div>
      <div className="mt-1.5 text-xs font-semibold text-foreground">{label}</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
      {file && (
        <div className="mt-1 truncate text-[11px] font-semibold text-success">
          ✓ {file.name}
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          if (f) onChange(f);
        }}
      />
    </div>
  );
}