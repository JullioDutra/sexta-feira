// Holograma "Onde você parou": programas, arquivos e páginas da sessão anterior, com caixas de seleção e o
// botão "Reabrir" (o servidor só reabre o que está anotado na sessão, pelos índices).
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";
import { horaCurta, type DadosRetomar } from "./tipos";

type Selecao = { apps: boolean[]; arquivos: boolean[]; abas: boolean[] };

const NOMES: Record<string, string> = {
  code: "VS Code", chrome: "Chrome", msedge: "Edge", firefox: "Firefox", brave: "Brave", winword: "Word",
  excel: "Excel", powerpnt: "PowerPoint", outlook: "Outlook", notepad: "Bloco de Notas", spotify: "Spotify",
  discord: "Discord", whatsapp: "WhatsApp", windowsterminal: "Terminal",
};

function indices(lista: boolean[]): number[] {
  return lista.flatMap((v, i) => (v ? [i] : []));
}

export default function HologramaRetomar({ dados, largura = 460 }: { dados: DadosRetomar; largura?: number }) {
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const avisar = useHud((s) => s.acoes.avisar);
  const sessao = dados?.sessao;
  const [sel, setSel] = useState<Selecao>({ apps: [], arquivos: [], abas: [] });
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    if (!sessao) return;
    setSel({ apps: sessao.apps.map(() => true), arquivos: sessao.arquivos.map(() => true), abas: sessao.abas.map(() => true) });
  }, [sessao?.id, sessao?.fim]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!sessao)
    return (
      <p style={{ width: largura }} className="max-w-full text-sm text-aco leading-snug">
        Ainda não anotei nenhuma sessão. No Windows, eu anoto a cada 5 minutos de uso os programas, arquivos e páginas abertos.
      </p>
    );

  const marcar = (grupo: keyof Selecao, i: number) =>
    setSel((s) => ({ ...s, [grupo]: s[grupo].map((v, j) => (j === i ? !v : v)) }));

  const reabrir = () => {
    setOcupado(true);
    api<{ texto: string }>("/api/retomar/reabrir", {
      method: "POST",
      json: { sessao: sessao.id, apps: indices(sel.apps), arquivos: indices(sel.arquivos), abas: indices(sel.abas) },
    })
      .then((r) => avisar(r.texto, "sucesso"))
      .catch((e) => avisar(e.message, "erro"))
      .finally(() => setOcupado(false));
  };

  const total = indices(sel.apps).length + indices(sel.arquivos).length + indices(sel.abas).length;
  return (
    <div style={{ width: largura }} className="max-w-full">
      <p className="text-xs text-aco">
        Sessão de {horaCurta(sessao.inicio)} até {horaCurta(sessao.fim).replace(/^hoje, /, "")}
      </p>
      <div className="mt-1 max-h-[420px] overflow-y-auto rolagem pr-1 -mr-1">
        <Grupo titulo="Programas" vazio="nenhum programa">
          {sessao.apps.map((a, i) => (
            <Item key={a.caminho} marcado={sel.apps[i] ?? false} aoMudar={() => marcar("apps", i)} titulo={NOMES[a.exe] ?? a.exe} detalhe={a.titulo} />
          ))}
        </Grupo>
        <Grupo titulo="Arquivos" vazio="nenhum arquivo">
          {sessao.arquivos.map((a, i) => (
            <Item key={a.caminho} marcado={sel.arquivos[i] ?? false} aoMudar={() => marcar("arquivos", i)} titulo={a.nome} detalhe={a.caminho} />
          ))}
        </Grupo>
        <Grupo titulo="Páginas" vazio="nenhuma página">
          {sessao.abas.map((a, i) => (
            <Item key={a.url} marcado={sel.abas[i] ?? false} aoMudar={() => marcar("abas", i)} titulo={a.titulo} detalhe={a.url} />
          ))}
        </Grupo>
      </div>
      {noPc && (
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-aco/20 pt-2">
          <span className="text-xs text-aco">Programas já abertos não abrem de novo.</span>
          <button
            type="button"
            data-clicavel
            disabled={ocupado || total === 0}
            onClick={reabrir}
            className="shrink-0 rounded border border-[var(--luz)]/50 px-3 py-1 text-sm text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.1)] disabled:opacity-40"
          >
            Reabrir {total > 0 ? `(${total})` : ""}
          </button>
        </div>
      )}
    </div>
  );
}

function Grupo({ titulo, vazio, children }: { titulo: string; vazio: string; children: React.ReactNode[] }) {
  return (
    <section>
      <h3 className="mt-3 mb-1 text-[11px] uppercase tracking-[0.18em] text-aco">{titulo}</h3>
      {children.length ? <ul className="space-y-0.5">{children}</ul> : <p className="text-xs text-aco/70">{vazio}</p>}
    </section>
  );
}

function Item({ marcado, aoMudar, titulo, detalhe }: { marcado: boolean; aoMudar: () => void; titulo: string; detalhe: string }) {
  return (
    <li>
      <label data-clicavel className="flex cursor-pointer items-start gap-2 rounded px-1 py-0.5 hover:bg-[rgb(var(--luz-rgb)/0.06)]">
        <input type="checkbox" checked={marcado} onChange={aoMudar} className="mt-1 accent-[var(--luz)]" />
        <span className="min-w-0">
          <span className="block truncate text-[13px] text-gelo">{titulo}</span>
          <span className="block truncate text-[11px] text-aco" title={detalhe}>
            {detalhe}
          </span>
        </span>
      </label>
    </li>
  );
}
