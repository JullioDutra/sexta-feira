// Holograma "Segurança": relatório da análise de um arquivo ou da revisão do PC, com o nível de risco em cor,
// evidências expansíveis, ações sugeridas (pedem confirmação) e o histórico das últimas análises.
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Icone } from "../../holograms/Glifos";
import {
  BORDA_RISCO,
  CATEGORIAS,
  COR_RISCO,
  ROTULO_RISCO,
  quandoCurto,
  tamanho,
  type AnaliseArquivo,
  type DadosSeguranca,
  type ItemPc,
  type ResumoHistorico,
  type RevisaoPc,
  type Risco,
} from "./tipos";

const ROTULO_ACAO: Record<string, string> = {
  desativar_inicializacao: "Desativar da inicialização",
  reativar_inicializacao: "Reativar",
  desativar_tarefa: "Desativar tarefa",
  reativar_tarefa: "Reativar tarefa",
  abrir_seguranca_windows: "Abrir Segurança do Windows",
  abrir_windows_update: "Abrir Windows Update",
  analisar: "Analisar o arquivo",
};

type Resposta = { texto: string; ok: boolean; pendente?: boolean };

function useAcoes() {
  const avisar = useHud((s) => s.acoes.avisar);
  const chamar = (url: string, json: Record<string, unknown>) =>
    api<Resposta>(url, { method: "POST", json })
      .then((r) => avisar(r.texto, r.pendente ? "info" : r.ok ? "sucesso" : "erro"))
      .catch((e) => avisar(e.message, "erro"));
  return { chamar, avisar };
}

export default function HologramaSeguranca({ dados, largura = 480 }: { dados: DadosSeguranca; largura?: number }) {
  const [escolhida, setEscolhida] = useState<AnaliseArquivo | RevisaoPc | null>(null);
  const avisar = useHud((s) => s.acoes.avisar);
  const atual = dados?.atual;
  useEffect(() => setEscolhida(null), [atual]); // um relatório novo do servidor tem a preferência

  const abrirHistorico = (id: string) =>
    api<AnaliseArquivo | RevisaoPc>(`/api/seguranca/analise/${encodeURIComponent(id)}`)
      .then(setEscolhida)
      .catch((e) => avisar(e.message, "erro"));

  const mostrado = escolhida ?? atual;
  return (
    <div style={{ width: largura }} className="max-w-full">
      <div className="max-h-[520px] overflow-y-auto rolagem pr-1 -mr-1">
        {!mostrado && <Inicio />}
        {mostrado?.tipo === "carregando" && <p className="text-[14px] text-[var(--luz)] pulsando">{mostrado.texto}</p>}
        {mostrado?.tipo === "arquivo" && <RelatorioArquivo r={mostrado} virustotal={dados?.virustotal} />}
        {mostrado?.tipo === "pc" && <RelatorioPc r={mostrado} />}
      </div>
      <Historico itens={dados?.historico ?? []} aoEscolher={abrirHistorico} ativo={mostrado && "id" in mostrado ? mostrado.id : undefined} />
      <Comandos />
    </div>
  );
}

function Selo({ risco }: { risco: Risco }) {
  return (
    <span className={`shrink-0 rounded border px-2 py-0.5 text-[11px] uppercase tracking-[0.14em] ${COR_RISCO[risco]} ${BORDA_RISCO[risco]}`}>
      {ROTULO_RISCO[risco]}
    </span>
  );
}

function Ponto({ risco }: { risco: Risco }) {
  const cor = { alto: "bg-coral", medio: "bg-ambar", baixo: "bg-menta", ok: "bg-aco/60" }[risco];
  return <span aria-hidden="true" className={`mt-1.5 size-2 shrink-0 rounded-full ${cor}`} />;
}

function Evidencias({ itens }: { itens: string[] }) {
  if (!itens.length) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {itens.map((e, i) => (
        <li key={i} className="break-all rounded bg-tinta-funda/60 px-1.5 py-0.5 font-mono text-[11px] leading-snug text-gelo/75">
          {e}
        </li>
      ))}
    </ul>
  );
}

