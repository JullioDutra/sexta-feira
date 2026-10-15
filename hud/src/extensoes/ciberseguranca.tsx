// Extensão "ciberseguranca": holograma da auditoria de segurança (site, rede, PC) — defensiva, só leitura.
import type { Extensao } from "./tipos";

interface Item {
  risco: "alto" | "medio" | "baixo" | "ok";
  titulo: string;
  detalhe?: string;
  sugestao?: string;
}
interface Servico {
  porta: number;
  servico: string;
  banner?: string;
}
interface Aparelho {
  ip: string;
  nome?: string;
  servicos: Servico[];
}
interface Relatorio {
  tipo: string;
  alvo?: string;
  url_final?: string;
  risco: Item["risco"];
  itens: Item[];
  aparelhos?: Aparelho[];
  mudancas?: string[];
  erro?: string;
  carregando?: boolean;
  dica?: string;
}

const COR: Record<Item["risco"], string> = {
  alto: "text-coral",
  medio: "text-[var(--luz)]",
  baixo: "text-aco",
  ok: "text-menta",
};
const ROTULO: Record<Item["risco"], string> = { alto: "alto", medio: "médio", baixo: "baixo", ok: "ok" };

function Auditoria({ dados, largura = 480 }: { dados: Relatorio; largura?: number }) {
  if (dados?.carregando) return <p className="text-sm text-aco" role="status">Auditando…</p>;
  if (!dados || dados.tipo === "vazio") return <p className="text-sm text-aco leading-snug">{dados?.dica ?? "Nenhuma auditoria ainda."}</p>;
  if (dados.erro) return <p className="text-sm text-coral">{dados.erro}</p>;
  return (
    <div style={{ width: largura }} className="space-y-2">
      <p className="text-[13px] text-aco">
        {dados.alvo} · risco geral <span className={COR[dados.risco]}>{ROTULO[dados.risco]}</span>
        {dados.url_final && dados.url_final !== dados.alvo ? ` · ${dados.url_final}` : ""}
      </p>
      {dados.aparelhos && dados.aparelhos.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-gelo">{dados.aparelhos.length} aparelho(s) na rede</summary>
          <ul className="mt-1 space-y-0.5">
            {dados.aparelhos.map((h) => (
              <li key={h.ip} className="text-aco">
                <span className="text-gelo">{h.ip}</span> {h.nome ?? ""} — {h.servicos.map((s) => `${s.servico}(${s.porta})`).join(", ")}
              </li>
            ))}
          </ul>
        </details>
      )}
      <ul className="max-h-[320px] overflow-y-auto rolagem pr-1 space-y-1">
        {dados.itens.length === 0 && <li className="text-sm text-menta">Nada de grave encontrado.</li>}
        {dados.itens.map((i, n) => (
          <li key={n} className="border-b border-aco/10 py-1">
            <p className="text-[14px]">
              <span className={COR[i.risco]}>[{ROTULO[i.risco]}]</span> <span className="text-gelo">{i.titulo}</span>
            </p>
            {i.detalhe && <p className="text-[12px] text-aco leading-snug">{i.detalhe}</p>}
            {i.sugestao && <p className="text-[12px] text-menta leading-snug">↳ {i.sugestao}</p>}
          </li>
        ))}
      </ul>
      {dados.mudancas && dados.mudancas.length > 0 && (
        <div className="text-[12px] text-aco">
          <p className="text-gelo">Desde a última auditoria:</p>
          {dados.mudancas.map((m, n) => (
            <p key={n}>• {m}</p>
          ))}
        </div>
      )}
    </div>
  );
}

function AuditoriaCelular({ dados }: { dados: Relatorio }) {
  return <Auditoria dados={dados} largura={340} />;
}

const glifo = (tamanho: number) => (
  <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3 5 6v5c0 4 3 7 7 9 4-2 7-5 7-9V6l-7-3Z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);

const extensao: Extensao = {
  hologramas: { ciberseguranca: { componente: Auditoria, celular: AuditoriaCelular, glifo } },
  doca: [{ tipo: "ciberseguranca", rotulo: "Auditoria" }],
};

export default extensao;
