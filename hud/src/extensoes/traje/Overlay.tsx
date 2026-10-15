// Página /overlay: painel compacto por cima do jogo (FPS, CPU/GPU, RAM e ping). A Sexta-Feira abre esta página
// no Edge em modo app e põe a janela "sempre visível"; as métricas chegam pelo evento "traje.overlay" (~1/s).
import { useEffect } from "react";
import { api } from "../../lib/api";
import { conexao } from "../../lib/socket";
import { useHud } from "../../lib/store";
import { aoMetricas, useTraje } from "./store";
import type { MetricasOverlay } from "./tipos";

function cor(valor: number | null, atencao: number, alerta: number): string {
  if (valor == null) return "text-aco";
  return valor >= alerta ? "text-coral" : valor >= atencao ? "text-ambar" : "text-gelo";
}

function Celula({ rotulo, valor, sufixo, classe }: { rotulo: string; valor: number | null; sufixo: string; classe: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[9px] uppercase tracking-[0.22em] text-aco">{rotulo}</div>
      <div className={`numeral text-[22px] font-[400] leading-none ${classe}`}>
        {valor == null ? "—" : Math.round(valor)}
        {valor != null && <span className="ml-0.5 text-[11px] text-aco">{sufixo}</span>}
      </div>
    </div>
  );
}

export default function Overlay() {
  const m = useTraje((s) => s.overlay);
  const conectado = useHud((s) => s.conectado);
  const semAcesso = useHud((s) => s.semAcesso);

  useEffect(() => {
    document.title = "Sexta-Feira Overlay";
    document.body.style.background = "#02060b";
    conexao.conectar();
    api<MetricasOverlay>("/api/traje/overlay").then(aoMetricas).catch(() => undefined);
    return () => conexao.parar();
  }, []);

  if (semAcesso) return <p className="p-3 text-sm text-coral">Sem acesso: peça para a Sexta-Feira abrir o overlay de novo.</p>;
  const fps = m?.fps ?? null;
  return (
    <main className="h-screen w-screen select-none overflow-hidden border border-[rgb(var(--luz-rgb)/0.35)] bg-tinta-funda/95 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`size-1.5 rounded-full ${conectado ? "bg-menta" : "bg-coral pulsando"}`} aria-hidden="true" />
        <span className="truncate text-[11px] uppercase tracking-[0.2em] text-[var(--luz)]">{m?.jogo || "Sexta-Feira"}</span>
        <button
          type="button"
          onClick={() => conexao.enviar({ tipo: "traje.overlay.fechar" })}
          className="ml-auto text-[13px] leading-none text-aco hover:text-gelo"
          aria-label="Fechar o overlay"
          title="Fechar"
        >
          ×
        </button>
      </div>
      <div className="mt-1 flex items-end gap-2">
        <span className={`numeral text-[44px] font-[300] leading-none ${fps == null ? "text-aco" : fps < 30 ? "text-coral" : fps < 55 ? "text-ambar" : "text-[var(--luz)]"}`}>
          {fps == null ? "—" : Math.round(fps)}
        </span>
        <span className="pb-1 text-[11px] uppercase tracking-[0.2em] text-aco">fps</span>
      </div>
      {fps == null && <div className="truncate text-[10px] text-ambar/90">FPS: {m?.fps_dica || "aguardando…"}</div>}
      <div className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2">
        <Celula rotulo="CPU" valor={m?.cpu ?? null} sufixo="%" classe={cor(m?.cpu ?? null, 85, 97)} />
        <Celula rotulo="CPU °C" valor={m?.cpu_temp ?? null} sufixo="°" classe={cor(m?.cpu_temp ?? null, 85, 95)} />
        <Celula rotulo="RAM" valor={m?.ram ?? null} sufixo="%" classe={cor(m?.ram ?? null, 85, 95)} />
        <Celula rotulo="GPU" valor={m?.gpu ?? null} sufixo="%" classe="text-gelo" />
        <Celula rotulo="GPU °C" valor={m?.gpu_temp ?? null} sufixo="°" classe={cor(m?.gpu_temp ?? null, 80, 90)} />
        <Celula rotulo="Ping" valor={m?.ping ?? null} sufixo="ms" classe={cor(m?.ping ?? null, 80, 150)} />
      </div>
    </main>
  );
}
