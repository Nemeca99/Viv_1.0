import fs from "node:fs";
import path from "node:path";

const MASTER_ENV = "L:\\Python_Master\\.venv";
const PROJECT_OVERRIDES = [
  { root: "D:\\LocalAi\\Continue", env: "L:\\.venv" },
];

function usableVenv(root) {
  return fs.existsSync(path.join(root, "pyvenv.cfg")) &&
    fs.existsSync(path.join(root, "Scripts", "python.exe"));
}

function isWithin(cwd, root) {
  const child = path.resolve(cwd).toLowerCase();
  const parent = path.resolve(root).replace(/[\\/]+$/, "").toLowerCase();
  return child === parent || child.startsWith(parent + path.sep.toLowerCase());
}

function projectVenv(cwd) {
  let current = path.resolve(cwd);
  const driveRoot = path.parse(current).root;

  while (true) {
    // Ignore L:\\'s old root .venv; the clean master is the drive-wide fallback.
    if (current.toLowerCase() !== driveRoot.toLowerCase()) {
      if (usableVenv(current)) return current;

      for (const name of [".venv", "venv", "env"]) {
        const candidate = path.join(current, name);
        if (usableVenv(candidate)) return candidate;
      }

      // Support a uniquely named environment such as .movie-scripts-venv.
      try {
        const custom = fs.readdirSync(current, { withFileTypes: true })
          .filter((entry) => entry.isDirectory() && /(?:\\.venv|-venv)$/i.test(entry.name))
          .map((entry) => path.join(current, entry.name))
          .filter(usableVenv);
        if (custom.length === 1) return custom[0];
      } catch {
        // An unreadable parent is not a reason to abort the user's command.
      }
    }

    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return undefined;
}

export const AutoVenvPlugin = async () => ({
  "shell.env": async (input, output) => {
    const cwd = typeof input.cwd === "string" ? input.cwd : process.cwd();
    let selected;

    for (const entry of PROJECT_OVERRIDES) {
      if (isWithin(cwd, entry.root) && usableVenv(entry.env)) {
        selected = entry.env;
        break;
      }
    }
    selected ??= projectVenv(cwd);
    selected ??= usableVenv(MASTER_ENV) ? MASTER_ENV : undefined;
    if (!selected) return;

    output.env ??= {};
    const pathKey = Object.keys(output.env).find((key) => key.toLowerCase() === "path") ??
      Object.keys(process.env).find((key) => key.toLowerCase() === "path") ?? "PATH";
    const currentPath = output.env[pathKey] ?? process.env[pathKey] ?? process.env.PATH ?? "";
    const scripts = path.join(selected, "Scripts");
    const segments = String(currentPath).split(path.delimiter).filter(Boolean);
    if (!segments.some((part) => path.resolve(part).toLowerCase() === path.resolve(scripts).toLowerCase())) {
      segments.unshift(scripts);
    }

    output.env[pathKey] = segments.join(path.delimiter);
    output.env.VIRTUAL_ENV = path.resolve(selected);
  },
});
