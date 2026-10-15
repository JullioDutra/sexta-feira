// Extensão "comunicacao": holograma do tradutor (voz, tela e texto copiado) e a personalidade em Ajustes.
import { AjustePersonalidade } from "./comunicacao/Personalidade";
import { GlifoTraducao, PararTradutorComEsc, Traducao } from "./comunicacao/Traducao";
import type { Extensao } from "./tipos";

const extensao: Extensao = {
  hologramas: {
    traducao: { componente: Traducao, glifo: (tamanho) => <GlifoTraducao tamanho={tamanho} /> },
  },
  ajustes: [{ titulo: "Personalidade", componente: AjustePersonalidade }],
  sobreposicoes: [PararTradutorComEsc],
};

export default extensao;
