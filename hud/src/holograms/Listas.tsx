// Lembretes, rotinas, câmera, notas e imagens.
import { useState } from "react";
import { api, comToken } from "../lib/api";
import { useHud } from "../lib/store";
import type { Lembrete, Rotina } from "../lib/tipos";
import { Icone } from "./Glifos";

const REPETICAO: Record<Lembrete["repetir"], string> = {
  nao: "",
  diario: "todo dia",
  dias_uteis: "dias úteis",
  semanal: "toda semana",
};

export function Lembretes() {
  const lembretes = useHud((s) => s.lembretes);
  const avisar = useHud((s) => s.acoes.avisar);
  if (!lembretes.length)
    return (
      <p className="w-[340px] text-sm text-aco leading-relaxed">
        Nenhum lembrete. Diga, por exemplo: "Sexta-Feira, me lembra de ligar pro João amanhã às 10h".
      </p>
    );
  return (
    <ol className="w-[360px] max-h-[380px] overflow-y-auto rolagem pr-1">
      {lembretes.map((l, i) => (
        <li key={l.id} className={`grid grid-cols-[64px_1fr_28px] gap-3 py-2.5 items-center ${i ? "border-t border-aco/15" : ""}`}>
          <span className="numeral text-2xl text-[var(--luz)] text-right leading-none">{l.hora}</span>
          <span className="min-w-0">
            <span className="block text-[15px] text-gelo truncate">{l.texto}</span>
            <span className="flex items-center gap-1.5 text-xs text-aco mt-0.5">
              {l.alarme && <Icone.Alarme tamanho={12} />}
              {l.descricao}
              {l.repetir !== "nao" && (
                <>
                  <Icone.Repetir tamanho={12} className="ml-1" /> {REPETICAO[l.repetir]}
                </>
              )}
            </span>
          </span>
          <button
            type="button"
            aria-label={`Cancelar lembrete ${l.texto}`}
            data-clicavel
            className="p-1 text-aco hover:text-coral"
            onClick={() => api(`/api/lembretes/${l.id}`, { method: "DELETE" }).catch((e) => avisar(e.message, "erro"))}
          >
            <Icone.Lixeira tamanho={16} />
          </button>
        </li>
      ))}
    </ol>
  );
}

const NOMES_ACOES: Record<string, string> = {
  falar: "fala",
  abrir: "abre",
  fechar: "fecha",
  tocar_youtube: "toca música",
  pesquisar: "pesquisa",
  volume: "volume",
  midia: "mídia",
  esperar: "espera",
  clima: "clima",
  noticias: "notícias",
  briefing: "resumo do dia",
  lembretes: "lembretes",
  holograma: "holograma",
  print: "print",
  bloquear: "bloqueia o PC",
  executar: "comando",
  layout: "layout",
  minimizar_tudo: "minimiza tudo",
  plano_energia: "energia",
  nao_perturbe: "não perturbe",
  modo_escuro: "modo escuro",
  brilho: "brilho",
  organizar_downloads: "organiza Downloads",
  notificar: "avisa no celular",
  mover_arquivo: "move o arquivo",
};

