// Ajustes → Segurança: revisão automática semanal e consultas ao VirusTotal (só o hash, sempre com confirmação).
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Chave } from "../../desktop/Ajustes";

interface Estado {
  windows: boolean;
  pefile: boolean;
  virustotal_configurado: boolean;
  revisao_semanal: boolean;
  ultima_automatica: string | null;
  analises: number;
}

type Mudar = (valores: Record<string, unknown>, mensagem?: string) => Promise<unknown>;

export default function AjustesSeguranca({ mudar }: { mudar: Mudar }) {
  const prefs = useHud((s) => s.prefs as Record<string, unknown> | null);
  const [estado, setEstado] = useState<Estado | null>(null);
  useEffect(() => {
    api<Estado>("/api/seguranca/estado")
      .then(setEstado)
      .catch(() => setEstado(null));
  }, []);
  const semanal = Boolean(prefs?.seguranca_revisao_semanal);
  const virustotal = prefs?.seguranca_virustotal !== false;
  return (
    <div>
      <p className="text-xs text-aco leading-snug">
        Diga “analisa o arquivo setup.exe”, “esse programa é seguro?”, “revisa a segurança do PC”, “quem está usando a internet?” ou “o que inicia com
        o Windows?”. A análise é estática: nenhum arquivo analisado é executado.
      </p>
      <Chave
        ligado={semanal}
        aoMudar={(v) => mudar({ seguranca_revisao_semanal: v }, v ? "Revisão semanal ligada." : "Revisão semanal desligada.")}
        rotulo="Revisão automática semanal"
        descricao={
          estado?.ultima_automatica
            ? `Última: ${new Date(estado.ultima_automatica).toLocaleDateString("pt-BR")}. Só avisa se encontrar algo importante.`
            : "Uma vez por semana, em segundo plano. Só avisa se encontrar algo importante."
        }
      />
      <Chave
        ligado={virustotal}
        aoMudar={(v) => mudar({ seguranca_virustotal: v }, v ? "VirusTotal liberado." : "VirusTotal desligado.")}
        rotulo="Consultar o VirusTotal"
        descricao={
          estado && !estado.virustotal_configurado
            ? "Sem chave: crie uma grátis em virustotal.com e coloque VIRUSTOTAL_API_KEY no arquivo .env."
            : "Só o hash (a impressão digital) do arquivo sai do PC, nunca o arquivo, e sempre depois do seu “sim”."
        }
      />
      {estado && (
        <p className="mt-1 text-xs text-aco leading-snug">
          {estado.analises} análise{estado.analises === 1 ? "" : "s"} no histórico ·{" "}
          {estado.pefile ? "pefile instalado" : "sem pefile (pip install pefile para análises mais completas)"}
          {estado.windows ? "" : " · revisão do PC só no Windows"}
        </p>
      )}
    </div>
  );
}
