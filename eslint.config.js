const { defineConfig } = require("eslint/config");
const eslintJs = require("@eslint/js");
const globals = require("globals");

module.exports = defineConfig([
  // The three guarded MCP server entry points are the only JavaScript this repo tracks
  // (force-app/ stays an empty skeleton; org metadata is never versioned here).
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: {
      sourceType: "module",
      ecmaVersion: "latest",
      globals: {
        ...globals.node
      }
    },
    plugins: {
      eslintJs
    },
    extends: ["eslintJs/recommended"]
  }
]);
