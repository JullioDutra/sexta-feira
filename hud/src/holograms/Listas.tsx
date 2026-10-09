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
};

export function Rotinas() {
  const rotinas = useHud((s) => s.rotinas);
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
  if (!rotinas.length) return <p className="w-[340px] text-sm text-aco">Nenhuma rotina. Edite config/rotinas.yaml ou peça por voz.</p>;
  return (
    <ul className="w-[380px] max-h-[400px] overflow-y-auto rolagem pr-1">
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
            <span className="min-w-0">
              <span className="block text-[15px] text-gelo first-letter:uppercase">{r.nome}</span>
              <span className="block text-xs text-aco truncate">
                {emAndamento ? `Passo ${ativa!.passo} de ${ativa!.total}` : acoes.join(", ")}
                {r.horario && !emAndamento ? `. Sozinha às ${r.horario}` : ""}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
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
