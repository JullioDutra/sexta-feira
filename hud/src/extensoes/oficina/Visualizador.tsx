// Holograma "Visualizador de música": anel de barras (espectro espelhado) e núcleo que pulsa com o grave.
// Os valores chegam pelo evento "musica.espectro" (25 por segundo) e são lidos aqui no requestAnimationFrame.
// Sem som (fora do Windows, sem a biblioteca, nada tocando) fica uma animação calma, com o motivo embaixo.
import { useEffect, useRef } from "react";
import { corDaLuz, espectro, useMusica, type DadosVisualizador } from "./tipos";

const SEM_SINAL_MS = 1200;

export default function Visualizador({ dados, tamanho = 380 }: { dados: DadosVisualizador; tamanho?: number }) {
  const tela = useRef<HTMLCanvasElement>(null);
  const vivo = useMusica((s) => s.estado);
  const estado = vivo ?? dados ?? {};

  useEffect(() => {
    const canvas = tela.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = tamanho * dpr;
    canvas.height = tamanho * dpr;
    ctx.scale(dpr, dpr);
    const cor = corDaLuz();
    let mostradas = new Float32Array(64);
    let grave = 0;
    let quadro = 0;

    const desenhar = (agora: number) => {
      quadro = requestAnimationFrame(desenhar);
      const comSinal = agora - espectro.em < SEM_SINAL_MS;
      const n = espectro.bandas.length;
      const total = n * 2; // espelhado: graves embaixo dos dois lados
      if (mostradas.length !== total) mostradas = new Float32Array(total);
      for (let i = 0; i < total; i++) {
        const banda = i < n ? i : total - 1 - i;
        let alvo: number;
        if (comSinal) alvo = espectro.bandas[banda];
        else alvo = 0.08 + 0.06 * Math.sin(agora / 900 + banda * 0.45) * Math.sin(agora / 1700 + i * 0.2); // ocioso
        mostradas[i] = alvo > mostradas[i] ? alvo : mostradas[i] * 0.9 + alvo * 0.1;
      }
      const alvoGrave = comSinal ? espectro.grave : 0.12 + 0.08 * Math.sin(agora / 1200);
      grave = alvoGrave > grave ? grave + (alvoGrave - grave) * 0.6 : grave * 0.92 + alvoGrave * 0.08;

      const c = tamanho / 2;
      const raioBase = tamanho * 0.23;
      const comprimento = tamanho * 0.22;
      ctx.clearRect(0, 0, tamanho, tamanho);
      ctx.save();
      ctx.translate(c, c);
      ctx.strokeStyle = cor;
      ctx.fillStyle = cor;
      ctx.shadowColor = cor;
      ctx.lineCap = "round";

      // anéis de referência
      ctx.globalAlpha = 0.18;
      ctx.lineWidth = 1;
      ctx.shadowBlur = 0;
      for (const r of [raioBase * 0.92, raioBase + comprimento + 8]) {
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, Math.PI * 2);
        ctx.stroke();
      }

      // barras
      ctx.shadowBlur = 10;
      const largura = Math.max(1.5, ((Math.PI * 2 * raioBase) / total) * 0.55);
      ctx.lineWidth = largura;
      const giro = agora / 9000;
      for (let i = 0; i < total; i++) {
        const v = mostradas[i];
        const angulo = (i / total) * Math.PI * 2 + Math.PI / 2 + giro;
        const r1 = raioBase;
        const r2 = raioBase + 3 + v * comprimento;
        ctx.globalAlpha = 0.35 + v * 0.65;
        ctx.beginPath();
        ctx.moveTo(Math.cos(angulo) * r1, Math.sin(angulo) * r1);
        ctx.lineTo(Math.cos(angulo) * r2, Math.sin(angulo) * r2);
        ctx.stroke();
      }

      // núcleo pulsando com o grave
      const raioNucleo = raioBase * (0.42 + grave * 0.38);
      const brilho = ctx.createRadialGradient(0, 0, 0, 0, 0, raioNucleo * 1.6);
      brilho.addColorStop(0, cor);
      brilho.addColorStop(0.45, cor);
      brilho.addColorStop(1, "transparent");
      ctx.globalAlpha = 0.25 + grave * 0.45;
      ctx.shadowBlur = 30 * grave;
      ctx.fillStyle = brilho;
      ctx.beginPath();
      ctx.arc(0, 0, raioNucleo * 1.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 0.85;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(0, 0, raioNucleo, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    };
    quadro = requestAnimationFrame(desenhar);
    return () => cancelAnimationFrame(quadro);
  }, [tamanho]);

  return (
    <div style={{ width: tamanho }} className="max-w-full">
      <canvas ref={tela} style={{ width: tamanho, height: tamanho }} className="block max-w-full" aria-label="Espectro do som do computador" role="img" />
      <p className="mt-1 text-center text-xs text-aco leading-snug">
        {estado.ativo ? "Ouvindo o som do computador." : estado.motivo || "Esperando o som do computador…"}
      </p>
    </div>
  );
}
