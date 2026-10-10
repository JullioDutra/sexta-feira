// Holograma Jornal: abas Destaques / Brasil / Tecnologia / Seus temas / Salvas.
// Toque (ou pinça rápida) numa notícia: a Sexta lê o resumo. Arrastar para o lado (ou o marcador): salva para depois.
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useHud } from "../lib/store";
import { Icone } from "./Glifos";

interface Noticia {
  id: string;
  titulo: string;
  link: string;
  fontes: string[];
  quando: string;
  resumo: string;
  tema?: string | null;
}

interface DadosJornal {
  aba: string;
  abas: Record<string, Noticia[]>;
  temas: string[];
  atualizado: string;
  leitura?: { titulo: string; texto: string; link: string; ts: number };
}

const ABAS: [string, string][] = [
  ["destaques", "Destaques"],
  ["brasil", "Brasil"],
  ["tecnologia", "Tecnologia"],
  ["temas", "Seus temas"],
  ["salvas", "Salvas"],
];

export default function Jornal({ dados, largura = 480 }: { dados: DadosJornal; largura?: number }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [aba, setAba] = useState(dados?.aba ?? "destaques");
  const [leitura, setLeitura] = useState<{ titulo: string; texto: string; link: string } | null>(null);
  const [carregando, setCarregando] = useState<string | null>(null);
  const itens = dados?.abas?.[aba] ?? [];
  // leitura pedida por voz ("lê a segunda notícia") chega pelos dados do holograma
  useEffect(() => {
    if (dados?.leitura) setLeitura(dados.leitura);
  }, [dados?.leitura?.ts]); // eslint-disable-line react-hooks/exhaustive-deps

  const ler = async (n: Noticia) => {
    setCarregando(n.id);
    try {
      const r = await api<{ texto: string; link: string }>("/api/jornal/ler", { method: "POST", json: { id: n.id } });
      setLeitura({ titulo: n.titulo, texto: r.texto, link: r.link });
    } catch (e: any) {
      avisar(e.message, "erro");
    } finally {
      setCarregando(null);
    }
  };
  const salvar = (n: Noticia) =>
    api<{ texto: string }>("/api/jornal/salvar", { method: "POST", json: { id: n.id } })
      .then((r) => avisar(r.texto, "sucesso"))
      .catch((e) => avisar(e.message, "erro"));
  const remover = (n: Noticia) => api(`/api/jornal/salvas/${encodeURIComponent(n.id)}`, { method: "DELETE" }).catch((e) => avisar(e.message, "erro"));
  const atualizar = () => api("/api/jornal/atualizar", { method: "POST", json: { aba } }).catch((e) => avisar(e.message, "erro"));

  if (leitura)
    return (
      <article style={{ width: largura }}>
        <button type="button" data-clicavel onClick={() => setLeitura(null)} className="text-xs text-aco hover:text-gelo mb-2">
          ← voltar às notícias
        </button>
        <h3 className="text-[16px] leading-snug text-gelo">{leitura.titulo}</h3>
        <p className="mt-2 max-h-[300px] overflow-y-auto rolagem text-[14px] leading-relaxed text-gelo/90 whitespace-pre-wrap">{leitura.texto}</p>
        {leitura.link && (
          <a href={leitura.link} target="_blank" rel="noreferrer" data-clicavel className="mt-3 inline-flex items-center gap-1.5 text-xs text-[var(--luz)]">
            Abrir a matéria <Icone.Externo tamanho={12} />
          </a>
        )}
      </article>
    );

  return (
    <div style={{ width: largura }}>
      <div role="tablist" aria-label="Abas do jornal" className="flex gap-1 mb-2 overflow-x-auto">
        {ABAS.map(([chave, rotulo]) => (
          <button
            key={chave}
            type="button"
            role="tab"
            data-clicavel
            aria-selected={aba === chave}
            onClick={() => setAba(chave)}
            className={`shrink-0 px-2.5 py-1 rounded-full text-xs border ${aba === chave ? "border-[var(--luz)] text-[var(--luz)]" : "border-transparent text-aco hover:text-gelo"}`}
          >
            {rotulo}
            {chave !== "destaques" && dados?.abas?.[chave]?.length ? <span className="ml-1 opacity-60">{dados.abas[chave].length}</span> : null}
          </button>
        ))}
      </div>
      {aba === "temas" && (
        <p className="text-xs text-aco mb-1">
          {dados.temas.length ? `Acompanhando: ${dados.temas.join(", ")}.` : 'Diga "me avisa quando sair notícia de…" para acompanhar um assunto.'}
        </p>
      )}
      {!itens.length ? (
        <p className="text-sm text-aco py-6">{aba === "salvas" ? "Nada salvo. Arraste uma notícia para o lado para guardar." : "Nenhuma notícia agora."}</p>
      ) : (
        <ol className="max-h-[400px] overflow-y-auto rolagem pr-1 -mr-1">
          {itens.map((n, i) => (
            <ItemNoticia
              key={n.id}
              n={n}
              i={i}
              ocupado={carregando === n.id}
              salva={aba === "salvas"}
              aoLer={() => ler(n)}
              aoSalvar={() => (aba === "salvas" ? remover(n) : salvar(n))}
            />
          ))}
        </ol>
      )}
      <div className="mt-2 flex items-center justify-between text-[11px] text-aco/70">
        <span>Toque para ouvir · arraste para o lado para salvar</span>
        <button type="button" data-clicavel onClick={atualizar} className="hover:text-gelo">
          Atualizado {dados?.atualizado} · atualizar
        </button>
      </div>
    </div>
  );
}

