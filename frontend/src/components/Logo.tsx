// Identidad visual de NotarIA: sello notarial circular (anillo dorado doble,
// inicial serif y destello de IA) + wordmark con "IA" en degradado dorado.

export function LogoMark({ className = "h-10 w-10" }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="notaria-navy" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2e5382" />
          <stop offset="0.55" stopColor="#16263d" />
          <stop offset="1" stopColor="#0d1828" />
        </linearGradient>
        <linearGradient id="notaria-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#eed9a0" />
          <stop offset="0.5" stopColor="#c79a3d" />
          <stop offset="1" stopColor="#a87f2c" />
        </linearGradient>
      </defs>

      {/* Cuerpo del sello */}
      <circle cx="24" cy="24" r="23" fill="url(#notaria-navy)" />
      {/* Doble anillo, como un sello notarial */}
      <circle cx="24" cy="24" r="20.5" fill="none" stroke="url(#notaria-gold)" strokeWidth="1.5" />
      <circle
        cx="24"
        cy="24"
        r="17.2"
        fill="none"
        stroke="url(#notaria-gold)"
        strokeWidth="0.6"
        opacity="0.65"
        strokeDasharray="2.2 2.2"
      />

      {/* Inicial serif */}
      <text
        x="24"
        y="30.5"
        textAnchor="middle"
        fontFamily="Georgia, 'Times New Roman', serif"
        fontSize="19"
        fontWeight="700"
        fill="url(#notaria-gold)"
      >
        N
      </text>
      {/* Rúbrica bajo la inicial */}
      <path
        d="M16 33.5 C 20 35.5, 28 35.5, 32 33.5"
        fill="none"
        stroke="url(#notaria-gold)"
        strokeWidth="1"
        strokeLinecap="round"
        opacity="0.9"
      />

      {/* Destello de IA sobre el anillo */}
      <path
        d="M35.5 7.5 l1.3 3.2 3.2 1.3 -3.2 1.3 -1.3 3.2 -1.3 -3.2 -3.2 -1.3 3.2 -1.3 z"
        fill="#eed9a0"
      />
      <circle cx="40.5" cy="16.5" r="1" fill="#eed9a0" opacity="0.9" />
    </svg>
  );
}

export function Logo({
  size = "text-2xl",
  tone = "dark",
}: {
  size?: string;
  /** "dark" para fondos oscuros (sidebar), "light" para fondos claros (welcome). */
  tone?: "dark" | "light";
}) {
  return (
    <span
      className={`font-serif font-semibold tracking-tight ${size} ${
        tone === "dark" ? "text-slate-100" : "text-brand-900"
      }`}
    >
      Notar
      <span className="bg-gradient-to-br from-accent-300 via-accent-500 to-accent-600 bg-clip-text text-transparent">
        IA
      </span>
    </span>
  );
}
