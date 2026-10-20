import { useTheme } from "../theme/ThemeProvider";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="flex gap-0.5 rounded-full border border-black/20 bg-white p-1 dark:border-white/10 dark:bg-white/5"
    >
      <span
        className={`flex h-[22px] w-[22px] items-center justify-center rounded-full transition-colors ${
          !isDark ? "bg-white shadow-sm" : ""
        }`}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={!isDark ? "#6366F1" : "#9AA1B1"} strokeWidth="2.2">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      </span>
      <span
        className={`flex h-[22px] w-[22px] items-center justify-center rounded-full transition-colors ${
          isDark ? "bg-white/15 shadow-sm" : ""
        }`}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={isDark ? "#C7CBFF" : "#9AA1B1"} strokeWidth="2.2">
          <path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" />
        </svg>
      </span>
    </button>
  );
}
