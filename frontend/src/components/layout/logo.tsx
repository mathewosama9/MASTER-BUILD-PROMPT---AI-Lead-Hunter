export function LogoMark({ className = "size-8" }: { className?: string }) {
  // Placeholder for the "codex" mark: a geometric C with code brackets, in brand colours.
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden fill="none">
      <rect width="64" height="64" rx="14" fill="#0E0F31" />
      <path d="M41 18H27a9 9 0 0 0-9 9v10a9 9 0 0 0 9 9h14" stroke="#1D79FF" strokeWidth="7" strokeLinecap="square" />
      <path d="M33 26l-5 6 5 6" stroke="#FFC100" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M40 26l5 6-5 6" stroke="#FFC100" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
