import React from "react";

const ICON_PATHS = Object.freeze({
  processing: ["M4 5.5h16", "M4 12h16", "M4 18.5h10", "M7 3v5", "M16 9.5v5", "M11 16v5"],
  diagnosis: ["M10.5 4H6a2 2 0 0 0-2 2v4.5", "M13.5 4H18a2 2 0 0 1 2 2v4.5", "M10.5 20H6a2 2 0 0 1-2-2v-4.5", "M13.5 20H18a2 2 0 0 0 2-2v-4.5", "M8 12h8", "M12 8v8"],
  sparkle: ["m12 3 1.35 3.65L17 8l-3.65 1.35L12 13l-1.35-3.65L7 8l3.65-1.35L12 3Z", "m18.5 14 .7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z", "M5 15.5h4", "M7 13.5v4"],
  color: ["M4 6h10", "M18 6h2", "M14 3v6", "M4 12h3", "M11 12h9", "M7 9v6", "M4 18h8", "M16 18h4", "M12 15v6"],
  compress: ["M8 3v5H3", "m8 8-5-5", "M16 21v-5h5", "m-5 0 5 5", "M16 3v5h5", "m-5 0 5-5", "M8 21v-5H3", "m5 0-5 5"],
  retouch: ["M4 20c3.5 0 5.5-1.3 5.5-3.6 0-1.8-1.2-3-3-3S3 15 3 17c0 1.1.4 2.1 1 3Z", "m9.2 13.6 7.9-7.9a2.1 2.1 0 0 1 3 3l-8 7.9", "m15.7 7.1 3 3"],
  delivery: ["M4 5h16v11H4z", "M8 20h8", "M12 16v4", "m8 5-8 6-8-6"],
  outputs: ["M4 7.5h5l1.5 2H20v9.5H4z", "M4 7.5V5h5l1.5 2H20v2.5", "M8 14h8"],
  settings: ["M12 15.25A3.25 3.25 0 1 0 12 8.75a3.25 3.25 0 0 0 0 6.5Z", "M19.1 13.8a7.7 7.7 0 0 0 0-3.6l2-1.55-2-3.46-2.47 1a7.7 7.7 0 0 0-3.1-1.8L11.55 2h-4l-.38 2.99a7.7 7.7 0 0 0-3.1 1.8l-2.47-1-2 3.46 2 1.55a7.7 7.7 0 0 0 0 3.6l-2 1.55 2 3.46 2.47-1a7.7 7.7 0 0 0 3.1 1.8L7.55 23h4l.38-2.99a7.7 7.7 0 0 0 3.1-1.8l2.47 1 2-3.46-2-1.55Z"],
  chevron: ["m9 18 6-6-6-6"],
  sun: ["M12 4V2", "M12 22v-2", "m5.64 6.36-1.42-1.42", "m18.36 19.06-1.42-1.42", "M4 12H2", "M22 12h-2", "m5.64 17.64-1.42 1.42", "m18.36 4.94-1.42 1.42", "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"],
});

export default function HddeIcon({ name, size = 18, className = "" }) {
  const paths = ICON_PATHS[name] || ICON_PATHS.processing;
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
    >
      {paths.map((path, index) => <path key={`${name}-${index}`} d={path} />)}
    </svg>
  );
}
