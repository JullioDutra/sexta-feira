// Extensão "aprendizado": holograma Memória (fatos, lições e conhecimentos que ela aprendeu)
// e a seção "Inteligência" em Ajustes (autonomia, pensamento nos pedidos complexos, memória).
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useHud } from "../lib/store";
import type { Preferencias } from "../lib/tipos";
import type { Extensao } from "./tipos";

interface Item {
  id: number;
  tipo: "fato" | "licao" | "conhecimento";
  texto: string;
  etiquetas: string[];
  origem: string;
  confianca: number;
  usos: number;
}

interface Estatisticas {
  fatos: number;
  licoes: number;
  conhecimentos: number;
  episodios: number;
  acertos: number;
  consolidado_em: string | null;
}

interface DadosMemoria {
  estatisticas: Estatisticas;
  fatos: Item[];
  licoes: Item[];
  conhecimentos: Item[];
}

type Aba = "fatos" | "licoes" | "conhecimentos";

const ABAS: [Aba, string][] = [
  ["fatos", "Sobre você"],
  ["licoes", "Lições"],
  ["conhecimentos", "Conhecimento"],
];

const ORIGENS: Record<string, string> = {
  usuario: "você",
  correcao: "correção",
  consolidacao: "revisão do dia",
  engenharia_reversa: "eng. reversa",
};

function taxa(e: Estatisticas) {
  return e.episodios ? `${Math.round((100 * e.acertos) / e.episodios)}% de acertos em ${e.episodios} pedidos` : "nenhum pedido ainda";
}

