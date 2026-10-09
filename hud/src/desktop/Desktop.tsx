import { useEffect, useState } from "react";
import { conexao } from "../lib/socket";
import { useHud } from "../lib/store";
import Ajustes from "./Ajustes";
import { Avisos, BarraComando, Cabecalho, Doca, Espelho, Legendas, Status } from "./Interface";
import Nucleo from "./Nucleo";
import Palco from "./Palco";
import { PrimeiraConfiguracao, SemAcesso, TelaBloqueio } from "./Telas";

export default function Desktop() {
  const semAcesso = useHud((s) => s.semAcesso);
  const tema = useHud((s) => s.prefs?.tema ?? "sexta");
  const maosLigadas = useHud((s) => s.maosLigadas);
  const [ajustes, setAjustes] = useState(false);

  useEffect(() => {
    conexao.conectar();
    return () => conexao.parar();
  }, []);

  useEffect(() => {
    document.documentElement.dataset.tema = tema;
  }, [tema]);

  // quando a Sexta liga os gestos (por voz), este HUD passa a receber os pontos das mãos
  useEffect(() => {
    conexao.definirMaos(maosLigadas);
  }, [maosLigadas]);

  if (semAcesso) return <SemAcesso />;

  return (
    <main className="relative h-full w-full overflow-hidden">
      <h1 className="sr-only">Sexta-Feira</h1>
      <Nucleo />
      <Palco />
      <div className="absolute inset-0 z-[2000] pointer-events-none">
        <Cabecalho />
        <Status />
        <Legendas />
        <Doca abrirAjustes={() => setAjustes(true)} />
        <BarraComando />
        <Espelho />
      </div>
      <TelaBloqueio />
      <PrimeiraConfiguracao />
      {ajustes && <Ajustes aoFechar={() => setAjustes(false)} />}
      <Avisos />
    </main>
  );
}
