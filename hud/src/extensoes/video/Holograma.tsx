// Holograma "Vídeos": trabalhos em andamento (barra de progresso, cancelar) e os últimos arquivos gerados
// (prévia, abrir e mostrar na pasta). A prévia vem de /api/videos/arquivo/<id>, que só serve o que a Sexta gerou.
import { useState } from "react";
import { api, comToken } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Icone } from "../../holograms/Glifos";
import { useTrabalhos, type DadosVideos, type Gerado, type Trabalho } from "./tipos";

const ROTULO_ESTADO: Record<Trabalho["estado"], string> = {
  fila: "Na fila",
  rodando: "",
  ok: "Pronto",
  erro: "Falhou",
  cancelado: "Cancelado",
};

export default function HologramaVideos({ dados, largura = 440 }: { dados: DadosVideos; largura?: number }) {
  const vivos = useTrabalhos((s) => s.trabalhos);
  const trabalhos = (vivos ?? dados?.trabalhos ?? []).slice().reverse();
  const ativos = trabalhos.filter((t) => t.estado === "fila" || t.estado === "rodando");
  const recentes = trabalhos.filter((t) => t.estado === "erro").slice(0, 2);
  const gerados = dados?.gerados ?? [];
  return (
    <div style={{ width: largura }} className="max-w-full">
      {ativos.length + recentes.length > 0 ? (
        <ul className="space-y-2">
          {[...ativos, ...recentes].map((t) => (
            <ItemTrabalho key={t.id} trabalho={t} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-aco leading-snug">Nenhum vídeo sendo feito agora. Diga, por exemplo: “corta o último vídeo do 0:30 ao 1:15”.</p>
      )}
      <h3 className="mt-3 mb-1 text-[11px] uppercase tracking-[0.18em] text-aco">Últimos gerados</h3>
      {gerados.length ? (
        <ul className="max-h-[340px] overflow-y-auto rolagem pr-1 -mr-1 space-y-1.5">
          {gerados.map((g, i) => (
            <ItemGerado key={g.id} gerado={g} aberto={i === 0} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-aco">Nada ainda.</p>
      )}
      {dados?.pasta && (
        <p className="mt-2 truncate text-[11px] text-aco/80" title={dados.pasta}>
          {dados.pasta}
        </p>
      )}
    </div>
  );
}

function ItemTrabalho({ trabalho: t }: { trabalho: Trabalho }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const ativo = t.estado === "fila" || t.estado === "rodando";
  const cancelar = () =>
    api<{ texto: string }>("/api/videos/cancelar", { method: "POST", json: { id: t.id } })
      .then((r) => avisar(r.texto, "info"))
      .catch((e) => avisar(e.message, "erro"));
  const pct = Math.round(t.progresso * 100);
  return (
    <li className="rounded border border-aco/20 bg-[rgb(var(--luz-rgb)/0.03)] px-2.5 py-2">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] text-gelo" title={t.rotulo}>
          {t.rotulo}
        </span>
        <span className={`numeral shrink-0 text-xs ${t.estado === "erro" ? "text-coral" : "text-[var(--luz)]"}`}>
          {t.estado === "rodando" ? `${pct}%` : ROTULO_ESTADO[t.estado]}
        </span>
        {ativo && (
          <button type="button" data-clicavel onClick={cancelar} aria-label={`Cancelar: ${t.rotulo}`} className="shrink-0 p-0.5 text-aco hover:text-coral">
            <Icone.Fechar tamanho={14} />
          </button>
        )}
      </div>
      {ativo && (
        <div className="mt-1.5 h-1.5 rounded-full bg-aco/20 overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div
            className={`h-full rounded-full bg-[var(--luz)] transition-[width] duration-500 ${t.estado === "fila" ? "opacity-30" : ""}`}
            style={{ width: `${t.estado === "fila" ? 0 : Math.max(2, pct)}%` }}
          />
        </div>
      )}
      {t.etapa && ativo && <p className="mt-1 text-[11px] text-aco">{t.etapa}…</p>}
      {t.estado === "erro" && <p className="mt-1 text-xs text-coral leading-snug">{t.erro}</p>}
    </li>
  );
}

function ItemGerado({ gerado: g, aberto }: { gerado: Gerado; aberto: boolean }) {
  const avisar = useHud((s) => s.acoes.avisar);
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const [previa, setPrevia] = useState(aberto && g.existe && g.tipo !== "legenda");
  const url = comToken(`/api/videos/arquivo/${g.id}`);
  const abrir = (pasta: boolean) =>
    api<{ texto: string }>("/api/videos/abrir", { method: "POST", json: { id: g.id, pasta } })
      .then((r) => avisar(r.texto, "sucesso"))
      .catch((e) => avisar(e.message, "erro"));
  return (
    <li className="rounded border border-aco/20 px-2.5 py-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-clicavel
          disabled={!g.existe || g.tipo === "legenda"}
          onClick={() => setPrevia((v) => !v)}
          className="min-w-0 flex-1 text-left disabled:cursor-default"
          aria-expanded={previa}
        >
          <span className={`block truncate text-[13px] ${g.existe ? "text-gelo" : "text-aco line-through"}`} title={g.caminho}>
            {g.nome}
          </span>
          <span className="block text-[11px] text-aco">
            {g.tamanho} · {new Date(g.criado * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
            {!g.existe && " · apagado"}
          </span>
        </button>
        {noPc && g.existe && (
          <>
            <button type="button" data-clicavel onClick={() => abrir(false)} className="shrink-0 inline-flex items-center gap-1 text-xs text-[var(--luz)] hover:text-gelo">
              Abrir <Icone.Externo tamanho={12} />
            </button>
            <button type="button" data-clicavel onClick={() => abrir(true)} className="shrink-0 text-xs text-aco hover:text-gelo">
              Pasta
            </button>
          </>
        )}
      </div>
      {previa && g.existe && (
        <div className="mt-2">
          {g.tipo === "video" && <video src={url} controls preload="metadata" playsInline className="w-full max-h-[220px] rounded bg-black" />}
          {g.tipo === "gif" && <img src={url} alt={g.nome} className="w-full max-h-[220px] object-contain rounded" />}
          {g.tipo === "audio" && <audio src={url} controls preload="metadata" className="w-full" />}
        </div>
      )}
    </li>
  );
}
