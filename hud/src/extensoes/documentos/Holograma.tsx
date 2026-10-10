// Holograma "Memória dos documentos": a resposta, as fontes (arquivo, página e o trecho com as palavras
// da pergunta em destaque) e um campo para perguntar de novo. No PC, cada fonte abre o arquivo.
import { useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Icone } from "../../holograms/Glifos";
import { numero, type DadosDocumentos, type Fonte, type ResumoMemoria } from "./tipos";

export default function HologramaDocumentos({ dados, largura = 460 }: { dados: DadosDocumentos; largura?: number }) {
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const fontes = dados?.fontes ?? [];
  return (
    <div style={{ width: largura }} className="max-w-full">
      {dados?.pergunta ? (
        <>
          <p className="text-xs text-aco leading-snug">“{dados.pergunta}”</p>
          {dados.carregando ? (
            <p className="mt-2 text-[14px] text-[var(--luz)] pulsando">Lendo os trechos dos seus documentos…</p>
          ) : (
            <p className="mt-2 max-h-[200px] overflow-y-auto rolagem text-[15px] leading-relaxed text-gelo whitespace-pre-wrap">{dados.resposta}</p>
          )}
          {fontes.length > 0 && (
            <>
              <h3 className="mt-3 mb-1 text-[11px] uppercase tracking-[0.18em] text-aco">Fontes</h3>
              <ol className="max-h-[260px] overflow-y-auto rolagem pr-1 -mr-1 space-y-1.5">
                {fontes.map((f, i) => (
                  <CartaoFonte key={`${f.id}-${f.pagina}-${i}`} fonte={f} indice={i + 1} podeAbrir={noPc} />
                ))}
              </ol>
            </>
          )}
        </>
      ) : (
        <Resumo estado={dados?.estado} />
      )}
      <Perguntar />
    </div>
  );
}

function CartaoFonte({ fonte, indice, podeAbrir }: { fonte: Fonte; indice: number; podeAbrir: boolean }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const abrir = () =>
    api<{ texto: string }>("/api/documentos/abrir", { method: "POST", json: { id: fonte.id } })
      .then((r) => avisar(r.texto, "sucesso"))
      .catch((e) => avisar(e.message, "erro"));
  return (
    <li className="grid grid-cols-[20px_1fr] gap-2 rounded border border-aco/20 bg-[rgb(var(--luz-rgb)/0.03)] px-2.5 py-2">
      <span className="numeral text-lg leading-5 text-[var(--luz)]/70">{indice}</span>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] text-gelo" title={fonte.arquivo}>
            {fonte.arquivo}
          </span>
          {fonte.pagina != null && <span className="shrink-0 text-xs text-aco">pág. {fonte.pagina}</span>}
          {podeAbrir && (
            <button
              type="button"
              data-clicavel
              onClick={abrir}
              className="ml-auto shrink-0 inline-flex items-center gap-1 text-xs text-[var(--luz)] hover:text-gelo"
            >
              Abrir <Icone.Externo tamanho={12} />
            </button>
          )}
        </div>
        <p className="mt-1 text-[13px] leading-snug text-gelo/75">
          {fonte.trecho.map(([texto, destaque], j) =>
            destaque ? (
              <mark key={j} className="rounded-sm bg-[rgb(var(--luz-rgb)/0.18)] px-0.5 text-[var(--luz)]">
                {texto}
              </mark>
            ) : (
              <span key={j}>{texto}</span>
            ),
          )}
        </p>
      </div>
    </li>
  );
}

function Resumo({ estado }: { estado?: ResumoMemoria }) {
  if (estado?.erro_banco) return <p className="text-sm text-coral">A memória dos documentos não funciona aqui: {estado.erro_banco}.</p>;
  if (!estado?.pastas)
    return (
      <p className="text-sm text-aco leading-snug">
        Nenhuma pasta na memória ainda. Diga “usa a pasta Documentos/Contratos como memória” ou escolha em Ajustes.
      </p>
    );
  return (
    <div>
      <p className="numeral text-3xl font-[300] text-gelo">
        {numero(estado.documentos)} <span className="text-base text-aco">documentos</span>
      </p>
      <p className="text-xs text-aco">
        {numero(estado.trechos)} trechos de {estado.pastas} pasta{estado.pastas === 1 ? "" : "s"}
        {estado.indexando ? " · lendo agora…" : estado.ultima ? ` · lidos em ${estado.ultima}` : ""}
      </p>
      <p className="mt-2 text-sm text-gelo/80 leading-snug">Pergunte, por exemplo: “o que diz meu contrato sobre multa?”</p>
    </div>
  );
}

function Perguntar() {
  const avisar = useHud((s) => s.acoes.avisar);
  const [pergunta, setPergunta] = useState("");
  const [enviando, setEnviando] = useState(false);
  const enviar = async (e: React.FormEvent) => {
    e.preventDefault();
    const texto = pergunta.trim();
    if (!texto || enviando) return;
    setEnviando(true);
    try {
      await api("/api/documentos/perguntar", { method: "POST", json: { pergunta: texto } });
      setPergunta("");
    } catch (erro: any) {
      avisar(erro.message, "erro");
    } finally {
      setEnviando(false);
    }
  };
  return (
    <form onSubmit={enviar} className="mt-3 flex items-center gap-2 border-t border-aco/20 pt-2">
      <input
        value={pergunta}
        onChange={(e) => setPergunta(e.target.value)}
        placeholder="Pergunte aos seus documentos…"
        aria-label="Pergunta aos documentos"
        className="flex-1 min-w-0 bg-transparent border-b border-aco/40 py-1 text-sm text-gelo outline-none focus:border-[var(--luz)]"
      />
      <button type="submit" data-clicavel disabled={enviando} aria-label="Perguntar" className="p-1 text-[var(--luz)] hover:text-gelo disabled:opacity-40">
        <Icone.Enviar tamanho={18} />
      </button>
    </form>
  );
}
