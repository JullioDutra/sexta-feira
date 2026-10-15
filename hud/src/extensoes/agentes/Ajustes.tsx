// Ajustes → Agentes: limites, pastas de projeto do programador, programas necessários e servidores MCP.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Icone } from "../../holograms/Glifos";

interface ServidorMcp {
  nome: string;
  comando: string;
  habilitado: boolean;
  comando_existe: boolean;
  rodando: boolean;
  ferramentas: number;
  erro: string;
}

interface EstadoAjustes {
  mcp: ServidorMcp[];
  erro_config: string;
  projetos: string[];
  programas: { node: boolean; npx: boolean; agent_browser: boolean; claude: boolean };
}

type Mudar = (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown>;

const LIMITES = [
  { chave: "agentes_max_passos", rotulo: "Passos por agente", min: 1, max: 200, padrao: 25 },
  { chave: "agentes_max_minutos", rotulo: "Minutos por agente", min: 1, max: 1440, padrao: 20 },
  { chave: "agentes_max_simultaneos", rotulo: "Agentes ao mesmo tempo", min: 1, max: 20, padrao: 3 },
  { chave: "agentes_espera_aprovacao_min", rotulo: "Espera por aprovação (min)", min: 1, max: 1440, padrao: 10 },
];

const PROGRAMAS: { chave: keyof EstadoAjustes["programas"]; rotulo: string; dica: string }[] = [
  { chave: "node", rotulo: "Node.js", dica: "nodejs.org (versão LTS)" },
  { chave: "agent_browser", rotulo: "agent-browser", dica: "npm install -g agent-browser && agent-browser install" },
  { chave: "claude", rotulo: "Claude Code", dica: "irm https://claude.ai/install.ps1 | iex" },
];

export default function AjustesAgentes({ mudar }: { mudar: Mudar }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const prefs = useHud((s) => s.prefs) as Record<string, unknown> | null;
  const [estado, setEstado] = useState<EstadoAjustes | null>(null);
  const [pasta, setPasta] = useState("");
  const [testando, setTestando] = useState<string | null>(null);

  const carregar = useCallback(
    () =>
      api<EstadoAjustes>("/api/agentes/ajustes")
        .then(setEstado)
        .catch((e) => avisar(e.message, "erro")),
    [avisar],
  );
  useEffect(() => {
    carregar();
  }, [carregar]);

  const pastas = Array.isArray(prefs?.projetos_pastas) ? (prefs!.projetos_pastas as string[]) : [];
  const salvarPastas = (lista: string[], mensagem: string) => mudar({ projetos_pastas: lista }, mensagem).then(() => carregar());

  const testar = (nome: string) => {
    setTestando(nome);
    api<{ ok: boolean; texto: string }>("/api/agentes/mcp/testar", { method: "POST", json: { nome } })
      .then((r) => avisar(r.texto, r.ok ? "sucesso" : "erro"))
      .catch((e) => avisar(e.message, "erro"))
      .finally(() => {
        setTestando(null);
        carregar();
      });
  };
  const recarregar = () =>
    api<EstadoAjustes>("/api/agentes/mcp/recarregar", { method: "POST" })
      .then((r) => {
        setEstado(r);
        avisar("config/mcp.yaml relido.", "sucesso");
      })
      .catch((e) => avisar(e.message, "erro"));

  return (
    <div className="space-y-4">
      <p className="text-xs text-aco leading-snug">
        Agentes trabalham sozinhos em segundo plano e avisam quando terminam: “coloca um agente para pesquisar…”, “agente navegador, abre…”,
        “status dos agentes”, “aprova o agente”. Ações sensíveis sempre esperam a sua aprovação.
      </p>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {LIMITES.map((l) => (
          <label key={l.chave} className="flex items-center justify-between gap-2">
            <span className="text-[13px] text-gelo">{l.rotulo}</span>
            <input
              type="number"
              min={l.min}
              max={l.max}
              defaultValue={Number(prefs?.[l.chave] ?? l.padrao)}
              key={String(prefs?.[l.chave] ?? l.padrao)}
              onBlur={(e) => {
                const valor = Math.max(l.min, Math.min(l.max, Math.round(Number(e.target.value) || l.padrao)));
                if (valor !== Number(prefs?.[l.chave] ?? l.padrao)) mudar({ [l.chave]: valor }, "Limite salvo.");
              }}
              className="w-16 bg-transparent border-b border-aco/50 py-0.5 text-right text-gelo outline-none focus:border-[var(--luz)]"
            />
          </label>
        ))}
      </div>

      <div>
        <h4 className="text-[11px] uppercase tracking-[0.18em] text-aco">Pastas de projeto (agente programador)</h4>
        <ul className="mt-1 space-y-1">
          {pastas.length === 0 && <li className="text-sm text-aco">Nenhuma pasta. O programador só trabalha dentro delas.</li>}
          {pastas.map((p) => (
            <li key={p} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-[13px] text-gelo" title={p}>
                {p}
              </span>
              <button
                type="button"
                aria-label={`Remover ${p}`}
                onClick={() => salvarPastas(pastas.filter((x) => x !== p), "Pasta removida.")}
                className="shrink-0 p-0.5 text-aco hover:text-coral"
              >
                <Icone.Lixeira tamanho={15} />
              </button>
            </li>
          ))}
        </ul>
        <form
          className="mt-1 flex items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            const nova = pasta.trim();
            if (nova && !pastas.includes(nova)) salvarPastas([...pastas, nova], "Pasta adicionada.").then(() => setPasta(""));
          }}
        >
          <input
            value={pasta}
            onChange={(e) => setPasta(e.target.value)}
            placeholder="C:\Users\voce\Projetos"
            aria-label="Nova pasta de projetos"
            className="flex-1 bg-transparent border-b border-aco/50 py-1 text-sm text-gelo outline-none placeholder:text-aco/60 focus:border-[var(--luz)]"
          />
          <button type="submit" className="text-sm text-[var(--luz)] hover:text-gelo pb-1">
            Adicionar
          </button>
        </form>
      </div>

      {estado && (
        <div>
          <h4 className="text-[11px] uppercase tracking-[0.18em] text-aco">Programas</h4>
          <ul className="mt-1 space-y-0.5">
            {PROGRAMAS.map((p) => (
              <li key={p.chave} className="flex items-baseline gap-2 text-[13px]">
                <span className={estado.programas[p.chave] ? "text-menta" : "text-coral"}>{estado.programas[p.chave] ? "✓" : "✗"}</span>
                <span className="text-gelo">{p.rotulo}</span>
                {!estado.programas[p.chave] && <span className="truncate text-xs text-aco">{p.dica}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {estado && (
        <div>
          <div className="flex items-center justify-between">
            <h4 className="text-[11px] uppercase tracking-[0.18em] text-aco">Servidores MCP (config/mcp.yaml)</h4>
            <button type="button" onClick={recarregar} className="inline-flex items-center gap-1 text-xs text-[var(--luz)] hover:text-gelo">
              <Icone.Repetir tamanho={13} /> Reler
            </button>
          </div>
          {estado.erro_config && <p className="text-sm text-coral">{estado.erro_config}</p>}
          <ul className="mt-1 space-y-1.5">
            {estado.mcp.map((s) => {
              const ok = s.habilitado && !s.erro;
              return (
                <li key={s.nome} className="flex items-start gap-2">
                  <span className={`pt-0.5 ${ok ? "text-menta" : "text-coral"}`}>{ok ? "✓" : "✗"}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] text-gelo">
                      {s.nome}
                      <span className="ml-2 text-xs text-aco">
                        {!s.comando_existe
                          ? "comando não encontrado"
                          : !s.habilitado
                            ? "desligado"
                            : s.rodando
                              ? `rodando · ${s.ferramentas} ferramentas`
                              : "inicia quando um agente precisar"}
                      </span>
                    </span>
                    <span className="block truncate text-xs text-aco" title={s.comando}>
                      {s.comando}
                    </span>
                    {s.erro && <span className="block text-xs text-coral leading-snug">{s.erro}</span>}
                  </span>
                  <button
                    type="button"
                    disabled={!s.habilitado || testando !== null}
                    onClick={() => testar(s.nome)}
                    className="shrink-0 text-xs text-[var(--luz)] hover:text-gelo disabled:opacity-40"
                  >
                    {testando === s.nome ? "Testando…" : "Testar"}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
