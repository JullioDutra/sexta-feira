// Glifos em traço fino (luz), desenhados para o HUD.
import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement> & { tamanho?: number };

function Svg({ tamanho = 20, children, ...resto }: Props & { children: React.ReactNode }) {
  return (
    <svg
      width={tamanho}
      height={tamanho}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...resto}
    >
      {children}
    </svg>
  );
}

const nuvem = "M7 18h10.5a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.4 9.2 4.4 4.4 0 0 0 7 18Z";

export function GlifoClima({ icone, dia = true, ...p }: Props & { icone: string; dia?: boolean }) {
  switch (icone) {
    case "limpo":
      return dia ? (
        <Svg {...p}>
          <circle cx="12" cy="12" r="4.2" />
          {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
            <line key={a} x1="12" y1="2.6" x2="12" y2="4.8" transform={`rotate(${a} 12 12)`} />
          ))}
        </Svg>
      ) : (
        <Svg {...p}>
          <path d="M19.5 14.6A7.6 7.6 0 1 1 9.4 4.5a6.2 6.2 0 0 0 10.1 10.1Z" />
        </Svg>
      );
    case "parcial":
      return (
        <Svg {...p}>
          <circle cx="8.5" cy="8" r="3" />
          <path d="M8.5 2.6v1.2M3.1 8h1.2M4.7 4.2l.9.9M12.3 4.2l-.9.9" />
          <path d="M9 19h9a3.4 3.4 0 0 0 .5-6.77A4.7 4.7 0 0 0 9.4 11.5 3.75 3.75 0 0 0 9 19Z" />
        </Svg>
      );
    case "nublado":
      return (
        <Svg {...p}>
          <path d={nuvem} />
        </Svg>
      );
    case "neblina":
      return (
        <Svg {...p}>
          <path d="M4 9h16M2.5 13h19M5 17h14M7.5 21h9" />
        </Svg>
      );
    case "garoa":
      return (
        <Svg {...p}>
          <path d="M7 15h10.5a3.6 3.6 0 0 0 .55-7.16A4.9 4.9 0 0 0 7.4 7 4 4 0 0 0 7 15Z" />
          <path d="M8 18.5v.1M12 19.5v.1M16 18.5v.1M10 21.5v.1M14 21.5v.1" strokeWidth={2} />
        </Svg>
      );
    case "chuva":
    case "chuva_forte":
      return (
        <Svg {...p}>
          <path d="M7 14h10.5a3.6 3.6 0 0 0 .55-7.16A4.9 4.9 0 0 0 7.4 6 4 4 0 0 0 7 14Z" />
          <path d="M9 17l-1 3M13 17l-1 3M17 17l-1 3" />
          {icone === "chuva_forte" && <path d="M11 21l-.6 1.6M15 21l-.6 1.6" />}
        </Svg>
      );
    case "neve":
      return (
        <Svg {...p}>
          <path d="M7 14h10.5a3.6 3.6 0 0 0 .55-7.16A4.9 4.9 0 0 0 7.4 6 4 4 0 0 0 7 14Z" />
          <path d="M9 17.5v3M7.7 19h2.6M15 17.5v3M13.7 19h2.6" />
        </Svg>
      );
    case "tempestade":
      return (
        <Svg {...p}>
          <path d="M7 14h10.5a3.6 3.6 0 0 0 .55-7.16A4.9 4.9 0 0 0 7.4 6 4 4 0 0 0 7 14Z" />
          <path d="M12.5 14.5 10 18.5h3l-2 4" />
        </Svg>
      );
    default:
      return (
        <Svg {...p}>
          <path d={nuvem} />
        </Svg>
      );
  }
}

export function GlifoTipo({ tipo, ...p }: Props & { tipo: string }) {
  switch (tipo) {
    case "clima":
      return <GlifoClima icone="parcial" {...p} />;
    case "noticias":
    case "jornal":
      return (
        <Svg {...p}>
          <rect x="3.5" y="4.5" width="17" height="15" rx="1" />
          <path d="M7 9h10M7 12.5h10M7 16h6" />
        </Svg>
      );
    case "sistema":
      return (
        <Svg {...p}>
          <rect x="6.5" y="6.5" width="11" height="11" rx="1" />
          <rect x="9.5" y="9.5" width="5" height="5" />
          <path d="M9 3.5v3M12 3.5v3M15 3.5v3M9 17.5v3M12 17.5v3M15 17.5v3M3.5 9h3M3.5 12h3M3.5 15h3M17.5 9h3M17.5 12h3M17.5 15h3" />
        </Svg>
      );
    case "relogio":
      return (
        <Svg {...p}>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7v5l3.2 2" />
        </Svg>
      );
    case "globo":
      return (
        <Svg {...p}>
          <circle cx="12" cy="12" r="8.5" />
          <ellipse cx="12" cy="12" rx="3.8" ry="8.5" />
          <path d="M3.5 12h17M5 7.5h14M5 16.5h14" />
        </Svg>
      );
    case "lembretes":
      return (
        <Svg {...p}>
          <path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.5H5Z" />
          <path d="M10 20.5a2 2 0 0 0 4 0" />
        </Svg>
      );
    case "rotinas":
      return (
        <Svg {...p}>
          <path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5" />
          <path d="M20 4v4.5h-4.5" />
          <path d="M20 12a8 8 0 0 1-13.7 5.6L4 15.5" />
          <path d="M4 20v-4.5h4.5" />
        </Svg>
      );
    case "camera":
      return (
        <Svg {...p}>
          <circle cx="12" cy="11" r="6.5" />
          <circle cx="12" cy="11" r="2.6" />
          <path d="M8 20.5h8" />
        </Svg>
      );
    case "atividades":
      return (
        <Svg {...p}>
          <path d="M3.5 12h4l2.5-6 4 12 2.5-6h4" />
        </Svg>
      );
    case "imagem":
      return (
        <Svg {...p}>
          <rect x="3.5" y="5" width="17" height="14" rx="1" />
          <path d="m3.5 16 5-5 4 4 2.5-2.5 5.5 5" />
          <circle cx="16" cy="9" r="1.4" />
        </Svg>
      );
    default:
      return (
        <Svg {...p}>
          <path d="M6 3.5h8.5L19 8v12.5H6Z" />
          <path d="M14 3.5V8h5M9 12h7M9 15.5h7" />
        </Svg>
      );
  }
}

