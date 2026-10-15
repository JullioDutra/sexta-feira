// Celular: os agentes trabalhando agora, com aprovar/negar/cancelar (só aparece quando há algum ativo).
import { useEffect } from "react";
import { useHud } from "../../lib/store";
import { ATIVOS, ROTULO_STATUS, aprovarAgente, cancelarAgente, useAgentes } from "./tipos";

export default function AgentesCelular() {
  const avisar = useHud((s) => s.acoes.avisar);
  const dados = useAgentes((s) => s.dados);
  const carregar = useAgentes((s) => s.carregar);
  useEffect(() => {
    carregar();
  }, [carregar]);
  const ativos = (dados?.agentes ?? []).filter((a) => ATIVOS.includes(a.status));
  if (ativos.length === 0) return null;
  const acao = (p: Promise<{ texto: string }>) => p.then((r) => avisar(r.texto, "info")).catch((e) => avisar(e.message, "erro"));
  return (
    <section className="mt-4">
      <h3 className="text-[11px] uppercase tracking-[0.18em] text-aco">Agentes</h3>
      <ul className="mt-1 space-y-2">
        {ativos.map((a) => {
          const ultimo = [...a.passos].reverse().find((p) => ["ferramenta", "pensamento", "claude"].includes(p.tipo));
          return (
            <li key={a.id} className="rounded border border-aco/30 px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-sm text-[var(--luz)]">{a.rotulo}</span>
                <span className="ml-auto text-xs text-aco">{ROTULO_STATUS[a.status]}</span>
              </div>
              <p className="text-sm text-gelo leading-snug">{a.objetivo}</p>
              {a.status === "aguardando" && a.pendente ? (
                <>
                  <p className="mt-1 text-sm text-gelo/90">Quer {a.pendente.descricao}</p>
                  <div className="mt-2 flex gap-3">
                    <button type="button" onClick={() => acao(aprovarAgente(a.id, true))} className="flex-1 rounded border border-menta/60 py-2 text-menta">
                      Aprovar
                    </button>
                    <button type="button" onClick={() => acao(aprovarAgente(a.id, false))} className="flex-1 rounded border border-coral/60 py-2 text-coral">
                      Negar
                    </button>
                  </div>
                </>
              ) : (
                ultimo && <p className="mt-1 truncate text-xs text-aco">{ultimo.texto}</p>
              )}
              <button type="button" onClick={() => acao(cancelarAgente(a.id))} className="mt-2 text-xs text-coral">
                Cancelar agente
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
