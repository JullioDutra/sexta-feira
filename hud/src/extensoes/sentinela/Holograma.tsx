// Holograma "Protocolo Sentinela": armado/desarmado, as fotos de quem mexeu no PC (miniaturas buscadas com
// a chave de acesso) e botões para apagar. Enquanto armado, a luz da webcam pisca: a câmera liga a cada ~8 s.
import { useState } from "react";
import { api, comToken } from "../../lib/api";
import { useHud } from "../../lib/store";
import { Icone } from "../../holograms/Glifos";
import { horaCurta, type DadosSentinela, type FotoSentinela } from "./tipos";

export default function HologramaSentinela({ dados, largura = 460 }: { dados: DadosSentinela; largura?: number }) {
  const noPc = useHud((s) => s.cliente?.tipo === "pc");
  const avisar = useHud((s) => s.acoes.avisar);
  const [fotos, setFotos] = useState<FotoSentinela[] | null>(null);
  const [aberta, setAberta] = useState<string | null>(null);
  const lista = fotos ?? dados?.fotos ?? [];
  const armado = Boolean(dados?.armado);

  const apagar = (nome: string) =>
    api<{ fotos: FotoSentinela[] }>(`/api/sentinela/fotos/${encodeURIComponent(nome)}`, { method: "DELETE" })
      .then((r) => {
        setFotos(r.fotos);
        if (aberta === nome) setAberta(null);
        avisar("Foto apagada.", "sucesso");
      })
      .catch((e) => avisar(e.message, "erro"));

  const alternar = () =>
    api<{ texto: string }>(armado ? "/api/sentinela/desarmar" : "/api/sentinela/armar", { method: "POST" })
      .then((r) => avisar(r.texto, "info"))
      .catch((e) => avisar(e.message, "erro"));

  return (
    <div style={{ width: largura }} className="max-w-full">
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className={`size-3 shrink-0 rounded-full ${armado ? "bg-coral pulsando shadow-[0_0_10px_rgb(255_110_90/0.7)]" : "bg-aco/60"}`}
        />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] text-gelo">{armado ? "Armado" : "Desarmado"}</p>
          <p className="text-xs text-aco leading-snug">
            {armado
              ? `Desde ${horaCurta(dados?.desde)}${dados?.motivo === "automatico" ? " (automático)" : ""} · a luz da câmera pisca enquanto vigio`
              : dados?.auto
                ? `Arma sozinho depois de ${dados.minutos} min sem ninguém na frente do PC`
                : "Diga “ativa o protocolo sentinela” antes de sair"}
          </p>
        </div>
        {noPc && (
          <button
            type="button"
            data-clicavel
            onClick={alternar}
            className="shrink-0 rounded border border-[var(--luz)]/50 px-2.5 py-1 text-xs text-[var(--luz)] hover:bg-[rgb(var(--luz-rgb)/0.1)]"
          >
            {armado ? "Desarmar" : "Armar"}
          </button>
        )}
      </div>
      {dados && !dados.cadastrado && (
        <p className="mt-2 text-xs text-ambar leading-snug">
          Seu rosto não está cadastrado: fotografo qualquer pessoa que mexer no PC. Cadastre em Ajustes para eu te reconhecer e desarmar sozinha.
        </p>
      )}

      <h3 className="mt-3 mb-1 text-[11px] uppercase tracking-[0.18em] text-aco">
        Capturas {lista.length > 0 && `(${lista.length})`}
      </h3>
      {lista.length === 0 ? (
        <p className="text-sm text-aco">Nenhuma captura. As fotos ficam só neste computador.</p>
      ) : (
        <ul className="grid max-h-[340px] grid-cols-3 gap-2 overflow-y-auto rolagem pr-1 -mr-1">
          {lista.map((f) => (
            <li key={f.nome} className="group relative overflow-hidden rounded border border-aco/25 bg-tinta-funda/60">
              <button type="button" data-clicavel onClick={() => setAberta(aberta === f.nome ? null : f.nome)} className="block w-full" aria-label={`Ver foto de ${horaCurta(f.quando)}`}>
                <img src={comToken(`/api/sentinela/fotos/${encodeURIComponent(f.nome)}`)} alt="" loading="lazy" className="aspect-[4/3] w-full object-cover" />
              </button>
              <div className="flex items-center justify-between gap-1 px-1.5 py-1">
                <span className="truncate text-[11px] text-gelo/80">{horaCurta(f.quando)}</span>
                {noPc && (
                  <button type="button" data-clicavel onClick={() => apagar(f.nome)} aria-label="Apagar foto" className="shrink-0 text-aco hover:text-coral">
                    <Icone.Lixeira tamanho={13} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {aberta && (
        <img
          src={comToken(`/api/sentinela/fotos/${encodeURIComponent(aberta)}`)}
          alt="Captura do Sentinela"
          className="mt-2 w-full rounded border border-aco/30"
          onClick={() => setAberta(null)}
        />
      )}
    </div>
  );
}
