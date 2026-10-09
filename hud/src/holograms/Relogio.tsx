import { useEffect, useState } from "react";

const DIAS = ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"];
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

export function useAgora(intervalo = 1000): Date {
  const [agora, setAgora] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setAgora(new Date()), intervalo);
    return () => window.clearInterval(id);
  }, [intervalo]);
  return agora;
}

export function dataPorExtenso(d: Date): string {
  return `${DIAS[d.getDay()]}, ${d.getDate()} de ${MESES[d.getMonth()]}`;
}

export default function Relogio() {
  const agora = useAgora(250);
  const s = agora.getSeconds() + agora.getMilliseconds() / 1000;
  const m = agora.getMinutes() + s / 60;
  const h = (agora.getHours() % 12) + m / 60;
  const raio = 104;
  const c = 2 * Math.PI * raio;
  return (
    <div className="w-[260px] flex flex-col items-center">
      <svg width="240" height="240" viewBox="0 0 240 240" role="img" aria-label={`São ${agora.getHours()} horas e ${agora.getMinutes()} minutos`}>
        {Array.from({ length: 60 }, (_, i) => (
          <line
            key={i}
            x1="120"
            y1={i % 5 === 0 ? 18 : 22}
            x2="120"
            y2="28"
            stroke={i % 5 === 0 ? "var(--color-gelo)" : "var(--color-aco)"}
            strokeOpacity={i % 5 === 0 ? 0.8 : 0.5}
            strokeWidth={i % 15 === 0 ? 2 : 1}
            transform={`rotate(${i * 6} 120 120)`}
          />
        ))}
        <circle
          cx="120"
          cy="120"
          r={raio}
          fill="none"
          stroke="var(--luz)"
          strokeWidth="2"
          strokeDasharray={`${(s / 60) * c} ${c}`}
          transform="rotate(-90 120 120)"
          style={{ filter: "drop-shadow(0 0 5px rgb(var(--luz-rgb) / 0.8))" }}
        />
        <line x1="120" y1="120" x2="120" y2="66" stroke="var(--color-gelo)" strokeWidth="2.5" strokeLinecap="round" transform={`rotate(${h * 30} 120 120)`} />
        <line x1="120" y1="120" x2="120" y2="42" stroke="var(--color-gelo)" strokeWidth="1.5" strokeLinecap="round" transform={`rotate(${m * 6} 120 120)`} />
        <circle cx="120" cy="120" r="4" fill="var(--luz)" />
      </svg>
      <p className="numeral text-5xl font-[250] text-gelo mt-1 brilho">
        {String(agora.getHours()).padStart(2, "0")}:{String(agora.getMinutes()).padStart(2, "0")}
      </p>
      <p className="text-sm text-aco first-letter:uppercase">{dataPorExtenso(agora)}</p>
    </div>
  );
}