function ItemNoticia({
  n,
  i,
  ocupado,
  salva,
  aoLer,
  aoSalvar,
}: {
  n: Noticia;
  i: number;
  ocupado: boolean;
  salva: boolean;
  aoLer: () => void;
  aoSalvar: () => void;
}) {
  const inicio = useRef<number | null>(null);
  const [deslocamento, setDeslocamento] = useState(0);
  const arrastou = useRef(false);

  // arrastar para o lado (mouse ou toque) salva a notícia — ou tira das salvas
  const soltar = () => {
    if (Math.abs(deslocamento) > 110) aoSalvar();
    inicio.current = null;
    setDeslocamento(0);
  };

  return (
    <li className={`relative ${i ? "border-t border-aco/15" : ""}`}>
      <span
        aria-hidden
        className={`absolute inset-y-0 left-0 flex items-center text-xs text-[var(--luz)] transition-opacity ${Math.abs(deslocamento) > 40 ? "opacity-100" : "opacity-0"}`}
      >
        {salva ? "remover" : "salvar"}
      </span>
      <div
        role="button"
        tabIndex={0}
        data-clicavel
        aria-label={`Ouvir: ${n.titulo}`}
        onPointerDown={(e) => {
          inicio.current = e.clientX;
          arrastou.current = false;
        }}
        onPointerMove={(e) => {
          if (inicio.current === null) return;
          const dx = e.clientX - inicio.current;
          if (Math.abs(dx) > 8) arrastou.current = true;
          setDeslocamento(dx);
        }}
        onPointerUp={soltar}
        onPointerLeave={() => inicio.current !== null && soltar()}
        onClick={() => !arrastou.current && aoLer()}
        onKeyDown={(e) => e.key === "Enter" && aoLer()}
        style={{ transform: `translateX(${deslocamento}px)` }}
        className={`group grid grid-cols-[22px_1fr_22px] gap-2 py-2.5 items-start outline-none cursor-pointer bg-[var(--fundo-holo,transparent)] ${deslocamento ? "" : "transition-transform"} focus-visible:bg-[rgb(var(--luz-rgb)/0.08)]`}
      >
        <span className="numeral text-lg leading-6 text-[var(--luz)]/70">{ocupado ? "…" : i + 1}</span>
        <span className="min-w-0">
          <span className="block text-[15px] leading-snug text-gelo group-hover:text-white">{n.titulo}</span>
          <span className="mt-1 block text-xs text-aco truncate">
            {n.fontes.filter(Boolean).join(" · ")}
            {n.fontes.length > 1 && <span className="ml-1 text-[var(--luz)]/80">({n.fontes.length} fontes)</span>}
            {n.quando ? `, ${n.quando}` : ""}
            {n.tema ? ` · ${n.tema}` : ""}
          </span>
        </span>
        <button
          type="button"
          data-clicavel
          aria-label={salva ? `Remover das salvas: ${n.titulo}` : `Salvar para depois: ${n.titulo}`}
          onClick={(e) => {
            e.stopPropagation();
            aoSalvar();
          }}
          className="mt-0.5 text-aco hover:text-[var(--luz)]"
        >
          {salva ? <Icone.Lixeira tamanho={15} /> : <Marcador />}
        </button>
      </div>
    </li>
  );
}

function Marcador() {
  return (
    <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden>
      <path d="M6.5 3.5h11v17l-5.5-4-5.5 4Z" />
    </svg>
  );
}
