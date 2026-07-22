import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "server-only": new URL("./src/test/server-only.ts", import.meta.url).pathname,
    },
  },
  oxc: {
    jsx: {
      runtime: "automatic",
    },
  },
  test: {
    coverage: {
      exclude: [
        ".next/**",
        "coverage/**",
        "next-env.d.ts",
        "next.config.*",
        "postcss.config.*",
        "tailwind.config.*",
        "vitest.config.*",
        "**/*.test.{ts,tsx}",
        "src/app/api/**",
      ],
      include: ["src/**/*.{ts,tsx}"],
      provider: "v8",
      reporter: ["text", "html", "lcov"],
    },
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
