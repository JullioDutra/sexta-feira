// Extensão "tarefas_aprendidas": tarefas que ela aprendeu (ensinadas, gravadas ou tiradas dos agentes)
// e faz sozinha. Holograma com a lista, executar, esquecer e um campo para ensinar uma nova.
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useHud } from "../lib/store";
import type { Extensao } from "./tipos";

interface Tarefa {
  id: string;
  nome: string;
  origem: "ensinada" | "gravada" | "agente";
  objetivo?: string;
  passos?: string[];
  comandos?: string[];
  agente?: string;
  frases?: string[];
  execucoes: number;
  sucessos: number;
  ultima: { quando: number; ok: boolean; falha: string } | null;
  executando?: boolean;
}

interface Dados {
  tarefas: Tarefa[];
  gravando: string | null;
  comandos_gravados: number;
}

const ORIGEM: Record<Tarefa["origem"], string> = { ensinada: "ensinada", gravada: "gravada", agente: "de um agente" };

function Tarefas({ dados, largura = 470 }: { dados: Dados; largura?: number }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [atual, setAtual] = useState<Dados>(dados);
  const [aberta, setAberta] = useState<string | null>(null);
  const [explicacao, setExplicacao] = useState("");
  const [ensinando, setEnsinando] = useState(false);
  useEffect(() => setAtual(dados), [dados]);
  const tarefas = atual?.tarefas ?? [];

  const executar = (t: Tarefa) =>
    api<Dados & { texto: string }>(`/api/tarefas_aprendidas/${t.id}/executar`, { method: "POST" })
      .then((r) => {
        setAtual(r);
        avisar(r.texto, "info");
      })
      .catch((e) => avisar(e.message, "erro"));
  const esquecer = (t: Tarefa) =>
    api<Dados>(`/api/tarefas_aprendidas/${t.id}`, { method: "DELETE" })
      .then(setAtual)
      .catch((e) => avisar(e.message, "erro"));
  const ensinar = () => {
    if (ensinando || explicacao.trim().length < 8) return;
    setEnsinando(true);
    api<Dados>("/api/tarefas_aprendidas", { method: "POST", json: { explicacao } })
      .then((r) => {
        setAtual(r);
        setExplicacao("");
        avisar("Tarefa aprendida.", "sucesso");
      })
      .catch((e) => avisar(e.message, "erro"))
      .finally(() => setEnsinando(false));
  };

  return (
    <div style={{ width: largura }} className="space-y-2">
      {atual?.gravando && (
        <p className="text-sm text-coral" role="status">
          ● Gravando “{atual.gravando}” — {atual.comandos_gravados} passo(s). Diga “termina a gravação”.
        </p>
      )}
      <ul className="max-h-[340px] overflow-y-auto rolagem pr-1 space-y-1">
        {tarefas.length === 0 && (
          <li className="text-sm text-aco py-2 leading-snug">
            Nenhuma tarefa ainda. Ensine com “aprende a tarefa X: …”, grave com “começa a gravar a tarefa X” ou, depois de um agente terminar,
            “salva isso como tarefa X”.
          </li>
        )}
        {tarefas.map((t) => {
          const passos = t.comandos ?? t.passos ?? [];
          return (
            <li key={t.id} className="border-b border-aco/10 py-1">
              <div className="flex items-start gap-2">
                <button type="button" onClick={() => setAberta(aberta === t.id ? null : t.id)} className="min-w-0 flex-1 text-left" aria-expanded={aberta === t.id}>
                  <span className="block text-[14px] text-gelo">
                    {t.ultima ? (t.ultima.ok ? "✓ " : "✗ ") : ""}
                    {t.nome}
                  </span>
                  <span className="block text-[11px] text-aco">
                    {ORIGEM[t.origem]} · {passos.length} passo(s){t.agente && !t.comandos ? ` · agente ${t.agente}` : ""} · {t.sucessos}/{t.execucoes} certas
                  </span>
                </button>
                <button
                  type="button"
                  disabled={t.executando}
                  onClick={() => executar(t)}
                  className="shrink-0 px-2 py-0.5 rounded border border-[var(--luz)] text-[12px] text-gelo disabled:opacity-50"
                >
                  {t.executando ? "fazendo…" : "fazer"}
                </button>
                <button type="button" onClick={() => esquecer(t)} className="shrink-0 text-[12px] text-aco hover:text-coral" aria-label={`Esquecer a tarefa ${t.nome}`}>
                  esquecer
                </button>
              </div>
              {aberta === t.id && (
                <div className="mt-1 pl-2 text-[12px] text-aco space-y-1">
                  {t.objetivo && <p>Objetivo: {t.objetivo}</p>}
                  <ol className="list-decimal pl-4">
                    {passos.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ol>
                  {t.ultima && !t.ultima.ok && t.ultima.falha && <p className="text-coral">Última falha: {t.ultima.falha}</p>}
                  {t.frases && t.frases.length > 0 && <p>Para pedir: {t.frases.map((f) => `“${f}”`).join(", ")}</p>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex gap-2">
        <input
          value={explicacao}
          onChange={(e) => setExplicacao(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ensinar()}
          placeholder="Ensinar: explique a tarefa passo a passo…"
          aria-label="Explicação da nova tarefa"
          className="min-w-0 flex-1 bg-tinta border border-aco/40 rounded px-2 py-1 text-[13px] text-gelo"
        />
        <button type="button" disabled={ensinando} onClick={ensinar} className="px-3 py-1 rounded border border-aco/40 text-[13px] text-gelo disabled:opacity-50">
          {ensinando ? "Aprendendo…" : "Ensinar"}
        </button>
      </div>
    </div>
  );
}

function TarefasCelular({ dados }: { dados: Dados }) {
  return <Tarefas dados={dados} largura={340} />;
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 6h9M4 12h7M4 18h9" />
    <path d="m15 11 2 2 4-4" />
    <circle cx="18" cy="17.5" r="2.5" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { tarefas_aprendidas: { componente: Tarefas, celular: TarefasCelular, glifo } },
  doca: [{ tipo: "tarefas_aprendidas", rotulo: "Tarefas aprendidas" }],
};

export default extensao;
