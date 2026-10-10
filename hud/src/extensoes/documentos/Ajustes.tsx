// Ajustes → Memória dos documentos: pastas lidas, reindexação e andamento do índice.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Icone } from "../../holograms/Glifos";
import { numero, type EstadoMemoria } from "./tipos";

const VIGIAR_MS = 2000;

const nomeDaPasta = (caminho: string) => caminho.split(/[\\/]/).filter(Boolean).pop() ?? caminho;

export default function AjustesDocumentos() {
  const avisar = useHud((s) => s.acoes.avisar);
  const [estado, setEstado] = useState<EstadoMemoria | null>(null);
  const [pasta, setPasta] = useState("");
  // a leitura começa em segundo plano logo depois de um pedido: confere mais algumas vezes mesmo antes de ela aparecer
  const [conferir, setConferir] = useState(0);

  const carregar = useCallback(
    () =>
      api<EstadoMemoria>("/api/documentos/estado")
        .then(setEstado)
        .catch((e) => avisar(e.message, "erro")),
    [avisar],
  );
  useEffect(() => {
    carregar();
  }, [carregar]);
  useEffect(() => {
    if (!estado?.indexando && conferir === 0) return;
    const espera = window.setTimeout(() => {
      setConferir((n) => Math.max(0, n - 1));
      carregar();
    }, VIGIAR_MS);
    return () => window.clearTimeout(espera);
  }, [estado, conferir, carregar]);

  const mudarPasta = (acao: "adicionar" | "remover", caminho: string) =>
    api<{ texto: string; estado: EstadoMemoria }>("/api/documentos/pastas", { method: "POST", json: { acao, pasta: caminho } })
      .then((r) => {
        setEstado(r.estado);
        setConferir(3);
        avisar(r.texto, "sucesso");
        if (acao === "adicionar") setPasta("");
      })
      .catch((e) => avisar(e.message, "erro"));
  const reindexar = () =>
    api<EstadoMemoria>("/api/documentos/indexar", { method: "POST" })
      .then((r) => {
        setEstado(r);
        setConferir(3);
      })
      .catch((e) => avisar(e.message, "erro"));

  return (
    <div className="space-y-3">
      <p className="text-xs text-aco leading-snug">
        Pergunte sobre seus PDFs, documentos do Word e textos: “o que diz meu contrato sobre multa?”. Os arquivos são lidos e indexados neste PC; a cada
        pergunta, só os trechos escolhidos vão para o modelo de IA.
      </p>
      {estado?.erro_banco && <p className="text-sm text-coral">Não funciona neste Python: {estado.erro_banco}.</p>}

      <ul className="space-y-1">
        {estado?.pastas.length === 0 && <li className="text-sm text-aco">Nenhuma pasta escolhida.</li>}
        {estado?.pastas.map((p) => (
          <li key={p.caminho} className="flex items-start gap-2 py-1">
            <span className="min-w-0 flex-1" title={p.caminho}>
              <span className="block truncate text-[14px] text-gelo">{nomeDaPasta(p.caminho)}</span>
              <span className="block truncate text-xs text-aco">{p.caminho}</span>
              {p.erro && <span className="block text-xs text-coral leading-snug">{p.erro}</span>}
            </span>
            {p.origem === "env" ? (
              <span className="shrink-0 text-[11px] text-aco" title="Definida em DOCUMENTOS_PASTAS no arquivo .env">
                .env
              </span>
            ) : (
              <button
                type="button"
                aria-label={`Tirar ${p.caminho} da memória`}
                onClick={() => mudarPasta("remover", p.caminho)}
                className="shrink-0 p-0.5 text-aco hover:text-coral"
              >
                <Icone.Lixeira tamanho={16} />
              </button>
            )}
          </li>
        ))}
      </ul>

      <form
        className="flex items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (pasta.trim()) mudarPasta("adicionar", pasta.trim());
        }}
      >
        <label className="flex-1">
          <span className="text-xs text-aco">Pasta (caminho completo ou “Documentos/Contratos”)</span>
          <input
            value={pasta}
            onChange={(e) => setPasta(e.target.value)}
            placeholder="C:\Users\voce\Documents\Contratos"
            className="mt-0.5 block w-full bg-transparent border-b border-aco/50 py-1 text-gelo outline-none placeholder:text-aco/60 focus:border-[var(--luz)]"
          />
        </label>
        <button type="submit" className="text-sm text-[var(--luz)] hover:text-gelo pb-1">
          Adicionar
        </button>
      </form>

      {estado && (
        <div className="flex items-start justify-between gap-4 pt-1">
          <p className="text-sm text-gelo leading-snug">
            {numero(estado.documentos)} documentos, {numero(estado.trechos)} trechos
            <span className="block text-xs text-aco">
              {estado.indexando
                ? `Lendo agora${estado.lendo ? `: ${estado.lendo}` : "…"}`
                : estado.ultima
                  ? `Última indexação: ${estado.ultima}`
                  : "Ainda não indexado"}
            </span>
          </p>
          <button
            type="button"
            onClick={reindexar}
            disabled={estado.indexando || estado.pastas.length === 0}
            className="shrink-0 inline-flex items-center gap-1.5 text-sm text-[var(--luz)] hover:text-gelo disabled:opacity-40"
          >
            <Icone.Repetir tamanho={15} className={estado.indexando ? "girando" : undefined} /> Reindexar agora
          </button>
        </div>
      )}

      {estado && estado.total_erros > 0 && (
        <details className="text-xs text-aco">
          <summary className="cursor-pointer hover:text-gelo">
            {numero(estado.total_erros)} {estado.total_erros === 1 ? "arquivo não pôde ser lido" : "arquivos não puderam ser lidos"}
          </summary>
          <ul className="mt-1 max-h-40 overflow-y-auto rolagem space-y-0.5">
            {estado.erros.map((e) => (
              <li key={e.caminho} title={e.caminho} className="flex gap-2">
                <span className="truncate text-gelo/80">{e.arquivo}</span>
                <span className="shrink-0">{e.erro}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
