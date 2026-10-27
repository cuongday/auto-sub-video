/** Small stroke icons (24px grid) so the sidebar looks the same on every OS, unlike emoji. */
const PATHS = {
  film: "M4 5h16v14H4z M8 5v14 M16 5v14 M4 9h4 M4 15h4 M16 9h4 M16 15h4",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  inbox: "M3 13l3-8h12l3 8 M3 13v5a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-5 M3 13h5l1 2h6l1-2h5",
  download: "M12 4v11 M7 10l5 5 5-5 M5 20h14",
  plus: "M12 5v14 M5 12h14",
  check: "M5 12.5l4.5 4.5L19 7",
  chevron: "M9 6l6 6-6 6",
  folderPlus: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M12 10v6 M9 13h6",
  alert: "M12 4l9 16H3z M12 10v4 M12 17v.5",
  clapper: "M4 10h16v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z M4 10l-.6-3.4 15.8-2.8.5 3.4z M8.5 6l2.2 3.2 M13.3 5.2l2.2 3.2",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-4-4",
  upload: "M12 20V9 M7 14l5-5 5 5 M5 4h14",
  book: "M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z M5 17a3 3 0 0 1 3-3h11 M9 8h6",
  headphones: "M4 15v-3a8 8 0 0 1 16 0v3 M4 15a2 2 0 0 1 2-2h1v7H6a2 2 0 0 1-2-2z M20 15a2 2 0 0 0-2-2h-1v7h1a2 2 0 0 0 2-2z",
  key: "M8 11a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M11 13.5l8-8 M16 8.5l2.5 2.5 M14 10.5l2 2",
} as const;

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 16, className = "" }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={`icon-svg ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