export function Rotinas() {
  const rotinas = useHud((s) => s.rotinas);
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const abrirEditor = useHud((s) => s.acoes.abrirEditor);
  const ativa = useHud((s) => s.rotinaAtiva);
  const avisar = useHud((s) => s.acoes.avisar);
  const [rodando, setRodando] = useState<string | null>(null);
  const executar = async (r: Rotina) => {
    setRodando(r.nome);
    try {
      await api(`/api/rotinas/${encodeURIComponent(r.nome)}/executar`, { method: "POST" });
    } catch (e: any) {
      avisar(e.message, "erro");
    } finally {
      window.setTimeout(() => setRodando(null), 1200);
    }
  };
  const botaoNovo = noPc && (
    <button
      type="button"
      data-clicavel
      onClick={() => abrirEditor("")}
      className="mt-2 w-full py-1.5 rounded-full border border-dashed border-[var(--luz)]/50 text-sm text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.1)]"
    >
      + Novo protocolo
    </button>
  );
  if (!rotinas.length)
    return (
      <div className="w-[340px]">
        <p className="text-sm text-aco">Nenhum protocolo. Peça por voz ("toda vez que eu abrir o Valorant…") ou crie um aqui.</p>
        {botaoNovo}
      </div>
    );
  return (
    <div className="w-[400px]">
      <ul className="max-h-[400px] overflow-y-auto rolagem pr-1">
        {rotinas.map((r, i) => {
          const emAndamento = ativa?.nome === r.nome;
          const acoes = [...new Set(r.acoes.map((a) => NOMES_ACOES[a] ?? a))];
          return (
            <li key={r.nome} className={`flex items-center gap-3 py-2.5 ${i ? "border-t border-aco/15" : ""}`}>
              <button
                type="button"
                data-clicavel
                aria-label={`Executar ${r.nome}`}
                disabled={rodando === r.nome}
                onClick={() => executar(r)}
                className="grid place-items-center size-9 shrink-0 rounded-full border border-[var(--luz)]/50 text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)] disabled:opacity-50"
              >
                <Icone.Executar tamanho={15} />
              </button>
              <span className="min-w-0 flex-1">
                <span className={`block text-[15px] first-letter:uppercase ${r.ativo === false ? "text-aco/60 line-through" : "text-gelo"}`}>{r.nome}</span>
                <span className="block text-xs text-aco truncate">
                  {emAndamento ? `Passo ${ativa!.passo} de ${ativa!.total}` : r.gatilhos?.length ? `${r.gatilhos[0]} → ${acoes.join(", ")}` : acoes.join(", ")}
                </span>
              </span>
              {noPc && (
                <button
                  type="button"
                  data-clicavel
                  aria-label={`Editar ${r.nome}`}
                  onClick={() => abrirEditor(r.nome)}
                  className="shrink-0 px-2 py-1 text-xs text-aco hover:text-[var(--luz)]"
                >
                  Editar
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {botaoNovo}
    </div>
  );
}

export function Camera() {
  return (
    <div className="w-[360px]">
      <div className="relative aspect-[4/3] bg-tinta-funda overflow-hidden">
        <img src={comToken("/api/camera.mjpg")} alt="Imagem da câmera" className="size-full object-cover" />
      </div>
      <p className="mt-2 text-xs text-aco">A câmera desliga sozinha quando este holograma fecha.</p>
    </div>
  );
}

export function Nota({ dados }: { dados: { texto?: string } }) {
  return <p className="w-[340px] whitespace-pre-wrap text-[15px] leading-relaxed text-gelo">{dados?.texto || "(vazio)"}</p>;
}

export function Imagem({ dados }: { dados: { url: string; legenda?: string } }) {
  return (
    <figure className="w-[520px]">
      <img src={comToken(dados.url)} alt={dados.legenda ?? "Imagem"} className="w-full max-h-[320px] object-contain bg-tinta-funda" />
      {dados.legenda && <figcaption className="mt-2 text-xs text-aco truncate">{dados.legenda}</figcaption>}
    </figure>
  );
}

interface Atividade {
  ts: number;
  ferramenta: string;
  nivel: "livre" | "confirmada" | "rosto";
  situacao: "ok" | "falhou" | "aguardando" | "cancelada" | "negada";
  resumo: string;
  canal: string;
}

const SITUACAO: Record<Atividade["situacao"], { rotulo: string; cor: string }> = {
  ok: { rotulo: "feito", cor: "text-[var(--luz)]" },
  falhou: { rotulo: "falhou", cor: "text-coral" },
  aguardando: { rotulo: "aguardando", cor: "text-gelo" },
  cancelada: { rotulo: "cancelado", cor: "text-aco" },
  negada: { rotulo: "negado", cor: "text-coral" },
};
const NIVEL: Record<Atividade["nivel"], string> = { livre: "", confirmada: "confirmado por voz", rosto: "rosto + voz" };

export function Atividades({ dados }: { dados: { itens?: Atividade[] } }) {
  const itens = dados?.itens ?? [];
  if (!itens.length) return <p className="w-[360px] text-sm text-aco">Nada por aqui ainda. Tudo que eu fizer no computador aparece neste registro.</p>;
  return (
    <ol className="w-[400px] max-h-[400px] overflow-y-auto rolagem pr-1" aria-label="Registro de atividades">
      {itens.map((a, i) => {
        const s = SITUACAO[a.situacao] ?? SITUACAO.ok;
        const hora = new Date(a.ts * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        return (
          <li key={`${a.ts}-${i}`} className={`grid grid-cols-[46px_1fr] gap-3 py-2 ${i ? "border-t border-aco/15" : ""}`}>
            <span className="numeral text-sm text-aco text-right pt-0.5">{hora}</span>
            <span className="min-w-0">
              <span className="block text-[14px] text-gelo leading-snug">{a.resumo || a.ferramenta}</span>
              <span className="flex flex-wrap gap-x-2 text-xs mt-0.5">
                <span className={s.cor}>{s.rotulo}</span>
                {NIVEL[a.nivel] && <span className="text-aco">{NIVEL[a.nivel]}</span>}
                <span className="text-aco/70">{a.canal === "celular" ? "pelo celular" : a.ferramenta}</span>
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

interface Bloco {
  tipo: string;
  valor: unknown;
  dias?: number[];
}

export function Protocolo({ dados }: { dados: { protocolo: { nome: string; gatilhos: Bloco[]; condicoes: Bloco[]; acoes: Bloco[] }; resumo: string } }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const [enviando, setEnviando] = useState(false);
  const p = dados?.protocolo;
  if (!p) return null;
  const responder = async (aprovar: boolean) => {
    setEnviando(true);
    try {
      const r = await api<{ texto: string }>("/api/pendente", { method: "POST", json: { aprovar } });
      avisar(r.texto, aprovar ? "sucesso" : "info");
    } catch (e: any) {
      avisar(e.message, "erro");
    } finally {
      setEnviando(false);
    }
  };
  const valor = (b: Bloco) => (b.valor === true || b.valor === null || b.valor === "" ? "" : Array.isArray(b.valor) ? b.valor.join(", ") : String(b.valor));
  const coluna = (titulo: string, blocos: Bloco[]) => (
    <div className="min-w-0">
      <h3 className="text-xs uppercase tracking-wider text-aco mb-1.5">{titulo}</h3>
      {blocos.length ? (
        <ul className="space-y-1.5">
          {blocos.map((b, i) => (
            <li key={i} className="border border-[var(--luz)]/35 rounded px-2 py-1.5 text-[13px] text-gelo">
              <span className="text-[var(--luz)]">{b.tipo.replaceAll("_", " ")}</span> {valor(b)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-aco/70">sempre</p>
      )}
    </div>
  );
  return (
    <div className="w-[460px]">
      <div className="grid grid-cols-3 gap-3">
        {coluna("Quando", p.gatilhos)}
        {coluna("Se", p.condicoes)}
        {coluna("Então", p.acoes)}
      </div>
      <p className="mt-3 text-xs text-aco leading-snug">{dados.resumo}</p>
      <div className="mt-3 flex gap-2 justify-end">
        <button
          type="button"
          data-clicavel
          disabled={enviando}
          onClick={() => responder(false)}
          className="px-4 py-1.5 rounded-full border border-aco/40 text-sm text-aco hover:text-gelo"
        >
          Cancelar
        </button>
        <button
          type="button"
          data-clicavel
          disabled={enviando}
          onClick={() => responder(true)}
          className="px-4 py-1.5 rounded-full border border-[var(--luz)] text-sm text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]"
        >
          Aprovar
        </button>
      </div>
    </div>
  );
}
