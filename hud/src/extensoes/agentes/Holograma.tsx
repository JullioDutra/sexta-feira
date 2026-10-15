// Holograma "Agentes": ativos e recentes, passos ao vivo, status com ✓/✗, cancelar/aprovar e um campo para criar agente.
import { useEffect, useState } from "react";
import { useHud } from "../../lib/store";
import { Icone } from "../../holograms/Glifos";
import {
  ATIVOS,
  ROTULO_STATUS,
  SIMBOLO_STATUS,
  aprovarAgente,
  cancelarAgente,
  criarAgente,
  duracao,
  useAgentes,
  type Agente,
  type DadosAgentes,
  type Passo,
} from "./tipos";

export default function HologramaAgentes({ dados, largura = 480 }: { dados?: DadosAgentes; largura?: number }) {
  const doStore = useAgentes((s) => s.dados);
  const carregar = useAgentes((s) => s.carregar);
  useEffect(() => {
    if (!doStore) carregar();
  }, [doStore, carregar]);
  const atuais = doStore ?? dados;
  const agentes = atuais?.agentes ?? [];
  const ativos = agentes.filter((a) => ATIVOS.includes(a.status));
  const recentes = agentes.filter((a) => !ATIVOS.includes(a.status)).slice(0, 8);
  const [aberto, setAberto] = useState<string | null>(null);

  return (
    <div style={{ width: largura }} className="max-w-full">
      {agentes.length === 0 && (
        <p className="text-sm text-aco leading-snug">
          Nenhum agente ainda. Diga “coloca um agente para pesquisar…” ou “agente navegador, abre…”, ou crie abaixo.
        </p>
      )}
      {ativos.length > 0 && (
        <ul className="space-y-2">
          {ativos.map((a) => (
            <CartaoAgente key={a.id} agente={a} vivo />
          ))}
        </ul>
      )}
      {recentes.length > 0 && (
        <>
          <h3 className="mt-3 mb-1 text-[11px] uppercase tracking-[0.18em] text-aco">Recentes</h3>
          <ul className="max-h-[240px] overflow-y-auto rolagem pr-1 -mr-1 space-y-1">
            {recentes.map((a) =>
              aberto === a.id ? (
                <CartaoAgente key={a.id} agente={a} aoFechar={() => setAberto(null)} />
              ) : (
                <li key={a.id}>
                  <button type="button" data-clicavel onClick={() => setAberto(a.id)} className="w-full flex items-center gap-2 py-1 text-left hover:text-gelo">
                    <Status agente={a} />
                    <span className="shrink-0 text-xs text-aco">{a.rotulo}</span>
                    <span className="truncate text-[13px] text-gelo/80">{a.resumo || a.objetivo}</span>
                  </button>
                </li>
              ),
            )}
          </ul>
        </>
      )}
      <NovoAgente tipos={atuais?.tipos ?? []} />
    </div>
  );
}

function Status({ agente }: { agente: Agente }) {
  const simbolo = SIMBOLO_STATUS[agente.status];
  const cor =
    agente.status === "concluido"
      ? "text-menta"
      : agente.status === "falhou"
        ? "text-coral"
        : agente.status === "aguardando"
          ? "text-[var(--luz)] pulsando"
          : ATIVOS.includes(agente.status)
            ? "text-[var(--luz)]"
            : "text-aco";
  return (
    <span className={`shrink-0 w-5 text-center text-[15px] leading-none ${cor}`} title={ROTULO_STATUS[agente.status]}>
      {simbolo ?? (ATIVOS.includes(agente.status) ? "●" : "–")}
    </span>
  );
}

