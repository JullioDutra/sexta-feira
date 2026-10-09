// Editor visual de protocolos: blocos Quando (gatilhos) → Se (condições) → Então (ações).
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useHud } from "../lib/store";
import { Icone } from "../holograms/Glifos";

type Entrada = "texto" | "numero" | "hora" | "nenhum" | "bool" | "opcoes" | "dias" | "intervalo";

interface ItemCatalogo {
  tipo: string;
  rotulo: string;
  entrada: Entrada;
  dica?: string;
  opcoes?: string[];
}

interface Catalogo {
  gatilhos: ItemCatalogo[];
  condicoes: ItemCatalogo[];
  acoes: ItemCatalogo[];
}

interface Bloco {
  tipo: string;
  valor: unknown;
  dias?: number[];
}

interface ProtocoloEditor {
  nome: string;
  ativo: boolean;
  criada_pela_ia: boolean;
  editavel: boolean;
  gatilhos: Bloco[];
  condicoes: Bloco[];
  acoes: Bloco[];
}

type Coluna = "gatilhos" | "condicoes" | "acoes";

const DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
const COLUNAS: { chave: Coluna; titulo: string; vazio: string }[] = [
  { chave: "gatilhos", titulo: "Quando", vazio: "Sem gatilho: roda quando você disser o nome." },
  { chave: "condicoes", titulo: "Se", vazio: "Sem condições: roda sempre." },
  { chave: "acoes", titulo: "Então", vazio: "Adicione pelo menos uma ação." },
];

function valorPadrao(item: ItemCatalogo): unknown {
  switch (item.entrada) {
    case "nenhum":
      return true;
    case "bool":
      return true;
    case "dias":
      return [0, 1, 2, 3, 4];
    case "intervalo":
      return "18:00-23:00";
    case "hora":
      return "08:00";
    case "numero":
      return Number(item.dica ?? 5) || 5;
    case "opcoes":
      return item.opcoes?.[0] ?? "";
    default:
      return "";
  }
}

const NOVO: ProtocoloEditor = { nome: "", ativo: true, criada_pela_ia: true, editavel: true, gatilhos: [], condicoes: [], acoes: [] };