function Titulo({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-3 mb-1 text-[11px] uppercase tracking-[0.18em] text-aco">{children}</h3>;
}

function Inicio() {
  return (
    <p className="text-sm text-aco leading-snug">
      Peça “analisa o arquivo setup.exe”, “o último download é seguro?” ou “revisa a segurança do PC”. Nada é executado: só leio os arquivos e as
      configurações do Windows.
    </p>
  );
}

// -- análise de arquivo -------------------------------------------------------------------------------
function RelatorioArquivo({ r, virustotal }: { r: AnaliseArquivo; virustotal?: boolean }) {
  const { chamar } = useAcoes();
  const motivos = r.motivos.filter((m) => m.peso !== 0 || m.evidencias.length);
  const pe = r.detalhes.pe;
  const asar = r.detalhes.asar;
  const strings = Object.entries(r.strings).filter(([, v]) => v.length) as [string, string[]][];
  const vt = r.virustotal;
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[15px] text-gelo" title={r.caminho}>
            {r.arquivo}
          </p>
          <p className="text-xs text-aco">
            {r.descricao} · {tamanho(r.tamanho)} · {quandoCurto(r.quando)}
          </p>
        </div>
        <Selo risco={r.risco} />
      </div>
      <p className="mt-2 text-[14px] leading-relaxed text-gelo/90">{r.veredito}</p>
      <p className="mt-1 text-xs text-aco">
        Assinatura digital: <span className={r.assinatura.status === "Valid" ? "text-menta" : r.assinatura.status === "HashMismatch" ? "text-coral" : "text-gelo/80"}>{r.assinatura.texto}</span>
        {r.assinatura.assinante ? ` · ${r.assinatura.assinante}` : ""}
      </p>
      {vt ? (
        <p className="mt-1 text-xs text-aco">
          VirusTotal:{" "}
          {vt.conhecido ? (
            <span className={vt.maliciosos ? "text-coral" : "text-menta"}>
              {vt.maliciosos}/{vt.total} detecções{vt.rotulo ? ` (${vt.rotulo})` : ""}
            </span>
          ) : (
            "arquivo desconhecido"
          )}
        </p>
      ) : (
        virustotal &&
        r.id && (
          <button type="button" data-clicavel onClick={() => chamar("/api/seguranca/virustotal", { id: r.id })} className="mt-1 text-xs text-[var(--luz)] hover:text-gelo">
            Consultar o hash no VirusTotal (só o hash sai do PC)
          </button>
        )
      )}

      {motivos.length > 0 && (
        <>
          <Titulo>O que eu vi</Titulo>
          <ul className="space-y-1">
            {motivos.map((m) => (
              <li key={m.id}>
                <details className="group">
                  <summary className="flex cursor-pointer list-none items-start gap-2 text-[13px] leading-snug text-gelo/90 hover:text-gelo">
                    <Ponto risco={m.peso >= 4 ? "alto" : m.peso >= 2 ? "medio" : m.peso > 0 ? "baixo" : "ok"} />
                    <span className="flex-1">{m.texto}</span>
                    {m.evidencias.length > 0 && <span className="shrink-0 text-[11px] text-aco group-open:hidden">evidências</span>}
                  </summary>
                  <div className="pl-4">
                    <Evidencias itens={m.evidencias} />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </>
      )}

      {r.sugestoes.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-[var(--luz)]/90">
          {r.sugestoes.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] uppercase tracking-[0.18em] text-aco hover:text-gelo">Detalhes técnicos</summary>
        <dl className="mt-1 grid grid-cols-[96px_1fr] gap-x-2 gap-y-0.5 text-xs">
          <dt className="text-aco">SHA-256</dt>
          <dd className="break-all font-mono text-gelo/80 select-all">{r.sha256}</dd>
          <dt className="text-aco">Caminho</dt>
          <dd className="break-all text-gelo/80">{r.caminho}</dd>
          {pe && (
            <>
              <dt className="text-aco">Programa</dt>
              <dd className="text-gelo/80">
                {pe.tipo}, {pe.arquitetura}, {pe.subsistema}
                {pe.dotnet ? ", .NET" : ""}
              </dd>
              <dt className="text-aco">Compilado</dt>
              <dd className="text-gelo/80">{pe.compilado_em ?? "sem data"}</dd>
              <dt className="text-aco">Importa</dt>
              <dd className="text-gelo/80">
                {pe.total_funcoes} funções de {pe.dlls.length} DLLs{pe.dlls.length ? `: ${pe.dlls.slice(0, 8).join(", ")}${pe.dlls.length > 8 ? "…" : ""}` : ""}
              </dd>
              {pe.sobra_bytes > 0 && (
                <>
                  <dt className="text-aco">Dados extras</dt>
                  <dd className="text-gelo/80">{tamanho(pe.sobra_bytes)} depois das seções (comum em instaladores)</dd>
                </>
              )}
            </>
          )}
        </dl>
        {pe && pe.secoes.length > 0 && (
          <table className="mt-2 w-full text-xs">
            <thead>
              <tr className="text-left text-aco">
                <th className="font-normal">Seção</th>
                <th className="font-normal">Tamanho</th>
                <th className="font-normal">Entropia</th>
                <th className="font-normal">Permissões</th>
              </tr>
            </thead>
            <tbody>
              {pe.secoes.map((s, i) => (
                <tr key={i} className="text-gelo/80">
                  <td className="font-mono">{s.nome || "?"}</td>
                  <td>{tamanho(s.tamanho_bruto)}</td>
                  <td className={s.entropia >= 7.2 ? "text-ambar" : undefined}>{s.entropia.toFixed(2)}</td>
                  <td>{[s.executavel && "executa", s.gravavel && "grava"].filter(Boolean).join(", ") || "leitura"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {Object.keys(r.capacidades).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {Object.entries(r.capacidades).map(([chave, funcoes]) => (
              <span key={chave} title={funcoes.join(", ")} className="rounded border border-aco/40 px-1.5 py-0.5 text-[11px] text-gelo/80">
                {r.capacidades_rotulos[chave] ?? chave}
              </span>
            ))}
          </div>
        )}
        {asar && !asar.erro && (
          <p className="mt-2 text-xs text-gelo/80">
            App Electron{asar.nome ? ` “${asar.nome}”` : ""}
            {asar.versao ? ` ${asar.versao}` : ""}: {asar.arquivos} arquivos no pacote
            {asar.principal ? `, começa por ${asar.principal}` : ""}
            {asar.preload?.length ? `, preload: ${asar.preload.join(", ")}` : ""}.
          </p>
        )}
        {strings.map(([tipo, lista]) => (
          <details key={tipo} className="mt-1">
            <summary className="cursor-pointer text-xs text-aco hover:text-gelo">
              {{ urls: "Endereços (URLs)", ips: "IPs", caminhos: "Caminhos", registro: "Chaves de registro" }[tipo] ?? tipo} ({lista.length})
            </summary>
            <Evidencias itens={lista} />
          </details>
        ))}
        <ul className="mt-2 space-y-0.5 text-[11px] leading-snug text-aco">
          {r.limites.map((l, i) => (
            <li key={i}>• {l}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

// -- revisão do PC ------------------------------------------------------------------------------------
function RelatorioPc({ r }: { r: RevisaoPc }) {
  const categorias = Array.from(new Set(r.itens.map((i) => i.categoria)));
  const [soAtencao, setSoAtencao] = useState(true);
  const visiveis = (lista: ItemPc[]) => (soAtencao ? lista.filter((i) => i.risco === "alto" || i.risco === "medio") : lista);
  const temAtencao = r.itens.some((i) => i.risco === "alto" || i.risco === "medio");
  const mostrarTodos = !temAtencao || !soAtencao;
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[15px] text-gelo">Revisão de segurança do PC</p>
          <p className="text-xs text-aco">{quandoCurto(r.quando)}</p>
        </div>
        <Selo risco={r.risco} />
      </div>
      <div className="mt-2 flex gap-3 text-xs">
        {(["alto", "medio", "baixo", "ok"] as Risco[]).map((n) => (
          <span key={n} className={COR_RISCO[n]}>
            <span className="numeral text-lg">{r.contagem[n] ?? 0}</span> {ROTULO_RISCO[n].toLowerCase()}
          </span>
        ))}
      </div>
      <p className="mt-2 text-[14px] leading-relaxed text-gelo/90">{r.veredito}</p>
      {temAtencao && (
        <button type="button" data-clicavel onClick={() => setSoAtencao((v) => !v)} className="mt-1 text-xs text-[var(--luz)] hover:text-gelo">
          {soAtencao ? "Mostrar tudo o que foi revisado" : "Mostrar só o que merece atenção"}
        </button>
      )}
      {categorias.map((cat) => {
        const itens = mostrarTodos ? r.itens.filter((i) => i.categoria === cat) : visiveis(r.itens.filter((i) => i.categoria === cat));
        if (!itens.length) return null;
        return (
          <section key={cat}>
            <Titulo>{CATEGORIAS[cat] ?? cat}</Titulo>
            <ul className="space-y-1">
              {itens.map((item) => (
                <ItemRevisao key={item.id} item={item} />
              ))}
            </ul>
          </section>
        );
      })}
      {r.erros.length > 0 && (
        <details className="mt-3 text-xs text-aco">
          <summary className="cursor-pointer hover:text-gelo">O que não consegui olhar ({r.erros.length})</summary>
          <Evidencias itens={r.erros} />
        </details>
      )}
    </div>
  );
}

function ItemRevisao({ item }: { item: ItemPc }) {
  const { chamar } = useAcoes();
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const acao = item.acao;
  const executar = () => {
    if (!acao) return;
    if (acao.acao === "analisar") chamar("/api/seguranca/analisar", { caminho: acao.caminho });
    else chamar("/api/seguranca/corrigir", acao);
  };
  return (
    <li className={`rounded border px-2 py-1.5 ${item.risco === "alto" ? "border-coral/40" : item.risco === "medio" ? "border-ambar/30" : "border-aco/20"}`}>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-start gap-2 text-[13px] leading-snug text-gelo/90 hover:text-gelo">
          <Ponto risco={item.risco} />
          <span className="flex-1">{item.titulo}</span>
          <span className={`shrink-0 text-[11px] ${COR_RISCO[item.risco]}`}>{ROTULO_RISCO[item.risco]}</span>
        </summary>
        <div className="mt-1 pl-4 text-xs">
          {item.detalhe && <p className="text-gelo/80 leading-snug">{item.detalhe}</p>}
          {item.sugestao && <p className="mt-1 text-[var(--luz)]/90 leading-snug">{item.sugestao}</p>}
          <Evidencias itens={item.evidencias} />
          {acao && noPc && ROTULO_ACAO[acao.acao] && (
            <button type="button" data-clicavel onClick={executar} className="mt-1.5 rounded border border-[var(--luz)]/50 px-2 py-0.5 text-[var(--luz)] hover:text-gelo">
              {ROTULO_ACAO[acao.acao]}
            </button>
          )}
        </div>
      </details>
    </li>
  );
}

// -- histórico e comandos -----------------------------------------------------------------------------
function Historico({ itens, aoEscolher, ativo }: { itens: ResumoHistorico[]; aoEscolher: (id: string) => void; ativo?: string }) {
  if (!itens.length) return null;
  return (
    <details className="mt-3 border-t border-aco/20 pt-2">
      <summary className="cursor-pointer text-[11px] uppercase tracking-[0.18em] text-aco hover:text-gelo">Análises anteriores ({itens.length})</summary>
      <ul className="mt-1 max-h-[160px] overflow-y-auto rolagem space-y-0.5">
        {itens.map((h) => (
          <li key={h.id}>
            <button
              type="button"
              data-clicavel
              onClick={() => aoEscolher(h.id)}
              className={`flex w-full items-start gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-[rgb(var(--luz-rgb)/0.06)] ${ativo === h.id ? "bg-[rgb(var(--luz-rgb)/0.08)]" : ""}`}
            >
              <Ponto risco={h.risco} />
              <span className="min-w-0 flex-1 truncate text-gelo/85">{h.titulo}</span>
              <span className="shrink-0 text-aco">{quandoCurto(h.quando)}</span>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Comandos() {
  const { chamar } = useAcoes();
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const [caminho, setCaminho] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const rodar = (p: Promise<unknown>) => {
    setOcupado(true);
    p.finally(() => setOcupado(false));
  };
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-aco/20 pt-2">
      <button
        type="button"
        data-clicavel
        disabled={ocupado}
        onClick={() => rodar(chamar("/api/seguranca/revisar", { parte: "tudo" }))}
        className="inline-flex items-center gap-1.5 text-sm text-[var(--luz)] hover:text-gelo disabled:opacity-40"
      >
        <Icone.Repetir tamanho={14} className={ocupado ? "girando" : undefined} /> Revisar o PC
      </button>
      {noPc && (
        <form
          className="flex min-w-[200px] flex-1 items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const alvo = caminho.trim();
            if (!alvo || ocupado) return;
            rodar(chamar("/api/seguranca/analisar", { caminho: alvo }).then(() => setCaminho("")));
          }}
        >
          <input
            value={caminho}
            onChange={(e) => setCaminho(e.target.value)}
            maxLength={1000}
            placeholder="Analisar arquivo (nome ou caminho)…"
            aria-label="Arquivo para analisar"
            className="min-w-0 flex-1 border-b border-aco/40 bg-transparent py-1 text-sm text-gelo outline-none placeholder:text-aco/70 focus:border-[var(--luz)]"
          />
          <button type="submit" data-clicavel disabled={ocupado} aria-label="Analisar" className="p-1 text-[var(--luz)] hover:text-gelo disabled:opacity-40">
            <Icone.Enviar tamanho={16} />
          </button>
        </form>
      )}
    </div>
  );
}
