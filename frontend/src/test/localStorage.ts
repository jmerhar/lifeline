/**
 * A working ``window.localStorage`` for the tests.
 *
 * Recent Node versions define their own experimental ``localStorage`` global, which is
 * unavailable unless the process is started with ``--localstorage-file``. Where that global
 * takes precedence over the one jsdom provides, reading it throws — so anything the app
 * stores has no home and the tests that assert on it cannot run. A real browser has the
 * genuine article; this only fills the gap under the test runner.
 */

class MemoryStorage implements Storage {
  private entries = new Map<string, string>();

  get length(): number {
    return this.entries.size;
  }

  clear(): void {
    this.entries.clear();
  }

  getItem(key: string): string | null {
    return this.entries.get(key) ?? null;
  }

  key(index: number): string | null {
    return [...this.entries.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.entries.delete(key);
  }

  setItem(key: string, value: string): void {
    this.entries.set(key, String(value));
  }
}

/** Ensure ``window.localStorage`` works, and return it. */
export function installLocalStorage(): Storage {
  let usable = false;
  try {
    usable = typeof window.localStorage?.setItem === "function";
  } catch {
    // Reading the property itself can throw, which counts as unusable.
  }
  if (!usable) {
    Object.defineProperty(window, "localStorage", {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    });
  }
  return window.localStorage;
}
