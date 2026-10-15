// Sequência de inicialização ("sistemas online"): os módulos aparecem um a um com o resultado da checagem,
// um arco de progresso e "SISTEMAS ONLINE" no fim; depois some sozinha (clique ou Esc pulam).
import { useEffect, useState } from "react";
import { useTraje } from "./store";
import type { ItemInicializacao, Nivel } from "./tipos";

const RAIO = 92;
const CIRCUNFERENCIA = 2 * Math.PI * RAIO;

export function IconeNivel({ nivel, tamanho = 16 }: { nivel: Nivel; tamanho?: number }) {
  const cor = nivel === "ok" ? "text-menta" : nivel === "aviso" ? "text-ambar" : "text-coral";
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 ${cor}`} aria-hidden="true">
      {nivel === "ok" ? (
        <path d="m5 12.5 4.5 4.5L19 7.5" />
      ) : (
        <>
          <path d="M12 3.5 2.8 19.5h18.4L12 3.5Z" />
          <path d="M12 10v4.2M12 17.1v.1" />
        </>
      )}
    </svg>
  );
}

const ROTULO_NIVEL: Record<Nivel, string> = { ok: "ok", aviso: "atenção", falha: "falhou" };

function Linha({ item }: { item: ItemInicializacao }) {
  return (
    <li className="surgir flex items-start gap-3 py-1.5 border-b border-aco/15">
      <IconeNivel nivel={item.nivel} />
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] tracking-wide text-gelo">{item.modulo}</span>
        <span className="block truncate text-xs text-aco">{item.detalhe}</span>
      </span>
      <span className={`text-[10px] uppercase tracking-[0.18em] ${item.nivel === "ok" ? "text-menta/80" : item.nivel === "aviso" ? "text-ambar" : "text-coral"}`}>
        {ROTULO_NIVEL[item.nivel]}
      </span>
    </li>
  );
}

export default function Inicializacao() {
  const evento = useTraje((s) => s.inicializacao);
  const dispensar = useTraje((s) => s.dispensar);
  const [saindo, setSaindo] = useState(false);
  const fim = evento?.fase === "fim";

  useEffect(() => {
    if (!evento) return;
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispensar();
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [evento, dispensar]);

  useEffect(() => {
    if (!fim) {
      setSaindo(false);
      return;
    }
    const sumir = window.setTimeout(() => setSaindo(true), 2200);
    const fechar = window.setTimeout(dispensar, 3000);
    return () => {
      window.clearTimeout(sumir);
      window.clearTimeout(fechar);
    };
  }, [fim, dispensar]);

  if (!evento) return null;
  const progresso = evento.total ? Math.min(1, evento.indice / evento.total) : 0;
  const falhas = evento.itens.filter((i) => !i.ok).length;
  return (
    <div
      className={`absolute inset-0 z-[3600] grid place-items-center bg-tinta-funda/85 backdrop-blur-sm transition-opacity duration-700 ${saindo ? "opacity-0" : "opacity-100"}`}
      role="status"
      aria-live="polite"
      aria-label="Sequência de inicialização"
      onClick={dispensar}
    >
      <div className="flex w-[min(860px,92vw)] flex-col items-center gap-10 md:flex-row md:items-center">
        <div className="relative grid size-[230px] shrink-0 place-items-center">
          <svg width={230} height={230} viewBox="0 0 230 230" className="absolute inset-0" aria-hidden="true">
            <circle cx={115} cy={115} r={RAIO + 14} fill="none" stroke="rgb(var(--luz-rgb) / 0.12)" strokeWidth={1} strokeDasharray="2 6" />
            <circle cx={115} cy={115} r={RAIO} fill="none" stroke="rgb(var(--luz-rgb) / 0.15)" strokeWidth={6} />
            <circle
              cx={115}
              cy={115}
              r={RAIO}
              fill="none"
              stroke="var(--luz)"
              strokeWidth={6}
              strokeLinecap="round"
              strokeDasharray={CIRCUNFERENCIA}
              strokeDashoffset={CIRCUNFERENCIA * (1 - progresso)}
              transform="rotate(-90 115 115)"
              style={{ transition: "stroke-dashoffset 0.25s ease-out", filter: "drop-shadow(0 0 8px rgb(var(--luz-rgb) / 0.6))" }}
            />
          </svg>
          <svg width={230} height={230} viewBox="0 0 230 230" className={`absolute inset-0 ${fim ? "" : "girando"}`} aria-hidden="true">
            <path d="M115 9 a106 106 0 0 1 75 31" fill="none" stroke="var(--luz-quente)" strokeWidth={2} strokeLinecap="round" opacity={0.7} />
          </svg>
          <div className="text-center">
            <div className="numeral text-5xl font-[300] text-[var(--luz)] brilho">{Math.round(progresso * 100)}%</div>
            <div className="mt-1 text-[11px] uppercase tracking-[0.3em] text-aco">
              {evento.indice}/{evento.total}
            </div>
          </div>
        </div>
        <div className="w-full min-w-0 flex-1">
          <p className={`numeral text-[34px] font-[300] leading-none tracking-[0.12em] ${fim ? "text-[var(--luz)] brilho" : "text-gelo pulsando"}`}>
            {fim ? "SISTEMAS ONLINE" : "INICIALIZANDO"}
          </p>
          <p className="mt-2 text-xs uppercase tracking-[0.22em] text-aco">
            {fim ? (falhas ? `${falhas} módulo${falhas > 1 ? "s" : ""} com falha` : "todos os sistemas operacionais") : `checando ${evento.modulo}…`}
          </p>
          <ul className="mt-5 max-h-[52vh] overflow-hidden">
            {evento.itens.map((item) => (
              <Linha key={item.id} item={item} />
            ))}
          </ul>
          <p className="mt-4 text-[11px] text-aco/80">Clique ou Esc para pular</p>
        </div>
      </div>
    </div>
  );
}
