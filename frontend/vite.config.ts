import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],

  server: {
    port: 5173,

    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/@livekit/protocol")) return "livekit-protocol";
          if (id.includes("node_modules/livekit-client")) return "livekit-client";
          if (id.includes("node_modules/@livekit/")) return "livekit-components";
        },
      },
    },
  },
});
