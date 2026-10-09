// Fase 4: quadro Kanban de tarefas, linha do tempo do dia/semana e o Pomodoro do modo foco.
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useHud } from "../lib/store";

interface Tarefa {
  id: number;
  titulo: string;
  projeto: string;
  prazo_texto: string;
  atrasada: boolean;
  prioridade: "alta" | "media" | "baixa";
  estimativa: number | null;
  status: "a_fazer" | "fazendo" | "feito";
}

const COLUNAS: [Tarefa["status"], string][] = [
  ["a_fazer", "A fazer"],
  ["fazendo", "Fazendo"],
  ["feito", "Feito"],
];
const COR_PRIORIDADE = { alta: "bg-coral", media: "bg-[var(--luz)]", baixa: "bg-aco" };

function duracao(min: number | null) {
  if (!min) return "";
  return min >= 60 ? `${Math.floor(min / 60)}h${min % 60 ? String(min % 60).padStart(2, "0") : ""}` : `${min} min`;
}

export function Tarefas({ dados }: { dados: { colunas: Record<Tarefa["status"], Tarefa[]> } }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [arrastando, setArrastando] = useState<number | null>(null);
  const [alvo, setAlvo] = useState<string | null>(null);
  const [nova, setNova] = useState("");
  const mover = (id: number, status: string) => api(`/api/tarefas/${id}`, { method: "PATCH", json: { status } }).catch((e) => avisar(e.message, "erro"));
  const criar = () => {
    if (!nova.trim()) return;
    api("/api/tarefas", { method: "POST", json: { texto: nova } })
      .then(() => setNova(""))
      .catch((e) => avisar(e.message, "erro"));
  };
  const colunas = dados?.colunas ?? { a_fazer: [], fazendo: [], feito: [] };

  return (
    <div className="w-[640px]">
      <div className="grid grid-cols-3 gap-3">
        {COLUNAS.map(([status, rotulo], ci) => (
          <section
            key={status}
            aria-label={rotulo}
            onDragOver={(e) => {
              e.preventDefault();
              setAlvo(status);
            }}
            onDragLeave={() => setAlvo(null)}
            onDrop={() => {
              if (arrastando !== null) mover(arrastando, status);
              setArrastando(null);
              setAlvo(null);
            }}
            className={`min-h-[180px] rounded border p-2 transition-colors ${alvo === status ? "border-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.06)]" : "border-aco/20"}`}
          >
            <h3 className="flex justify-between text-xs uppercase tracking-[0.18em] text-aco mb-2">
              {rotulo} <span className="text-[var(--luz)]/70">{colunas[status].length}</span>
            </h3>
            <ul className="space-y-1.5 max-h-[300px] overflow-y-auto rolagem pr-0.5">
              {colunas[status].map((t) => (
                <li
                  key={t.id}
                  draggable
                  data-clicavel
                  onDragStart={() => setArrastando(t.id)}
                  onDragEnd={() => setArrastando(null)}
                  className={`group rounded border border-[var(--luz)]/25 bg-[rgb(var(--luz-rgb)/0.04)] px-2 py-1.5 cursor-grab ${t.status === "feito" ? "opacity-60" : ""}`}
                >
                  <div className="flex items-start gap-1.5">
                    <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${COR_PRIORIDADE[t.prioridade]}`} title={`Prioridade ${t.prioridade}`} />
                    <span className={`flex-1 text-[13px] leading-snug text-gelo ${t.status === "feito" ? "line-through" : ""}`}>{t.titulo}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px]">
                    {t.prazo_texto && <span className={t.atrasada ? "text-coral" : "text-aco"}>{t.prazo_texto}</span>}
                    {t.estimativa ? <span className="text-aco/70">{duracao(t.estimativa)}</span> : null}
                    {t.projeto && <span className="text-[var(--luz)]/70 truncate">{t.projeto}</span>}
                    <span className="ml-auto flex gap-0.5 opacity-60 group-hover:opacity-100">
                      {ci > 0 && (
                        <button
                          type="button"
                          data-clicavel
                          aria-label={`Mover ${t.titulo} para ${COLUNAS[ci - 1][1]}`}
                          onClick={() => mover(t.id, COLUNAS[ci - 1][0])}
                          className="px-1 text-aco hover:text-gelo"
                        >
                          ◀
                        </button>
                      )}
                      {ci < 2 && (
                        <button
                          type="button"
                          data-clicavel
                          aria-label={`Mover ${t.titulo} para ${COLUNAS[ci + 1][1]}`}
                          onClick={() => mover(t.id, COLUNAS[ci + 1][0])}
                          className="px-1 text-aco hover:text-[var(--luz)]"
                        >
                          ▶
                        </button>
                      )}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <form
        className="mt-2 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          criar();
        }}
      >
        <input
          value={nova}
          onChange={(e) => setNova(e.target.value)}
          placeholder='Nova tarefa: "revisar o relatório até sexta, urgente"'
          aria-label="Nova tarefa"
          className="flex-1 bg-transparent border-b border-aco/40 py-1 text-[13px] text-gelo outline-none focus:border-[var(--luz)] placeholder:text-aco/50"
        />
        <button type="submit" data-clicavel className="text-sm text-[var(--luz)] hover:text-gelo">
          Anotar
        </button>
      </form>
    </div>
  );
}

interface BlocoPlano {
  inicio: string;
  fim: string;
  titulo: string;
  tipo: "evento" | "lembrete" | "almoco" | "tarefa" | "pausa";
  minutos: number;
  prioridade?: string;
}

interface DiaSemana {
  dia: string;
  data: string;
  tarefas: string[];
  eventos: string[];
}

const ESTILO_BLOCO: Record<BlocoPlano["tipo"], string> = {
  tarefa: "border-[var(--luz)]/60 bg-[rgb(var(--luz-rgb)/0.08)]",
  evento: "border-gelo/50 bg-gelo/5",
  lembrete: "border-gelo/30",
  almoco: "border-aco/30 border-dashed",
  pausa: "border-aco/20 border-dashed",
};

export function Plano({ dados }: { dados: { blocos?: BlocoPlano[]; sobras?: string[]; data?: string; semana?: DiaSemana[] } }) {
  const [agora, setAgora] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setAgora(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  if (dados?.semana)
    return (
      <ol className="w-[460px] space-y-1.5">
        {dados.semana.map((d) => (
          <li key={d.data} className="grid grid-cols-[86px_1fr] gap-3 border-t border-aco/15 pt-1.5 first:border-t-0">
            <span className="text-[13px] text-[var(--luz)] first-letter:uppercase">
              {d.dia} <span className="text-aco text-xs">{d.data}</span>
            </span>
            <span className="text-[13px] text-gelo leading-snug">
              {[...d.eventos.map((e) => `● ${e}`), ...d.tarefas.map((t) => `□ ${t}`)].join("   ") || <span className="text-aco/60">livre</span>}
            </span>
          </li>
        ))}
      </ol>
    );

  const blocos = dados?.blocos ?? [];
  const hora = `${String(agora.getHours()).padStart(2, "0")}:${String(agora.getMinutes()).padStart(2, "0")}`;
  if (!blocos.length) return <p className="w-[360px] text-sm text-aco">Dia livre: nenhuma tarefa pendente nem compromisso.</p>;
  return (
    <div className="w-[420px]">
      <ol className="relative max-h-[430px] overflow-y-auto rolagem pr-1 space-y-1.5" aria-label={`Plano do dia ${dados.data ?? ""}`}>
        {blocos.map((b, i) => {
          const atual = b.inicio <= hora && hora < b.fim;
          return (
            <li key={i} className="grid grid-cols-[48px_1fr] gap-2 items-stretch">
              <span className={`numeral text-right text-sm pt-1 ${atual ? "text-[var(--luz)]" : "text-aco"}`}>{b.inicio}</span>
              <div
                className={`rounded border px-2.5 py-1.5 ${ESTILO_BLOCO[b.tipo]} ${atual ? "ring-1 ring-[var(--luz)]" : ""}`}
                style={{ minHeight: Math.min(80, 22 + b.minutos / 3) }}
              >
                <span className={`block text-[13px] leading-snug ${b.tipo === "pausa" || b.tipo === "almoco" ? "text-aco" : "text-gelo"}`}>{b.titulo}</span>
                <span className="text-[11px] text-aco/70">
                  até {b.fim} · {b.minutos} min{atual ? " · agora" : ""}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      {dados.sobras && dados.sobras.length > 0 && <p className="mt-2 text-xs text-aco">Não couberam hoje: {dados.sobras.join(", ")}.</p>}
    </div>
  );
}

interface EstadoFoco {
  fase: "foco" | "pausa";
  ciclo: number;
  ciclos: number;
  tarefa: string;
  restante: number;
  duracao: number;
  pausado: boolean;
  agora: number;
}

export function Foco({ dados }: { dados: EstadoFoco }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [restante, setRestante] = useState(dados.restante);
  useEffect(() => {
    // conta localmente a partir do último estado enviado (o servidor só manda as mudanças de fase)
    const base = Date.now();
    setRestante(dados.restante);
    if (dados.pausado) return;
    const id = window.setInterval(() => setRestante(Math.max(0, dados.restante - (Date.now() - base) / 1000)), 250);
    return () => window.clearInterval(id);
  }, [dados.agora, dados.restante, dados.pausado]);
  const comando = (acao: string) => api("/api/foco", { method: "POST", json: { acao } }).catch((e) => avisar(e.message, "erro"));
  const fracao = dados.duracao ? restante / dados.duracao : 0;
  const raio = 70;
  const circ = 2 * Math.PI * raio;
  const mm = String(Math.floor(restante / 60)).padStart(2, "0");
  const ss = String(Math.floor(restante % 60)).padStart(2, "0");

  return (
    <div className="w-[260px] flex flex-col items-center">
      <div className="relative size-[180px]">
        <svg viewBox="0 0 180 180" className="absolute inset-0 -rotate-90" aria-hidden>
          <circle cx="90" cy="90" r={raio} fill="none" stroke="currentColor" strokeWidth="3" className="text-aco/20" />
          <circle
            cx="90"
            cy="90"
            r={raio}
            fill="none"
            stroke="var(--luz)"
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - fracao)}
            style={{ transition: "stroke-dashoffset 0.25s linear" }}
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center text-center">
          <div>
            <div className="numeral text-[44px] leading-none text-gelo" role="timer" aria-live="off">
              {mm}:{ss}
            </div>
            <div className="mt-1 text-xs uppercase tracking-[0.2em] text-[var(--luz)]">{dados.pausado ? "pausado" : dados.fase}</div>
          </div>
        </div>
      </div>
      {dados.tarefa && <p className="mt-2 text-[13px] text-gelo text-center leading-snug">{dados.tarefa}</p>}
      <p className="text-xs text-aco mt-1">
        Ciclo {dados.ciclo} de {dados.ciclos} · notificações silenciadas
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          data-clicavel
          onClick={() => comando(dados.pausado ? "retomar" : "pausar")}
          className="px-4 py-1 rounded-full border border-aco/40 text-sm text-aco hover:text-gelo"
        >
          {dados.pausado ? "Retomar" : "Pausar"}
        </button>
        <button
          type="button"
          data-clicavel
          onClick={() => comando("encerrar")}
          className="px-4 py-1 rounded-full border border-coral/50 text-sm text-coral hover:bg-coral/10"
        >
          Encerrar
        </button>
      </div>
    </div>
  );
}
