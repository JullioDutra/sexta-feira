// Holograma "Diagnóstico do traje": temperaturas, GPU, memória, rede, discos, atualizações, bateria e segurança,
// com os pontos de atenção no topo.
import { IconeNivel } from "./Inicializacao";
import type { Nivel, RelatorioTraje } from "./tipos";

const COR_NIVEL: Record<Nivel, string> = { ok: "text-menta", aviso: "text-ambar", falha: "text-coral" };
const BARRA_NIVEL: Record<Nivel, string> = { ok: "bg-[var(--luz)]", aviso: "bg-ambar", falha: "bg-coral" };

function nivelTemp(temp: number | null, limite: number): Nivel {
  if (temp == null) return "ok";
  return temp >= limite ? "falha" : temp >= limite - 10 ? "aviso" : "ok";
}

function num(v: number | null | undefined, sufixo = "", casas = 0): string {
  return v == null ? "—" : `${v.toFixed(casas)}${sufixo}`;
}

function Barra({ pct, nivel = "ok" }: { pct: number | null | undefined; nivel?: Nivel }) {
  return (
    <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-aco/20" aria-hidden="true">
      <div className={`h-full ${BARRA_NIVEL[nivel]}`} style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%`, transition: "width .4s" }} />
    </div>
  );
}

function Bloco({ rotulo, valor, detalhe, nivel = "ok", pct, dica }: { rotulo: string; valor: string; detalhe?: string; nivel?: Nivel; pct?: number | null; dica?: string }) {
  return (
    <div className="rounded border border-aco/25 bg-tinta-funda/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.2em] text-aco">{rotulo}</div>
      <div className={`numeral text-[26px] font-[300] leading-tight ${valor === "—" ? "text-aco" : nivel === "ok" ? "text-gelo" : COR_NIVEL[nivel]}`}>{valor}</div>
      {detalhe && <div className="truncate text-[11px] text-aco" title={detalhe}>{detalhe}</div>}
      {pct !== undefined && <Barra pct={pct} nivel={nivel} />}
      {dica && <div className="mt-1 text-[11px] leading-snug text-ambar/90">{dica}</div>}
    </div>
  );
}

function Titulo({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-1.5 mt-4 text-[11px] uppercase tracking-[0.24em] text-[var(--luz)]">{children}</h4>;
}

function dataCurta(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export default function HologramaTraje({ dados, largura = 500 }: { dados: RelatorioTraje; largura?: number }) {
  if (!dados || dados.carregando || !dados.cpu) {
    return (
      <div style={{ width: largura }} className="max-w-full py-6 text-center">
        <p className="pulsando text-[14px] text-[var(--luz)]">Varrendo os sistemas do traje…</p>
      </div>
    );
  }
  const { cpu, gpu, ram, rede, atualizacoes: atu, bateria, seguranca } = dados;
  const vramPct = gpu.vram_total ? (100 * (gpu.vram_usada ?? 0)) / gpu.vram_total : null;
  const ping: Nivel = rede.ping_ms == null ? "falha" : rede.ping_ms > 150 ? "aviso" : "ok";
  return (
    <div style={{ width: largura }} className="max-w-full">
      <div className="max-h-[540px] overflow-y-auto rolagem pr-1 -mr-1">
        <div className="flex items-center gap-2">
          <IconeNivel nivel={dados.nivel} tamanho={18} />
          <span className={`text-[15px] ${COR_NIVEL[dados.nivel]}`}>
            {dados.nivel === "ok" ? "Todos os sistemas nominais" : `${dados.atencao.length} ponto${dados.atencao.length > 1 ? "s" : ""} de atenção`}
          </span>
          <span className="ml-auto text-[11px] text-aco">{dataCurta(dados.quando)}</span>
        </div>
        {dados.atencao.length > 0 && (
          <ul className="mt-2 space-y-1">
            {dados.atencao.map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-[13px] text-gelo/90">
                <IconeNivel nivel={a.nivel} tamanho={14} />
                <span className="first-letter:uppercase">{a.texto}</span>
              </li>
            ))}
          </ul>
        )}

        <Titulo>Núcleo</Titulo>
        <div className="grid grid-cols-2 gap-2">
          <Bloco
            rotulo="CPU"
            valor={num(cpu.temp, "°")}
            nivel={nivelTemp(cpu.temp, cpu.limite)}
            detalhe={`uso ${num(cpu.uso, "%")}${cpu.fonte ? ` · ${cpu.fonte}` : ""}`}
            pct={cpu.uso}
            dica={cpu.temp == null ? cpu.erro : undefined}
          />
          <Bloco
            rotulo={gpu.nome ? `GPU · ${gpu.nome.replace(/^NVIDIA (GeForce )?/i, "")}` : "GPU"}
            valor={num(gpu.temp, "°")}
            nivel={nivelTemp(gpu.temp, gpu.limite)}
            detalhe={`uso ${num(gpu.uso, "%")}${gpu.vram_total ? ` · VRAM ${num((gpu.vram_usada ?? 0) / 1024, "", 1)}/${num(gpu.vram_total / 1024, " GB", 1)}` : ""}`}
            pct={vramPct ?? gpu.uso}
            dica={gpu.temp == null && gpu.erro ? gpu.erro : undefined}
          />
          <Bloco rotulo="Memória" valor={num(ram.pct, "%")} detalhe={ram.total ? `${num(ram.usada, "", 1)} de ${num(ram.total, " GB", 1)}` : undefined} pct={ram.pct} nivel={(ram.pct ?? 0) > 90 ? "aviso" : "ok"} />
          <Bloco rotulo="Rede" valor={rede.ping_ms == null ? "offline" : `${rede.ping_ms} ms`} nivel={ping} detalhe={rede.ssid ? `Wi-Fi ${rede.ssid}` : "cabo ou sem Wi-Fi"} />
        </div>

        <Titulo>Armazenamento</Titulo>
        <ul className="space-y-2">
          {dados.discos.map((d) => {
            const livre = 100 - d.pct;
            const nivel: Nivel = livre < 10 ? "falha" : livre < 20 ? "aviso" : "ok";
            return (
              <li key={d.unidade}>
                <div className="flex items-baseline justify-between text-[13px]">
                  <span className="text-gelo">
                    {d.unidade}
                    {d.sistema && <span className="ml-1.5 text-[10px] uppercase tracking-widest text-aco">sistema</span>}
                  </span>
                  <span className={nivel === "ok" ? "text-aco" : COR_NIVEL[nivel]}>
                    {d.livre_gb} GB livres de {d.total_gb} GB
                  </span>
                </div>
                <Barra pct={d.pct} nivel={nivel} />
              </li>
            );
          })}
        </ul>
        {dados.saude_discos.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {dados.saude_discos.map((d, i) => (
              <li key={i} className="flex items-center gap-1.5 text-[12px] text-aco">
                <IconeNivel nivel={d.ok ? "ok" : "falha"} tamanho={12} />
                {d.nome}
                {d.tipo ? ` (${d.tipo})` : ""}: <span className={d.ok ? "text-gelo/80" : "text-coral"}>{d.saude}</span>
              </li>
            ))}
          </ul>
        )}

        <Titulo>Manutenção</Titulo>
        <div className="grid grid-cols-2 gap-2">
          <Bloco
            rotulo="Atualizações"
            valor={atu.windows == null ? (atu.verificando ? "…" : "—") : String(atu.windows)}
            nivel={(atu.windows ?? 0) > 0 ? "aviso" : "ok"}
            detalhe={
              atu.verificando && atu.windows == null
                ? "verificando o Windows Update…"
                : `Windows${atu.winget != null ? ` · ${atu.winget} no winget` : ""}${atu.verificado ? ` · ${dataCurta(atu.verificado)}` : ""}`
            }
            dica={atu.erro || undefined}
          />
          <Bloco
            rotulo="Bateria"
            valor={bateria.presente ? num(bateria.saude_pct, "%") : bateria.presente === false ? "sem bateria" : bateria.verificando ? "…" : "—"}
            nivel={bateria.presente && (bateria.saude_pct ?? 100) < 70 ? "aviso" : "ok"}
            detalhe={
              bateria.presente
                ? `saúde: ${Math.round((bateria.atual_mwh ?? 0) / 1000)} de ${Math.round((bateria.projetada_mwh ?? 0) / 1000)} Wh`
                : bateria.verificando
                  ? "lendo o relatório do powercfg…"
                  : "computador de mesa"
            }
            pct={bateria.presente ? bateria.saude_pct : undefined}
          />
        </div>

        <Titulo>Segurança</Titulo>
        {seguranca ? (
          <div className="rounded border border-aco/25 bg-tinta-funda/40 px-3 py-2 text-[13px]">
            <div className="flex flex-wrap gap-x-5 gap-y-1">
              <span className="flex items-center gap-1.5">
                <IconeNivel nivel={seguranca.defender === "desligado" ? "falha" : seguranca.defender === "não verificado" ? "aviso" : "ok"} tamanho={13} />
                Defender: <span className="text-gelo">{seguranca.defender}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <IconeNivel nivel={seguranca.firewall === "desligado" ? "falha" : seguranca.firewall === "não verificado" ? "aviso" : "ok"} tamanho={13} />
                Firewall: <span className="text-gelo">{seguranca.firewall}</span>
              </span>
            </div>
            <div className="mt-1 text-[11px] text-aco">
              {seguranca.ultima_revisao ? `Última revisão: ${dataCurta(seguranca.ultima_revisao)}${seguranca.risco ? ` · risco ${seguranca.risco === "medio" ? "médio" : seguranca.risco}` : ""}` : seguranca.dica}
            </div>
          </div>
        ) : (
          <p className="text-[12px] text-aco">Extensão de segurança indisponível.</p>
        )}
      </div>
      <p className="mt-3 border-t border-aco/20 pt-2 text-[11px] text-aco">“status do traje” · “liga o overlay” · “liga o modo jogo automático”</p>
    </div>
  );
}