function Memoria({ dados, largura = 460 }: { dados: DadosMemoria; largura?: number }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [atual, setAtual] = useState<DadosMemoria>(dados);
  const [aba, setAba] = useState<Aba>("fatos");
  useEffect(() => setAtual(dados), [dados]);
  if (!atual?.estatisticas) return <p className="text-sm text-aco">Carregando…</p>;
  const itens = atual[aba] ?? [];
  const remover = (item: Item) =>
    api<DadosMemoria>(`/api/memoria/${item.id}`, { method: "DELETE" })
      .then((r) => {
        setAtual(r);
        avisar("Esquecido.", "sucesso");
      })
      .catch((e) => avisar(e.message, "erro"));

  return (
    <div style={{ width: largura }} className="space-y-2">
      <p className="text-xs text-aco">{taxa(atual.estatisticas)}</p>
      <div role="tablist" className="flex gap-1">
        {ABAS.map(([chave, rotulo]) => (
          <button
            key={chave}
            role="tab"
            aria-selected={aba === chave}
            onClick={() => setAba(chave)}
            className={`px-2 py-1 rounded text-[13px] border ${aba === chave ? "border-[var(--luz)] text-gelo" : "border-aco/30 text-aco"}`}
          >
            {rotulo} <span className="opacity-60">{atual[chave]?.length ?? 0}</span>
          </button>
        ))}
      </div>
      <ul className="max-h-[360px] overflow-y-auto rolagem pr-1 space-y-1">
        {itens.length === 0 && <li className="text-sm text-aco py-2">Nada aqui ainda.</li>}
        {itens.map((item) => (
          <li key={item.id} className="flex items-start gap-2 py-1 border-b border-aco/10">
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] text-gelo leading-snug">{item.texto}</span>
              <span className="block text-[11px] text-aco">
                {ORIGENS[item.origem] ?? item.origem ?? ""}
                {item.etiquetas.length ? ` · ${item.etiquetas.join(", ")}` : ""}
                {item.usos ? ` · usado ${item.usos}×` : ""}
              </span>
            </span>
            <button type="button" onClick={() => remover(item)} className="shrink-0 text-[12px] text-aco hover:text-coral" aria-label={`Esquecer: ${item.texto}`}>
              esquecer
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MemoriaCelular({ dados }: { dados: DadosMemoria }) {
  return <Memoria dados={dados} largura={340} />;
}

const AUTONOMIA: { valor: string; rotulo: string; descricao: string }[] = [
  { valor: "normal", rotulo: "Normal", descricao: "Fechar, mover e comandos fora da lista pedem confirmação; o resto ela faz na hora." },
  {
    valor: "total",
    rotulo: "Acesso completo",
    descricao: "Ela age sozinha (fechar, mover, comandos do terminal). Só o irreversível — apagar, desligar, comandos destrutivos — ainda pede confirmação com rosto.",
  },
];

type PrefsIA = Preferencias & { autonomia?: string; pensar_complexo?: boolean };

function AjustesInteligencia({ mudar }: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) {
  const prefs = useHud((s) => s.prefs as PrefsIA | null);
  const avisar = useHud((s) => s.acoes.avisar);
  const [estat, setEstat] = useState<Estatisticas | null>(null);
  const [revisando, setRevisando] = useState(false);
  const carregar = useCallback(
    () =>
      api<DadosMemoria>("/api/memoria")
        .then((r) => setEstat(r.estatisticas))
        .catch(() => undefined),
    [],
  );
  useEffect(() => {
    carregar();
  }, [carregar]);
  const autonomia = AUTONOMIA.find((a) => a.valor === (prefs?.autonomia ?? "normal")) ?? AUTONOMIA[1];
  const pensar = prefs?.pensar_complexo ?? true;
  const consolidar = () => {
    if (revisando) return;
    setRevisando(true);
    api<{ novos: { fato?: number; licao?: number }; estatisticas: Estatisticas }>("/api/memoria/consolidar", { method: "POST" })
      .then((r) => {
        setEstat(r.estatisticas);
        avisar(`Memória revisada: ${r.novos?.fato ?? 0} fatos e ${r.novos?.licao ?? 0} lições novas.`, "sucesso");
      })
      .catch((e) => avisar(e.message, "erro"))
      .finally(() => setRevisando(false));
  };

  return (
    <div className="space-y-3">
      <label className="flex items-center justify-between py-2">
        <span className="text-[15px] text-gelo">Autonomia</span>
        <select
          value={autonomia.valor}
          onChange={(e) => mudar({ autonomia: e.target.value }, "Autonomia salva.")}
          className="bg-tinta border border-aco/40 rounded px-2 py-1 text-gelo"
        >
          {AUTONOMIA.map((a) => (
            <option key={a.valor} value={a.valor}>
              {a.rotulo}
            </option>
          ))}
        </select>
      </label>
      <p className="text-xs text-aco leading-snug">{autonomia.descricao}</p>

      <div className="flex items-start justify-between gap-4 py-2">
        <span>
          <span className="block text-[15px] text-gelo">Pensar nos pedidos complexos</span>
          <span className="block text-xs text-aco leading-snug mt-0.5">
            Análises, planos e explicações usam o cérebro principal pensando antes de responder (ela diz "deixa eu ver" na hora). Pedidos simples continuam
            instantâneos.
          </span>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={pensar}
          aria-label="Pensar nos pedidos complexos"
          onClick={() => mudar({ pensar_complexo: !pensar })}
          className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors ${pensar ? "border-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.25)]" : "border-aco/50"}`}
        >
          <span className={`absolute top-0.5 size-4 rounded-full transition-all ${pensar ? "left-[22px] bg-[var(--luz)]" : "left-0.5 bg-aco"}`} />
        </button>
      </div>

      <div className="border-t border-aco/20 pt-3">
        <p className="text-[15px] text-gelo">Memória</p>
        {estat ? (
          <p className="text-xs text-aco leading-snug mt-1">
            {estat.fatos} fatos sobre você, {estat.licoes} lições, {estat.conhecimentos} conhecimentos; {taxa(estat)}.
            {estat.consolidado_em ? ` Última revisão: ${estat.consolidado_em.replace("T", " às ")}.` : " Ainda não revisada."}
          </p>
        ) : (
          <p className="text-xs text-aco">Carregando…</p>
        )}
        <p className="text-xs text-aco leading-snug mt-1">
          Ela revisa o dia sozinha às 3h e aprende com os erros e as suas correções. Por voz: "o que você aprendeu hoje?", "o que você sabe sobre mim?",
          "deu certo?", "aprende que quando eu falar X é Y".
        </p>
        <div className="flex gap-2 mt-2">
          <button
            type="button"
            onClick={() => api("/api/hologramas", { method: "POST", json: { tipo: "memoria" } }).catch((e) => avisar(e.message, "erro"))}
            className="px-3 py-1 rounded border border-aco/40 text-[13px] text-gelo">
            Ver memória
          </button>
          <button type="button" disabled={revisando} onClick={consolidar} className="px-3 py-1 rounded border border-aco/40 text-[13px] text-gelo disabled:opacity-50">
            {revisando ? "Revisando…" : "Revisar agora"}
          </button>
        </div>
      </div>
    </div>
  );
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9.5 4.5a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2.5 4.5 3 3 0 0 0 5 1.5V6a2.5 2.5 0 0 0-2.5-1.5z" />
    <path d="M14.5 4.5a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2.5 4.5 3 3 0 0 1-5 1.5" />
    <path d="M12 9h2.5M12 13h3" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { memoria: { componente: Memoria, celular: MemoriaCelular, glifo } },
  doca: [{ tipo: "memoria", rotulo: "Memória" }],
  ajustes: [{ titulo: "Inteligência e memória", componente: AjustesInteligencia }],
};

export default extensao;
