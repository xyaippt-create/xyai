// 影界 HDDE 前端静态检查（CI 与本地共用）
// 只开启“几乎必然是 Bug”的规则；风格类与未使用变量暂不开启，避免一次性改动大量受保护文件。
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

const recommended = js.configs.recommended.rules;

export default [
  {
    ignores: ["dist/**", "build/**", "node_modules/**", "tmp/**", "artifacts/**", "output/**", ".venv/**"],
  },
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      // vite.config.js 的 define 在构建时注入
      globals: { ...globals.browser, __HDDE_BUILD_ID__: "readonly", __HDDE_BUILD_TIME__: "readonly" },
    },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...recommended,
      "no-unused-vars": "off",
      "no-empty": "off",
      // 以下两条属于写法偏好（如 let payload = {} 后在 try 中重新赋值），不视为 Bug
      "no-useless-assignment": "off",
      "preserve-caught-error": "off",
      // 交付清单等文案里有意使用全角空格
      "no-irregular-whitespace": ["error", { skipStrings: true, skipTemplates: true }],
      "react-hooks/rules-of-hooks": "error",
    },
  },
];
