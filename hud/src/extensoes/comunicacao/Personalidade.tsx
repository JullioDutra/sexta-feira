// Seção "Personalidade" em Ajustes: formal, amigável ou sarcástica (também dá para pedir por voz).
import { useHud } from "../../lib/store";
import type { Preferencias } from "../../lib/tipos";

type Personalidade = "formal" | "amigavel" | "sarcastica";

const OPCOES: { valor: Personalidade; rotulo: string; descricao: string }[] = [
  { valor: "formal", rotulo: "Formal", descricao: 'Cortês e precisa, sem piadas. Chama você de "senhor" (ou do tratamento que você escolheu).' },
  { valor: "amigavel", rotulo: "Amigável", descricao: "O jeito de sempre: confiante, calorosa e com um humor leve." },
  { valor: "sarcastica", rotulo: "Sarcástica", descricao: "Humor seco e provocações leves, no estilo dos filmes. Avisos e confirmações continuam sérios." },
];

export function AjustePersonalidade({ mudar }: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) {
  const atual = useHud((s) => (s.prefs as (Preferencias & { personalidade?: Personalidade }) | null)?.personalidade ?? "amigavel");
  const escolhida = OPCOES.find((o) => o.valor === atual) ?? OPCOES[1];
  return (
    <div>
      <label className="flex items-center justify-between py-2">
        <span className="text-[15px] text-gelo">Personalidade</span>
        <select
          value={escolhida.valor}
          onChange={(e) => mudar({ personalidade: e.target.value }, "Personalidade salva.")}
          className="bg-tinta border border-aco/40 rounded px-2 py-1 text-gelo"
        >
          {OPCOES.map((o) => (
            <option key={o.valor} value={o.valor}>
              {o.rotulo}
            </option>
          ))}
        </select>
      </label>
      <p className="text-xs text-aco leading-snug">{escolhida.descricao}</p>
      <p className="text-xs text-aco leading-snug mt-2">
        Por voz: "modo formal", "pode ser sarcástica", "qual sua personalidade?". Para traduzir: "modo tradutor para inglês", "traduz a tela" ou
        "traduz o que eu copiei para espanhol".
      </p>
    </div>
  );
}