function CartaoAgente({ agente, vivo = false, aoFechar }: { agente: Agente; vivo?: boolean; aoFechar?: () => void }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [agora, setAgora] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!vivo) return;
    const t = window.setInterval(() => setAgora(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, [vivo]);
  const passos = agente.passos.slice(vivo ? -6 : -12);
  const tempo = (agente.terminado ?? agora) - agente.criado;
  const acao = (p: Promise<{ texto: string }>) => p.then((r) => avisar(r.texto, "info")).catch((e) => avisar(e.message, "erro"));

  return (
    <li className="rounded border border-aco/25 bg-[rgb(var(--luz-rgb)/0.03)] px-2.5 py-2">
      <div className="flex items-center gap-2">
        <Status agente={agente} />
        <span className="text-[13px] uppercase tracking-[0.12em] text-[var(--luz)]">
          {agente.rotulo} <span className="text-aco">#{agente.numero}</span>
        </span>
        <span className="ml-auto shrink-0 text-xs text-aco">
          {ROTULO_STATUS[agente.status]} · {vivo ? `passo ${agente.rodada}/${agente.max_passos} · ` : ""}
          {duracao(tempo)}
        </span>
        {vivo && (
          <button
            type="button"
            data-clicavel
            aria-label="Cancelar agente"
            title="Cancelar"
            onClick={() => acao(cancelarAgente(agente.id))}
            className="shrink-0 p-0.5 text-aco hover:text-coral"
          >
            <Icone.Parar tamanho={15} />
          </button>
        )}
        {aoFechar && (
          <button type="button" data-clicavel aria-label="Recolher" onClick={aoFechar} className="shrink-0 p-0.5 text-aco hover:text-gelo">
            <Icone.Fechar tamanho={14} />
          </button>
        )}
      </div>
      <p className="mt-1 text-[13px] text-gelo leading-snug">{agente.objetivo}</p>

      {agente.status === "aguardando" && agente.pendente && (
        <div className="mt-2 rounded border border-[var(--luz)]/50 px-2 py-1.5">
          <p className="text-[13px] text-gelo leading-snug">
            Quer {agente.pendente.descricao}
            {agente.pendente.nivel >= 3 && <span className="block text-xs text-aco">Ação irreversível: confirmação reforçada.</span>}
          </p>
          <div className="mt-1.5 flex gap-4">
            <button type="button" data-clicavel onClick={() => acao(aprovarAgente(agente.id, true))} className="text-sm text-menta hover:text-gelo">
              Aprovar
            </button>
            <button type="button" data-clicavel onClick={() => acao(aprovarAgente(agente.id, false))} className="text-sm text-coral hover:text-gelo">
              Negar
            </button>
          </div>
        </div>
      )}

      {passos.length > 0 && (
        <ol className="mt-1.5 space-y-0.5 max-h-[150px] overflow-y-auto rolagem">
          {passos.map((p) => (
            <LinhaPasso key={`${p.n}-${p.ts}`} passo={p} />
          ))}
        </ol>
      )}

      {!vivo && agente.relatorio && (
        <details className="mt-1.5" open={!vivo}>
          <summary className="cursor-pointer text-xs text-aco hover:text-gelo">Relatório</summary>
          <p className="mt-1 max-h-[220px] overflow-y-auto rolagem text-[13px] leading-relaxed text-gelo/90 whitespace-pre-wrap">{agente.relatorio}</p>
          {agente.evidencia && <p className="mt-1 text-xs text-aco leading-snug">Conferência: {agente.evidencia}</p>}
        </details>
      )}
    </li>
  );
}

function LinhaPasso({ passo }: { passo: Passo }) {
  const marca = passo.ok === true ? "✓" : passo.ok === false ? "✗" : passo.tipo === "ferramenta" ? "›" : "·";
  const cor = passo.ok === true ? "text-menta" : passo.ok === false ? "text-coral" : "text-aco";
  const texto = passo.tipo === "pensamento" ? <em className="not-italic text-gelo/60">{passo.texto}</em> : passo.texto;
  return (
    <li className="flex gap-1.5 text-xs leading-snug">
      <span className={`shrink-0 w-3 text-center ${cor}`}>{marca}</span>
      <span className="min-w-0 truncate text-gelo/80" title={passo.texto}>
        {texto}
      </span>
    </li>
  );
}

function NovoAgente({ tipos }: { tipos: { tipo: string; rotulo: string; descricao: string; confirmar: boolean }[] }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [tipo, setTipo] = useState("");
  const [objetivo, setObjetivo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const escolhido = tipos.find((t) => t.tipo === tipo);
  const enviar = async (e: React.FormEvent) => {
    e.preventDefault();
    const texto = objetivo.trim();
    if (!texto || enviando) return;
    setEnviando(true);
    try {
      const r = await criarAgente(tipo, texto);
      avisar(r.texto, r.ok ? "sucesso" : "info");
      if (r.ok || r.pendente) setObjetivo("");
    } catch (erro: any) {
      avisar(erro.message, "erro");
    } finally {
      setEnviando(false);
    }
  };
  return (
    <form onSubmit={enviar} className="mt-3 border-t border-aco/20 pt-2">
      <div className="flex items-center gap-2">
        <select
          value={tipo}
          onChange={(e) => setTipo(e.target.value)}
          aria-label="Tipo de agente"
          className="shrink-0 bg-tinta border border-aco/40 rounded px-1.5 py-1 text-xs text-gelo"
        >
          <option value="">Automático</option>
          {tipos.map((t) => (
            <option key={t.tipo} value={t.tipo}>
              {t.rotulo.replace(/^de /, "")}
            </option>
          ))}
        </select>
        <input
          value={objetivo}
          onChange={(e) => setObjetivo(e.target.value)}
          maxLength={2000}
          placeholder="Objetivo do novo agente…"
          aria-label="Objetivo do novo agente"
          className="flex-1 min-w-0 bg-transparent border-b border-aco/40 py-1 text-sm text-gelo outline-none placeholder:text-aco/70 focus:border-[var(--luz)]"
        />
        <button type="submit" data-clicavel disabled={enviando} aria-label="Criar agente" className="p-1 text-[var(--luz)] hover:text-gelo disabled:opacity-40">
          <Icone.Enviar tamanho={18} />
        </button>
      </div>
      {escolhido && (
        <p className="mt-1 text-xs text-aco leading-snug">
          {escolhido.descricao}
          {escolhido.confirmar ? " Pede confirmação antes de começar." : ""}
        </p>
      )}
    </form>
  );
}