export default function EditorProtocolos({ inicial, aoFechar }: { inicial: string; aoFechar: () => void }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);
  const [lista, setLista] = useState<ProtocoloEditor[]>([]);
  const [layouts, setLayouts] = useState<string[]>([]);
  const [nomeOriginal, setNomeOriginal] = useState<string | null>(null);
  const [atual, setAtual] = useState<ProtocoloEditor>(NOVO);
  const [salvando, setSalvando] = useState(false);

  const carregar = async (selecionar?: string) => {
    const r = await api<{ protocolos: ProtocoloEditor[]; catalogo: Catalogo; layouts: string[] }>("/api/protocolos");
    setCatalogo(r.catalogo);
    setLista(r.protocolos);
    setLayouts(r.layouts);
    const alvo = r.protocolos.find((p) => p.nome === selecionar);
    if (alvo) abrir(alvo);
    else if (selecionar === "") novo();
  };

  useEffect(() => {
    carregar(inicial).catch((e) => avisar(e.message, "erro"));
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && aoFechar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const abrir = (p: ProtocoloEditor) => {
    setNomeOriginal(p.nome);
    setAtual(structuredClone(p));
  };
  const novo = () => {
    setNomeOriginal(null);
    setAtual(structuredClone(NOVO));
  };

  const somenteLeitura = !atual.editavel;
  const mudarBloco = (coluna: Coluna, i: number, bloco: Bloco) => setAtual((a) => ({ ...a, [coluna]: a[coluna].map((b, j) => (j === i ? bloco : b)) }));
  const removerBloco = (coluna: Coluna, i: number) => setAtual((a) => ({ ...a, [coluna]: a[coluna].filter((_, j) => j !== i) }));
  const moverBloco = (coluna: Coluna, i: number, delta: number) =>
    setAtual((a) => {
      const itens = [...a[coluna]];
      const j = i + delta;
      if (j < 0 || j >= itens.length) return a;
      [itens[i], itens[j]] = [itens[j], itens[i]];
      return { ...a, [coluna]: itens };
    });
  const adicionar = (coluna: Coluna, tipo: string) => {
    const item = catalogo?.[coluna].find((c) => c.tipo === tipo);
    if (!item) return;
    const bloco: Bloco = { tipo, valor: valorPadrao(item) };
    if (coluna === "gatilhos" && tipo === "horario") bloco.dias = [];
    setAtual((a) => ({ ...a, [coluna]: [...a[coluna], bloco] }));
  };

  const salvar = async () => {
    if (!atual.nome.trim()) return avisar("Dê um nome ao protocolo.", "erro");
    if (!atual.acoes.length) return avisar("Adicione pelo menos uma ação.", "erro");
    const vazio = (["gatilhos", "condicoes", "acoes"] as Coluna[]).flatMap((c) =>
      atual[c]
        .filter((b) => {
          const item = catalogo?.[c].find((i) => i.tipo === b.tipo);
          const precisa = item && (["texto", "opcoes", "numero", "dias", "intervalo"] as Entrada[]).includes(item.entrada);
          const opcional = c === "gatilhos" && ["pendrive", "wifi"].includes(b.tipo);
          return precisa && !opcional && (b.valor === "" || b.valor === null || (Array.isArray(b.valor) && !b.valor.length));
        })
        .map((b) => catalogo?.[c].find((i) => i.tipo === b.tipo)?.rotulo ?? b.tipo),
    );
    if (vazio.length) return avisar(`Preencha: ${vazio.join(", ")}.`, "erro");
    setSalvando(true);
    try {
      const salvo = await api<ProtocoloEditor>("/api/protocolos", { method: "PUT", json: { ...atual, nome: atual.nome.trim(), nome_antigo: nomeOriginal } });
      avisar(`Protocolo ${salvo.nome} salvo.`, "sucesso");
      await carregar(salvo.nome);
    } catch (e: any) {
      avisar(e.message, "erro");
    } finally {
      setSalvando(false);
    }
  };

  const apagar = async () => {
    if (!nomeOriginal || !window.confirm(`Apagar o protocolo ${nomeOriginal}?`)) return;
    try {
      await api(`/api/protocolos/${encodeURIComponent(nomeOriginal)}`, { method: "DELETE" });
      avisar("Protocolo apagado.", "info");
      novo();
      await carregar();
    } catch (e: any) {
      avisar(e.message, "erro");
    }
  };

  const testar = () =>
    nomeOriginal &&
    api(`/api/rotinas/${encodeURIComponent(nomeOriginal)}/executar`, { method: "POST" })
      .then(() => avisar(`Rodando ${nomeOriginal}…`, "info"))
      .catch((e) => avisar(e.message, "erro"));

  const alternarAtivo = (p: ProtocoloEditor) =>
    api(`/api/protocolos/${encodeURIComponent(p.nome)}/ativo`, { method: "POST", json: { ativo: !p.ativo } })
      .then(() => carregar(nomeOriginal ?? undefined))
      .catch((e) => avisar(e.message, "erro"));

  return (
    <div className="absolute inset-0 z-[3300] grid place-items-center" role="dialog" aria-label="Editor de protocolos">
      <button type="button" aria-label="Fechar editor" className="absolute inset-0 bg-tinta-funda/60 cursor-default" onClick={aoFechar} />
      <section className="holo-corpo surgir relative w-[min(1180px,96vw)] h-[min(760px,92vh)] grid grid-cols-[240px_1fr] overflow-hidden">
        <nav className="border-r border-aco/20 flex flex-col min-h-0" aria-label="Protocolos">
          <h2 className="numeral text-[28px] font-[300] text-gelo px-5 pt-5 pb-3">Protocolos</h2>
          <ul className="flex-1 overflow-y-auto rolagem px-2">
            {lista.map((p) => (
              <li key={p.nome} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => abrir(p)}
                  aria-current={p.nome === nomeOriginal}
                  className={`flex-1 min-w-0 text-left px-3 py-2 rounded text-[14px] truncate first-letter:uppercase ${
                    p.nome === nomeOriginal
                      ? "bg-[rgb(var(--luz-rgb)/0.12)] text-[var(--luz)]"
                      : p.ativo
                        ? "text-gelo hover:bg-aco/10"
                        : "text-aco/60 hover:bg-aco/10"
                  }`}
                >
                  {p.nome}
                </button>
                <button
                  type="button"
                  role="switch"
                  aria-checked={p.ativo}
                  aria-label={`${p.ativo ? "Desativar" : "Ativar"} ${p.nome}`}
                  onClick={() => alternarAtivo(p)}
                  className={`relative h-4 w-7 shrink-0 rounded-full border ${p.ativo ? "border-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.25)]" : "border-aco/50"}`}
                >
                  <span className={`absolute top-[1px] size-3 rounded-full transition-all ${p.ativo ? "left-[13px] bg-[var(--luz)]" : "left-[1px] bg-aco"}`} />
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={novo}
            className="m-3 py-2 rounded-full border border-[var(--luz)]/60 text-sm text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]"
          >
            + Novo protocolo
          </button>
        </nav>

        <div className="flex flex-col min-h-0">
          <header className="flex items-center gap-4 px-6 pt-5 pb-3">
            <label className="flex-1">
              <span className="sr-only">Nome do protocolo</span>
              <input
                value={atual.nome}
                disabled={somenteLeitura}
                onChange={(e) => setAtual((a) => ({ ...a, nome: e.target.value }))}
                placeholder="Nome do protocolo (ex.: modo valorant)"
                className="w-full bg-transparent border-b border-aco/40 py-1 text-[22px] text-gelo outline-none focus:border-[var(--luz)] placeholder:text-aco/50"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-aco">
              <input
                type="checkbox"
                checked={atual.ativo}
                disabled={somenteLeitura}
                onChange={(e) => setAtual((a) => ({ ...a, ativo: e.target.checked }))}
                className="accent-[var(--luz)]"
              />
              Ativo
            </label>
            <button type="button" aria-label="Fechar" onClick={aoFechar} className="p-1 text-aco hover:text-gelo">
              <Icone.Fechar tamanho={20} />
            </button>
          </header>
          {somenteLeitura && <p className="mx-6 mb-2 text-xs text-coral">Este protocolo roda comandos do sistema: edite-o no arquivo config/rotinas.yaml.</p>}

          <div className="flex-1 min-h-0 grid grid-cols-3 gap-4 px-6 pb-4 overflow-hidden">
            {COLUNAS.map(({ chave, titulo, vazio }, indiceColuna) => (
              <div key={chave} className="flex flex-col min-h-0">
                <h3 className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-aco mb-2">
                  {titulo}
                  {indiceColuna < 2 && <span className="text-[var(--luz)]/60 normal-case tracking-normal">→</span>}
                </h3>
                <div className="flex-1 overflow-y-auto rolagem space-y-2 pr-1">
                  {atual[chave].length === 0 && <p className="text-xs text-aco/70 leading-snug">{vazio}</p>}
                  {atual[chave].map((bloco, i) => (
                    <CartaoBloco
                      key={`${chave}-${i}`}
                      bloco={bloco}
                      item={catalogo?.[chave].find((c) => c.tipo === bloco.tipo)}
                      layouts={layouts}
                      somenteLeitura={somenteLeitura}
                      aoMudar={(b) => mudarBloco(chave, i, b)}
                      aoRemover={() => removerBloco(chave, i)}
                      aoMover={chave === "acoes" ? (d) => moverBloco(chave, i, d) : undefined}
                    />
                  ))}
                </div>
                {!somenteLeitura && catalogo && (
                  <select
                    value=""
                    aria-label={`Adicionar em ${titulo}`}
                    onChange={(e) => adicionar(chave, e.target.value)}
                    className="mt-2 bg-tinta border border-dashed border-aco/50 rounded px-2 py-1.5 text-sm text-aco hover:text-gelo"
                  >
                    <option value="">+ adicionar…</option>
                    {catalogo[chave].map((c) => (
                      <option key={c.tipo} value={c.tipo}>
                        {c.rotulo}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            ))}
          </div>

          <footer className="flex items-center gap-3 px-6 py-4 border-t border-aco/20">
            <p className="flex-1 text-xs text-aco leading-snug">
              Dica: textos aceitam <code className="text-gelo">{"{app}"}</code>, <code className="text-gelo">{"{nome_arquivo}"}</code>,{" "}
              <code className="text-gelo">{"{rede}"}</code> e <code className="text-gelo">{"{bateria}"}</code>. Protocolos não pedem confirmação a cada passo.
            </p>
            {nomeOriginal && atual.criada_pela_ia && (
              <button type="button" onClick={apagar} className="px-4 py-1.5 rounded-full text-sm text-coral hover:bg-coral/10">
                Apagar
              </button>
            )}
            {nomeOriginal && (
              <button type="button" onClick={testar} className="px-4 py-1.5 rounded-full border border-aco/40 text-sm text-aco hover:text-gelo">
                Testar agora
              </button>
            )}
            <button
              type="button"
              disabled={salvando || somenteLeitura}
              onClick={salvar}
              className="px-5 py-1.5 rounded-full border border-[var(--luz)] text-sm text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)] disabled:opacity-40"
            >
              {salvando ? "Salvando…" : "Salvar"}
            </button>
          </footer>
        </div>
      </section>
    </div>
  );
}

function CartaoBloco({
  bloco,
  item,
  layouts,
  somenteLeitura,
  aoMudar,
  aoRemover,
  aoMover,
}: {
  bloco: Bloco;
  item?: ItemCatalogo;
  layouts: string[];
  somenteLeitura: boolean;
  aoMudar: (b: Bloco) => void;
  aoRemover: () => void;
  aoMover?: (delta: number) => void;
}) {
  const rotulo = item?.rotulo ?? bloco.tipo.replaceAll("_", " ");
  const entrada: Entrada = bloco.tipo === "executar" ? "texto" : (item?.entrada ?? "texto");
  const idLista = useMemo(() => `layouts-${Math.random().toString(36).slice(2)}`, []);
  const campo = "w-full bg-transparent border-b border-aco/40 py-1 text-[14px] text-gelo outline-none focus:border-[var(--luz)] placeholder:text-aco/50";
  const set = (valor: unknown) => aoMudar({ ...bloco, valor });

  let editor: React.ReactNode = null;
  switch (entrada) {
    case "nenhum":
      break;
    case "numero":
      editor = (
        <input type="number" disabled={somenteLeitura} value={Number(bloco.valor ?? 0)} onChange={(e) => set(Number(e.target.value))} className={campo} />
      );
      break;
    case "hora":
      editor = (
        <>
          <input type="time" disabled={somenteLeitura} value={String(bloco.valor ?? "08:00")} onChange={(e) => set(e.target.value)} className={campo} />
          <SeletorDias
            dias={bloco.dias ?? []}
            desabilitado={somenteLeitura}
            aoMudar={(dias) => aoMudar({ ...bloco, dias })}
            dica="Sem dias marcados = todo dia"
          />
        </>
      );
      break;
    case "dias":
      editor = <SeletorDias dias={(bloco.valor as number[]) ?? []} desabilitado={somenteLeitura} aoMudar={set} />;
      break;
    case "intervalo": {
      const [ini = "18:00", fim = "23:00"] = String(bloco.valor ?? "").split("-");
      editor = (
        <div className="flex items-center gap-2">
          <input type="time" disabled={somenteLeitura} value={ini} onChange={(e) => set(`${e.target.value}-${fim}`)} className={campo} />
          <span className="text-aco text-xs">até</span>
          <input type="time" disabled={somenteLeitura} value={fim} onChange={(e) => set(`${ini}-${e.target.value}`)} className={campo} />
        </div>
      );
      break;
    }
    case "bool":
      editor = (
        <div className="flex gap-1.5" role="radiogroup" aria-label={rotulo}>
          {[
            [true, "Sim"],
            [false, "Não"],
          ].map(([v, r]) => (
            <button
              key={String(v)}
              type="button"
              role="radio"
              aria-checked={bloco.valor === v}
              disabled={somenteLeitura}
              onClick={() => set(v)}
              className={`px-3 py-0.5 rounded-full border text-xs ${bloco.valor === v ? "border-[var(--luz)] text-[var(--luz)]" : "border-aco/40 text-aco"}`}
            >
              {r as string}
            </button>
          ))}
        </div>
      );
      break;
    case "opcoes":
      editor = (
        <select
          disabled={somenteLeitura}
          value={String(bloco.valor ?? "")}
          onChange={(e) => set(e.target.value)}
          className="w-full bg-tinta border border-aco/40 rounded px-2 py-1 text-[14px] text-gelo"
        >
          {(item?.opcoes ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
      break;
    default:
      editor = (
        <>
          <input
            disabled={somenteLeitura}
            value={bloco.valor === true ? "" : String(bloco.valor ?? "")}
            placeholder={item?.dica}
            list={bloco.tipo === "layout" ? idLista : undefined}
            onChange={(e) => set(e.target.value)}
            className={campo}
          />
          {bloco.tipo === "layout" && (
            <datalist id={idLista}>
              {layouts.map((l) => (
                <option key={l} value={l} />
              ))}
            </datalist>
          )}
        </>
      );
  }

  return (
    <div className="rounded border border-[var(--luz)]/35 bg-[rgb(var(--luz-rgb)/0.04)] px-3 py-2">
      <div className="flex items-center gap-1">
        <span className="flex-1 text-[13px] text-[var(--luz)]">{rotulo}</span>
        {aoMover && !somenteLeitura && (
          <>
            <button type="button" aria-label="Subir" onClick={() => aoMover(-1)} className="px-1 text-aco hover:text-gelo text-xs">
              ▲
            </button>
            <button type="button" aria-label="Descer" onClick={() => aoMover(1)} className="px-1 text-aco hover:text-gelo text-xs">
              ▼
            </button>
          </>
        )}
        {!somenteLeitura && (
          <button type="button" aria-label={`Remover ${rotulo}`} onClick={aoRemover} className="p-0.5 text-aco hover:text-coral">
            <Icone.Fechar tamanho={13} />
          </button>
        )}
      </div>
      {editor && <div className="mt-1.5 space-y-1.5">{editor}</div>}
    </div>
  );
}

function SeletorDias({ dias, aoMudar, desabilitado, dica }: { dias: number[]; aoMudar: (d: number[]) => void; desabilitado?: boolean; dica?: string }) {
  return (
    <div>
      <div className="flex gap-1">
        {DIAS.map((d, i) => {
          const marcado = dias.includes(i);
          return (
            <button
              key={d}
              type="button"
              aria-pressed={marcado}
              disabled={desabilitado}
              onClick={() => aoMudar(marcado ? dias.filter((x) => x !== i) : [...dias, i].sort())}
              className={`w-8 py-0.5 rounded text-[11px] border ${marcado ? "border-[var(--luz)] text-[var(--luz)] bg-[rgb(var(--luz-rgb)/0.12)]" : "border-aco/30 text-aco"}`}
            >
              {d}
            </button>
          );
        })}
      </div>
      {dica && <p className="text-[11px] text-aco/60 mt-1">{dica}</p>}
    </div>
  );
}
