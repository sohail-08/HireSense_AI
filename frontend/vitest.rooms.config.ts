import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["tests/rooms/setup.tsx"],
    include: ["tests/rooms/**/*.test.tsx"],
    fileParallelism: false,
    maxWorkers: 1,
  },
});
