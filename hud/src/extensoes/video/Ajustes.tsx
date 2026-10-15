// Ajustes → Vídeos: pasta dos vídeos, qualidade padrão e o que falta instalar (ffmpeg, Node.js, HyperFrames).
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";

interface ItemDiagnostico {
  nome: string;
  ok: boolean;
  detalhe: string;
  dica: string;
}

const QUALIDADES = [
  { valor: "alta", rotulo: "Alta (arquivos maiores, mais lento)" },
  { valor: "media", rotulo: "Média" },
  { valor: "leve", rotulo: "Leve (rápido, arquivos menores)" },
];

export default function AjustesVideos({ mudar }: { mudar: (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown> }) {
  const prefs = useHud((s) => s.prefs as Record<string, unknown> | null);
  const [pasta, setPasta] = useState(String(prefs?.videos_pasta ?? ""));
  const [itens, setItens] = useState<ItemDiagnostico[] | null>(null);
  const [conferindo, setConferindo] = useState(false);
  const qualidade = String(prefs?.videos_qualidade ?? "media");

  useEffect(() => setPasta(String(prefs?.videos_pasta ?? "")), [prefs?.videos_pasta]);
  const conferir = () => {
    setConferindo(true);
    api<ItemDiagnostico[]>("/api/videos/diagnostico")
      .then(setItens)
      .catch(() => setItens(null))
      .finally(() => setConferindo(false));
  };
  useEffect(conferir, []);

  return (
    <div className="space-y-3">
      <p className="text-xs text-aco leading-snug">
        Edita seus vídeos com o FFmpeg (“corta o vídeo X do 0:30 ao 1:15”, “comprime para o WhatsApp”, “coloca legendas”) e cria vídeos animados com o
        HyperFrames (“cria um vídeo de 15 segundos anunciando meu canal”). O resultado é sempre um arquivo novo na subpasta Sexta-Feira.
      </p>
      <form
        className="flex items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          mudar({ videos_pasta: pasta.trim() }, "Pasta de vídeos salva.").then(conferir);
        }}
      >
        <label className="flex-1">
          <span className="text-xs text-aco">Pasta dos vídeos (vazio = Vídeos do Windows)</span>
          <input
            value={pasta}
            onChange={(e) => setPasta(e.target.value)}
            placeholder="C:\Users\voce\Videos"
            className="mt-0.5 block w-full bg-transparent border-b border-aco/50 py-1 text-gelo outline-none placeholder:text-aco/60 focus:border-[var(--luz)]"
          />
        </label>
        <button type="submit" className="text-sm text-[var(--luz)] hover:text-gelo pb-1">
          Salvar
        </button>
      </form>
      <label className="flex items-center justify-between py-1">
        <span className="text-[15px] text-gelo">Qualidade padrão</span>
        <select
          value={qualidade}
          onChange={(e) => mudar({ videos_qualidade: e.target.value }, "Qualidade salva.")}
          className="bg-tinta border border-aco/40 rounded px-2 py-1 text-gelo"
        >
          {QUALIDADES.map((q) => (
            <option key={q.valor} value={q.valor}>
              {q.rotulo}
            </option>
          ))}
        </select>
      </label>
      <div>
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-[0.18em] text-aco">Programas</span>
          <button type="button" onClick={conferir} disabled={conferindo} className="text-xs text-[var(--luz)] hover:text-gelo disabled:opacity-40">
            {conferindo ? "Conferindo…" : "Conferir de novo"}
          </button>
        </div>
        <ul className="mt-1 space-y-1">
          {itens?.map((i) => (
            <li key={i.nome} className="text-sm leading-snug">
              <span className={i.ok ? "text-[var(--luz)]" : "text-coral"}>{i.ok ? "✓" : "✗"}</span>{" "}
              <span className="text-gelo">{i.nome.replace(/^Vídeos: /, "")}</span> <span className="text-xs text-aco">{i.detalhe}</span>
              {i.dica && <span className="block text-xs text-aco/90 pl-4">{i.dica}</span>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
