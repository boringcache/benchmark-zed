#!/usr/bin/env node

const path = require("path");

const sourcePath = process.argv[2];
if (!sourcePath) {
  console.error("Usage: run-mtime-cache.js SOURCE_PATH");
  process.exit(1);
}

const sourceRoot = path.resolve(sourcePath);
const actionPath = path.join(__dirname, "deno-mtime-cache-action.js");
process.chdir(sourceRoot);
process.env["INPUT_CACHE-PATH"] = "./target";

require(actionPath);
