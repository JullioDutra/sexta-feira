interface Dados {
  cpu: number;
  nucleos: number;
  ram: { usado: number; total: number; pct: number };
  disco: { usado: number; total: number; pct: number } | null;
  bateria: { pct: number; carregando: boolean } | null;
  rede: { desce_kbps: number; sobe_kbps: number };
  ligado_ha: string;
}

function Arco({ raio, pct, espessura = 3 }: { raio: number; pct: number; espessura?: number }) {
  const c = 2 * Math.PI * raio;
  const fracao = Math.max(0, Math.min(1, pct / 100)) * 0.75;
  return (
    <g transform="rotate(135 90 90)">
      <circle cx="90" cy="90" r={raio} fill="none" stroke="rgb(95 124 147 / 0.25)" strokeWidth={espessura} strokeDasharray={`${c * 0.75} ${c}`} />
      <circle
        cx="90"
        cy="90"
        r={raio}
        fill="none"
        stroke={pct > 85 ? "var(--color-coral)" : "var(--luz)"}
        strokeWidth={espessura}
        strokeLinecap="round"
        strokeDasharray={`${c * fracao} ${c}`}
        style={{ transition: "stroke-dasharray 0.8s ease", filter: "drop-shadow(0 0 4px rgb(var(--luz-rgb) / 0.7))" }}
      />
    </g>
  );
}

function velocidade(kbps: number): string {
  return kbps >= 1024 ? `${(kbps / 1024).toFixed(1)} MB/s` : `${kbps} kB/s`;
}

export default function Sistema({ dados }: { dados: Dados }) {
  if (!dados?.ram) return <p className="text-sm text-aco w-[340px]">Lendo o sistema…</p>;
  const linhas = [
    { nome: "Processador", valor: `${Math.round(dados.cpu)}%`, detalhe: `${dados.nucleos} núcleos` },
    { nome: "Memória", valor: `${Math.round(dados.ram.pct)}%`, detalhe: `${dados.ram.usado} de ${dados.ram.total} GB` },
    ...(dados.disco ? [{ nome: "Disco", valor: `${Math.round(dados.disco.pct)}%`, detalhe: `${dados.disco.usado} de ${dados.disco.total} GB` }] : []),
  ];
  return (
    <div className="w-[360px] flex gap-4 items-center">
      <svg width="180" height="180" viewBox="0 0 180 180" role="img" aria-label="Uso de processador, memória e disco">
        <Arco raio={80} pct={dados.cpu} />
        <Arco raio={66} pct={dados.ram.pct} />
        {dados.disco && <Arco raio={52} pct={dados.disco.pct} />}
        <text x="90" y="96" textAnchor="middle" className="numeral" fontSize="40" fontWeight="250" fill="var(--color-gelo)">
          {Math.round(dados.cpu)}
        </text>
        <text x="90" y="116" textAnchor="middle" fontSize="11" fill="var(--color-aco)">
          % processador
        </text>
      </svg>
      <dl className="flex-1 space-y-2.5 text-sm">
        {linhas.map((l) => (
          <div key={l.nome}>
            <dt className="text-aco text-xs">{l.nome}</dt>
            <dd className="flex items-baseline gap-2">
              <span className="numeral text-2xl text-gelo">{l.valor}</span>
              <span className="text-xs text-aco">{l.detalhe}</span>
            </dd>
          </div>
        ))}
        <div className="text-xs text-aco leading-relaxed pt-1">
          <p>Rede: baixando {velocidade(dados.rede.desce_kbps)}, enviando {velocidade(dados.rede.sobe_kbps)}</p>
          {dados.bateria && (
            <p>
              Bateria {dados.bateria.pct}%{dados.bateria.carregando ? ", carregando" : ""}
            </p>
          )}
          <p>Ligado há {dados.ligado_ha}</p>
        </div>
      </dl>
    </div>
  );
}
