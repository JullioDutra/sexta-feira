// Holograma "traducao": a conversa do modo tradutor (a fala mais nova embaixo) ou a tradução da tela / do texto copiado.
import { useEffect, useLayoutEffect, useRef } from "react";
import { conexao } from "../../lib/socket";
import { useHud } from "../../lib/store";

interface Linha {
  id: number;
  de: string;
  para: string;
  original: string;
  traducao: string;
}

interface DadosTraducao {
  modo: "voz" | "tela" | "copiado";
  ativo: boolean;
  idioma: string;
  codigo: string;
  linhas: Linha[];
}

const ROTULO_MODO = { tela: "Tela", copiado: "Texto copiado" };

/** Esc e o botão "Parar" desligam o modo tradutor (o servidor ignora se ele já estiver desligado). */
export function pararTradutor() {
  conexao.enviar({ tipo: "traducao.parar" });
}

export function GlifoTraducao({ tamanho }: { tamanho: number }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 5.5h10M8 3.5v2M5.5 5.5c.8 3.2 3 5.8 6 7.2M10.5 5.5c-.9 3.6-3.3 6.4-6.8 8" />
      <path d="M12.5 20.5 16.5 10l4 10.5M14 16.8h5" />
    </svg>
  );
}

/** Em qualquer lugar do HUD do PC, Esc também encerra o modo tradutor (o Esc do núcleo só para a fala). */
export function PararTradutorComEsc() {
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || (e.target as HTMLElement)?.closest?.("input, textarea, select")) return;
      pararTradutor();
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, []);
  return null;
}

function Cabecalho({ dados }: { dados: DadosTraducao }) {
  // sem idioma pedido, o texto copiado vai para o português (ou para o inglês, se já estava em português)
  if (dados.modo !== "voz")
    return (
      <p className="numeral text-xs tracking-wide text-aco uppercase">
        {ROTULO_MODO[dados.modo]}
        {dados.idioma && ` → ${dados.idioma}`}
      </p>
    );
  return (
    <p className="flex items-center gap-2 numeral text-xs tracking-wide uppercase">
      <span className={`size-2 rounded-full ${dados.ativo ? "bg-[var(--luz)] pulsando" : "bg-aco"}`} aria-hidden="true" />
      <span className={dados.ativo ? "text-[var(--luz)]" : "text-aco"}>{dados.ativo ? "Ao vivo" : "Encerrado"}</span>
      <span className="text-aco">· português ⇄ {dados.idioma}</span>
    </p>
  );
}

function ItemTraducao({ linha, conversa }: { linha: Linha; conversa: boolean }) {
  return (
    <li className="py-2.5 border-t border-aco/15 first:border-t-0">
      {conversa && (
        <span className="numeral block text-[11px] tracking-wide text-[var(--luz)] uppercase">
          {linha.de} → {linha.para}
        </span>
      )}
      {linha.original && <span className="block text-[13px] leading-snug text-aco whitespace-pre-wrap">{linha.original}</span>}
      <span className="block mt-1 text-[16px] leading-snug text-gelo whitespace-pre-wrap">{linha.traducao}</span>
    </li>
  );
}

export function Traducao({ dados }: { dados: DadosTraducao }) {
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const lista = useRef<HTMLOListElement>(null);
  const linhas = dados?.linhas ?? [];
  const conversa = dados?.modo === "voz";
  const ultima = linhas[linhas.length - 1]?.id;

  useLayoutEffect(() => {
    const el = lista.current;
    if (el && conversa) el.scrollTop = el.scrollHeight; // a fala mais nova fica sempre à vista
  }, [ultima, conversa]);

  if (!dados) return null;
  return (
    <div className="w-[440px] max-w-full">
      <Cabecalho dados={dados} />
      {linhas.length ? (
        <ol ref={lista} className="mt-2 max-h-[360px] overflow-y-auto rolagem pr-1 -mr-1" aria-live="polite">
          {linhas.map((l) => (
            <ItemTraducao key={l.id} linha={l} conversa={conversa} />
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-sm text-aco leading-relaxed">
          {dados.ativo
            ? `Pode falar: o que for dito em português eu repito em ${dados.idioma}, e o que for dito em ${dados.idioma} eu repito em português.`
            : "Nenhuma fala traduzida."}
        </p>
      )}
      {dados.ativo && (
        <div className="mt-3 flex items-center justify-between gap-3">
          <span className="text-[11px] text-aco/80">"Sexta-Feira, para de traduzir"{noPc && " ou Esc"}</span>
          <button
            type="button"
            data-clicavel
            onClick={pararTradutor}
            className="shrink-0 px-3 py-1 rounded-full border border-[var(--luz)]/60 text-xs text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]"
          >
            Parar tradutor
          </button>
        </div>
      )}
    </div>
  );
}
