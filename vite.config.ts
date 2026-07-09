import { readFileSync } from "fs";
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

const pkg = JSON.parse(readFileSync("./package.json", "utf-8"));

export default defineConfig({
  vite: {
    define: {
      __APP_VERSION__: JSON.stringify(pkg.version ?? "dev"),
    },
  },
});
