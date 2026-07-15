import { useEffect } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { APP_VERSION } from "@/lib/version";

const STORAGE_KEY = "certificador-version";

export function VersionBadge() {
  useEffect(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (stored && stored !== APP_VERSION) {
      toast("Nueva versión disponible", {
        description: `Se actualizó de ${stored} a ${APP_VERSION}. Recarga la página para usar la última versión.`,
        action: {
          label: "Recargar",
          onClick: () => window.location.reload(),
        },
        duration: 10_000,
      });
    }
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, APP_VERSION);
    }
  }, []);

  return (
    <Badge variant="secondary" className="font-mono text-xs" title={`Versión ${APP_VERSION}`}>
      v{APP_VERSION}
    </Badge>
  );
}
