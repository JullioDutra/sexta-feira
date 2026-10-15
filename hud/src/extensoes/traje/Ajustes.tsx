// Ajustes → Traje: sequência de inicialização, alertas proativos (limites de temperatura) e modo jogo/overlay.
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Chave } from "../../desktop/Ajustes";

interface Estado {
  windows: boolean;
  presentmon: string;
  nvidia_smi: boolean;
  edge: boolean;
  temperatura_fonte: string;
  temperatura_erro: string;
  jogo: string;
  overlay: boolean;
}

type Mudar = (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown>;
const campo = "bg-transparent border-b border-aco/50 py-1 text-gelo outline-none focus:border-[var(--luz)]";

export default function AjustesTraje({ mudar }: { mudar: Mudar }) {
  const prefs = useHud((s) => s.prefs as Record<string, unknown> | null);
  const [estado, setEstado] = useState<Estado | null>(null);
  const [cpu, setCpu] = useState(95);
  const [gpu, setGpu] = useState(90);
  const [jogos, setJogos] = useState("");

  useEffect(() => {
    api<Estado>("/api/traje/estado")
      .then(setEstado)
      .catch(() => setEstado(null));
  }, []);
  useEffect(() => {
    setCpu(Number(prefs?.alerta_cpu_temp ?? 95));
    setGpu(Number(prefs?.alerta_gpu_temp ?? 90));
    setJogos(((prefs?.jogos as string[] | undefined) ?? []).join(", "));
  }, [prefs?.alerta_cpu_temp, prefs?.alerta_gpu_temp, prefs?.jogos]);

  const liga = (chave: string, padrao = true) => (prefs?.[chave] ?? padrao) !== false;
  const chave = (nome: string, rotulo: string, descricao: string, ligado: string, desligado: string) => (
    <Chave ligado={liga(nome)} aoMudar={(v) => mudar({ [nome]: v }, v ? ligado : desligado)} rotulo={rotulo} descricao={descricao} />
  );
  const alertas = liga("alertas_proativos");
  const salvarLimites = () => {
    const c = Math.max(60, Math.min(110, Math.round(cpu || 95)));
    const g = Math.max(60, Math.min(110, Math.round(gpu || 90)));
    const lista = jogos
      .split(/[,;\n]/)
      .map((j) => j.trim())
      .filter(Boolean);
    mudar({ alerta_cpu_temp: c, alerta_gpu_temp: g, jogos: lista }, "Ajustes do traje salvos.");
  };

  return (
    <div>
      <p className="text-xs leading-snug text-aco">
        Diga “status do traje”, “liga o overlay”, “desliga o overlay” ou “liga o modo jogo automático”.
      </p>
      {chave("sequencia_inicial", "Sequência de inicialização", "Ao ligar, confere cada módulo com a animação “sistemas online”.", "Sequência de inicialização ligada.", "Sequência de inicialização desligada.")}
      {chave("alertas_proativos", "Alertas proativos", "Temperatura alta, chuva chegando e disco cheio: fala, mostra aqui e manda para o celular.", "Alertas ligados.", "Alertas desligados.")}
      {alertas && (
        <div className="ml-3 border-l border-aco/20 pl-3">
          {chave("alerta_temperatura", "Temperatura da CPU e da GPU", "Avisa depois de 5 minutos seguidos acima do limite.", "Alerta de temperatura ligado.", "Alerta de temperatura desligado.")}
          {chave("alerta_chuva", "Chuva chegando", "Quando a chuva está prevista para a próxima hora (precisa da cidade definida).", "Alerta de chuva ligado.", "Alerta de chuva desligado.")}
          {chave("alerta_disco", "Disco quase cheio", "Menos de 10% livre no disco do sistema, uma vez por dia.", "Alerta de disco ligado.", "Alerta de disco desligado.")}
        </div>
      )}
      {chave("modo_jogo_auto", "Modo jogo automático", "Quando um jogo abre: desempenho máximo e não perturbe; volta tudo ao fechar.", "Modo jogo automático ligado.", "Modo jogo automático desligado.")}
      {chave("overlay_jogo", "Overlay de jogo", "FPS, temperaturas e ping no canto do monitor do jogo (jogos em janela ou tela cheia sem bordas).", "Overlay ligado.", "Overlay desligado.")}
      <div className="mt-2 grid grid-cols-2 gap-3">
        <label className="text-xs text-aco">
          Limite da CPU (°C)
          <input type="number" min={60} max={110} value={cpu} onChange={(e) => setCpu(Number(e.target.value))} className={`block w-full ${campo}`} />
        </label>
        <label className="text-xs text-aco">
          Limite da GPU (°C)
          <input type="number" min={60} max={110} value={gpu} onChange={(e) => setGpu(Number(e.target.value))} className={`block w-full ${campo}`} />
        </label>
      </div>
      <label className="mt-3 block text-xs text-aco">
        Outros jogos (executáveis fora das pastas da Steam, Epic, Riot, Xbox e GOG)
        <input value={jogos} onChange={(e) => setJogos(e.target.value)} placeholder="javaw.exe, osu!.exe" className={`block w-full ${campo}`} />
      </label>
      <button type="button" onClick={salvarLimites} className="mt-3 rounded border border-[var(--luz)] px-3 py-1 text-sm text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.12)]">
        Salvar
      </button>
      {estado && (
        <ul className="mt-3 space-y-0.5 text-xs leading-snug text-aco">
          {!estado.windows && <li>Sensores, modo jogo e overlay só funcionam no Windows.</li>}
          {estado.windows && (
            <>
              <li>Temperatura: {estado.temperatura_fonte || estado.temperatura_erro || "ainda não lida"}</li>
              <li>GPU: {estado.nvidia_smi ? "nvidia-smi" : "contadores do Windows (temperatura pelo LibreHardwareMonitor)"}</li>
              <li>FPS: {estado.presentmon ? "PresentMon encontrado" : "instale o PresentMon em dados/ferramentas ou defina PRESENTMON no .env"}</li>
              {!estado.edge && <li className="text-ambar">Microsoft Edge não encontrado: o overlay precisa dele.</li>}
              {estado.jogo && <li className="text-gelo">Jogando agora: {estado.jogo}{estado.overlay ? " (overlay aberto)" : ""}</li>}
            </>
          )}
        </ul>
      )}
    </div>
  );
}