export const Icone = {
  Fechar: (p: Props) => (
    <Svg {...p}>
      <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
    </Svg>
  ),
  Microfone: (p: Props) => (
    <Svg {...p}>
      <rect x="9" y="3.5" width="6" height="11" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" />
    </Svg>
  ),
  MicrofoneDesligado: (p: Props) => (
    <Svg {...p}>
      <path d="M15 10V6.5a3 3 0 0 0-5.8-1.1M9 9.5v2a3 3 0 0 0 4.6 2.5M5.5 11.5a6.5 6.5 0 0 0 10.6 5M18.4 13.4a6.5 6.5 0 0 0 .1-1.9M12 18v2.5M4 4l16 16" />
    </Svg>
  ),
  Mao: (p: Props) => (
    <Svg {...p}>
      <path d="M8 12.5V6a1.5 1.5 0 0 1 3 0v5M11 11V4.5a1.5 1.5 0 0 1 3 0V11M14 11V6a1.5 1.5 0 0 1 3 0v7c0 4-2.5 7.5-6.5 7.5-2.8 0-4.4-1.6-5.7-3.8L3.6 14a1.5 1.5 0 0 1 2.6-1.5L8 15" />
    </Svg>
  ),
  Camera: (p: Props) => (
    <Svg {...p}>
      <circle cx="12" cy="11" r="6.5" />
      <circle cx="12" cy="11" r="2.6" />
    </Svg>
  ),
  Cadeado: (p: Props) => (
    <Svg {...p}>
      <rect x="5" y="10.5" width="14" height="10" rx="1.5" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </Svg>
  ),
  CadeadoAberto: (p: Props) => (
    <Svg {...p}>
      <rect x="5" y="10.5" width="14" height="10" rx="1.5" />
      <path d="M8 10.5V7.5a4 4 0 0 1 7.6-1.8" />
    </Svg>
  ),
  Ajustes: (p: Props) => (
    <Svg {...p}>
      <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
      <circle cx="15" cy="7" r="2" />
      <circle cx="9" cy="17" r="2" />
    </Svg>
  ),
  Teclado: (p: Props) => (
    <Svg {...p}>
      <rect x="2.5" y="6" width="19" height="12" rx="1.5" />
      <path d="M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M7.5 14h9" strokeWidth={1.8} />
    </Svg>
  ),
  Enviar: (p: Props) => (
    <Svg {...p}>
      <path d="M4 12 20 4l-5 16-3-7Z" />
      <path d="m12 13 8-9" />
    </Svg>
  ),
  Executar: (p: Props) => (
    <Svg {...p}>
      <path d="M8 5.5v13l10-6.5Z" />
    </Svg>
  ),
  Parar: (p: Props) => (
    <Svg {...p}>
      <rect x="6.5" y="6.5" width="11" height="11" rx="1" />
    </Svg>
  ),
  Celular: (p: Props) => (
    <Svg {...p}>
      <rect x="7" y="2.5" width="10" height="19" rx="2" />
      <path d="M11 18.5h2" />
    </Svg>
  ),
  Lixeira: (p: Props) => (
    <Svg {...p}>
      <path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13" />
    </Svg>
  ),
  Alarme: (p: Props) => (
    <Svg {...p}>
      <circle cx="12" cy="13" r="7" />
      <path d="M12 9.5V13l2.5 1.5M4 5.5l3-2.5M20 5.5l-3-2.5" />
    </Svg>
  ),
  Repetir: (p: Props) => (
    <Svg {...p}>
      <path d="M4 10.5V9a3 3 0 0 1 3-3h12l-3-3M20 13.5V15a3 3 0 0 1-3 3H5l3 3" />
    </Svg>
  ),
  Externo: (p: Props) => (
    <Svg {...p}>
      <path d="M13.5 4.5H19.5V10.5M19.5 4.5l-9 9M17 13.5v6H4.5V7h6" />
    </Svg>
  ),
  Foco: (p: Props) => (
    <Svg {...p}>
      <path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" />
    </Svg>
  ),
};
