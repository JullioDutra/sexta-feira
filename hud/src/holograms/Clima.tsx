import { GlifoClima } from "./Glifos";

interface Dia {
  data: string;
  dia: string;
  max: number;
  min: number;
  chuva: number | null;
  descricao: string;
  icone: string;
}

interface Hora {
  hora: string;
  temp: number;
  chuva: number | null;
  icone: string;
  dia: boolean;
}

export interface DadosClima {
  local: string;
  atual: { temp: number; sensacao: number; umidade: number; vento: number; descricao: string; icone: string; dia: boolean };
  dias: Dia[];
  horas: Hora[];
  nascer_sol: string;
  por_sol: string;
  uv: number | null;
}

export default function Clima({ dados }: { dados: DadosClima }) {
  if (!dados?.atual) return <p className="text-aco text-sm">Sem dados de clima.</p>;
  const { atual, dias, horas } = dados;
  const minimo = Math.min(...dias.map((d) => d.min));
  const maximo = Math.max(...dias.map((d) => d.max));
  const faixa = Math.max(1, maximo - minimo);

  return (
    <div className="w-[400px]">
      <div className="flex items-center gap-4">
        <GlifoClima icone={atual.icone} dia={atual.dia} tamanho={68} className="text-[var(--luz)] shrink-0" strokeWidth={1.1} />
        <div className="numeral text-[104px] leading-[0.8] font-[200] text-gelo brilho">{atual.temp}°</div>
        <div className="text-sm leading-snug">
          <p className="text-gelo first-letter:uppercase">{atual.descricao}</p>
          <p className="text-aco mt-1">Sensação de {atual.sensacao}°</p>
          <p className="text-aco">Umidade {atual.umidade}%</p>
          <p className="text-aco">Vento {atual.vento} km/h</p>
        </div>
      </div>

      <ol className="mt-5 grid grid-cols-12 gap-0.5 text-center" aria-label="Próximas horas">
        {horas.slice(0, 12).map((h, i) => (
          <li key={i} className="flex flex-col items-center gap-1">
            <span className="text-[10px] text-aco">{h.hora}</span>
            <GlifoClima icone={h.icone} dia={h.dia} tamanho={15} className="text-gelo/80" />
            <span className="numeral text-[15px] text-gelo">{h.temp}°</span>
          </li>
        ))}
      </ol>

      <ol className="mt-5 space-y-1.5" aria-label="Próximos dias">
        {dias.map((d) => {
          const inicio = ((d.min - minimo) / faixa) * 100;
          const largura = Math.max(6, ((d.max - d.min) / faixa) * 100);
          return (
            <li key={d.data} className="grid grid-cols-[52px_22px_28px_1fr_28px_38px] items-center gap-2 text-sm">
              <span className="text-gelo/90 first-letter:uppercase">{d.dia}</span>
              <GlifoClima icone={d.icone} tamanho={16} className="text-gelo/70" />
              <span className="numeral text-right text-aco text-base">{d.min}°</span>
              <span className="relative h-[3px] rounded-full bg-aco/20">
                <span
                  className="absolute inset-y-0 rounded-full"
                  style={{
                    left: `${inicio}%`,
                    width: `${largura}%`,
                    background: "linear-gradient(90deg, #9fd3ff, var(--luz) 70%, var(--luz-quente))",
                    boxShadow: "0 0 8px rgb(var(--luz-rgb) / 0.6)",
                  }}
                />
              </span>
              <span className="numeral text-gelo text-base">{d.max}°</span>
              <span className={`text-xs text-right ${d.chuva && d.chuva >= 50 ? "text-[#9fd3ff]" : "text-aco"}`}>
                {d.chuva !== null ? `${d.chuva}%` : ""}
              </span>
            </li>
          );
        })}
      </ol>

      <p className="mt-4 text-xs text-aco">
        Sol nasce {dados.nascer_sol} e se põe {dados.por_sol}
        {dados.uv != null ? `, índice UV ${Math.round(dados.uv)}` : ""}
      </p>
    </div>
  );
}
