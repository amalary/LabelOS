import baseConfig from "@label-os/config/eslint/base";
import nextPlugin from "@next/eslint-plugin-next";

export default [
  ...baseConfig,
  {
    files: ["**/*.{js,mjs,cjs,ts,tsx}"],
    plugins: {
      "@next/next": nextPlugin,
    },
    rules: {
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
    },
  },
  {
    ignores: ["next-env.d.ts"],
  },
];
