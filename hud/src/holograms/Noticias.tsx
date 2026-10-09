import { Icone } from "./Glifos";

interface Item {
  titulo: string;
  fonte: string;
  link: string;
  quando: string;
}

export default function Noticias({ dados }: { dados: { itens: Item[] } }) {
  const itens = dados?.itens ?? [];
  if (!itens.length) return <p className="w-[420px] text-sm text-aco">Nenhuma manchete agora.</p>;
  return (
    <ol className="w-[440px] max-h-[430px] overflow-y-auto rolagem pr-1 -mr-1">
      {itens.map((item, i) => (
        <li key={item.link || i} className={i ? "border-t border-aco/15" : ""}>
          <a
            href={item.link}
            target="_blank"
            rel="noreferrer"
            data-clicavel
            className="group grid grid-cols-[22px_1fr_16px] gap-2 py-2.5 items-start outline-none focus-visible:bg-[rgb(var(--luz-rgb)/0.08)]"
          >
            <span className="numeral text-lg leading-6 text-[var(--luz)]/70">{i + 1}</span>
            <span>
              <span className="block text-[15px] leading-snug text-gelo group-hover:text-white">{item.titulo}</span>
              <span className="mt-1 block text-xs text-aco">
                {item.fonte}
                {item.quando ? `, ${item.quando}` : ""}
              </span>
            </span>
            <Icone.Externo tamanho={14} className="mt-1 text-aco opacity-0 group-hover:opacity-100 transition-opacity" />
          </a>
        </li>
      ))}
    </ol>
  );
}
