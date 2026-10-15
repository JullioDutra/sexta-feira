// Ajustes → Protocolo Sentinela: armar sozinho quando você sai do PC e depois de quantos minutos.
import { useHud } from "../../lib/store";
import { Chave } from "../../desktop/Ajustes";

type Mudar = (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown>;
const OPCOES = [3, 5, 10, 15, 30];

export default function AjustesSentinela({ mudar }: { mudar: Mudar }) {
  const prefs = useHud((s) => s.prefs as Record<string, unknown> | null);
  const auto = Boolean(prefs?.sentinela_auto);
  const minutos = Number(prefs?.sentinela_minutos ?? 5);
  return (
    <div>
      <p className="text-xs text-aco leading-snug">
        Diga “ativa o protocolo sentinela” ao sair: bloqueio o PC e vigio pela câmera (a luz dela pisca a cada ~8 s). Quem mexer vira foto, guardada só
        neste computador, e você recebe um aviso no celular. Quando eu vejo seu rosto, desarmo. “Desativa o sentinela” confere seu rosto.
      </p>
      <Chave
        ligado={auto}
        aoMudar={(v) => mudar({ sentinela_auto: v }, v ? "Sentinela automático ligado." : "Sentinela automático desligado.")}
        rotulo="Armar sozinho quando eu sair"
        descricao="Sem teclado e mouse pelo tempo abaixo e sem o seu rosto na câmera em duas olhadas seguidas."
      />
      <label className="flex items-center justify-between gap-4 py-2">
        <span className="text-[15px] text-gelo">Minutos sem uso</span>
        <select
          value={OPCOES.includes(minutos) ? minutos : 5}
          onChange={(e) => mudar({ sentinela_minutos: Number(e.target.value) }, "Tempo do Sentinela salvo.")}
          className="rounded border border-aco/40 bg-tinta-funda px-2 py-1 text-sm text-gelo"
        >
          {OPCOES.map((m) => (
            <option key={m} value={m}>
              {m} min
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
