import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const frontendDir = fileURLToPath(new URL("./frontend/", import.meta.url));

export default defineConfig({
  root: "frontend",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: `${frontendDir}index.html`,
        "recipient-consent": `${frontendDir}recipient-consent.html`
      }
    }
  }
});
