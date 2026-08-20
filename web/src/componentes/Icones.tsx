/** Sprite SVG de ícones, portado de `clima-global-prototipo-v2.html:351`.
 *
 * A convenção do protótipo vale aqui, e o CLAUDE.md a torna obrigatória: ícone
 * só sai do sprite, via o helper — nada de glifo de texto (`▦`, `◎`, `≡`) numa
 * interface de produto. Glifo herda a métrica da fonte, muda de desenho entre
 * plataformas e não aceita `stroke-width`; um `<symbol>` faz as três coisas.
 *
 * Para acrescentar um ícone: declare o `<symbol id="i-*">` em `SIMBOLOS` antes
 * de usar `<Icone nome="*">`. O `id` é global no documento, e o sprite é
 * montado uma única vez por `<SpriteIcones />` na raiz da aplicação.
 */

export type NomeIcone =
  | "grid" | "globe" | "activity" | "file" | "bell" | "db" | "settings"
  | "search" | "menu" | "moon" | "sun" | "layers" | "expand" | "arrow"
  | "spark" | "marquee" | "minus" | "crosshair" | "shrink" | "chevron"
  | "close" | "filter" | "list" | "check" | "plus" | "download" | "webhook"
  | "shield" | "more";

/** `d`/markup exatamente como no protótipo: mesma grade de 24, mesmo traço. */
const SIMBOLOS: Record<NomeIcone, string> = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.6 3 14.4 0 18M12 3c-3 3.6-3 14.4 0 18"/>',
  activity: '<path d="M3 12h4l2.4-7 4.2 14 2.4-7h5"/>',
  file: '<path d="M6 2h8l4 4v16H6zM14 2v5h5M9 12h6M9 16h6"/>',
  bell: '<path d="M18 8a6 6 0 10-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19 15l2 2-4 4-2-2-3 1-1 3H6l-1-3-3-1v-5l3-1V9L2 7l4-4 2 2 3-1 1-3h5l1 3 3 1v5l-3 1z"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  moon: '<path d="M20 15.5A8.5 8.5 0 018.5 4 8.5 8.5 0 1020 15.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  layers: '<path d="M12 2L2 7l10 5 10-5-10-5zM2 12l10 5 10-5M2 17l10 5 10-5"/>',
  expand: '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  spark: '<path d="M12 2l1.5 5.5L19 9l-5.5 1.5L12 16l-1.5-5.5L5 9l5.5-1.5L12 2zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16z"/>',
  marquee: '<path d="M3 8V5a2 2 0 012-2h3M16 3h3a2 2 0 012 2v3M21 16v3a2 2 0 01-2 2h-3M8 21H5a2 2 0 01-2-2v-3"/>',
  minus: '<path d="M5 12h14"/>',
  crosshair: '<circle cx="12" cy="12" r="7"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  shrink: '<path d="M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6"/>',
  chevron: '<path d="M9 18l6-6-6-6"/>',
  close: '<path d="M5 5l14 14M19 5L5 19"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.1M3 12h.1M3 18h.1"/>',
  check: '<path d="M4 12l5 5L20 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
  webhook: '<circle cx="6" cy="12" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M9 11l6-4M9 13l6 4"/>',
  shield: '<path d="M12 2l8 4v6c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6zM8 12l3 3 5-6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
};

/** Monta o sprite uma vez. Precisa vir antes de qualquer `<use>` na árvore. */
export function SpriteIcones() {
  return (
    <svg
      aria-hidden="true"
      width="0"
      height="0"
      style={{ position: "absolute", overflow: "hidden" }}
    >
      <defs>
        {(Object.keys(SIMBOLOS) as NomeIcone[]).map((nome) => (
          <symbol
            key={nome}
            id={`i-${nome}`}
            viewBox="0 0 24 24"
            dangerouslySetInnerHTML={{ __html: SIMBOLOS[nome] }}
          />
        ))}
      </defs>
    </svg>
  );
}

/**
 * O ícone é sempre decorativo: `aria-hidden`. Quem precisa de nome acessível é
 * o controle que o contém, e é lá que o `aria-label` fica — repetir aqui faria
 * o leitor de tela anunciar o rótulo duas vezes.
 *
 * @param tamanho `sm` 15px, padrão 18px, `lg` 21px — a escala do protótipo.
 */
export function Icone({
  nome,
  tamanho,
  className = "",
}: {
  nome: NomeIcone;
  tamanho?: "sm" | "lg";
  className?: string;
}) {
  const classes = ["icon", tamanho ?? "", className].filter(Boolean).join(" ");
  return (
    <svg className={classes} aria-hidden="true" focusable="false">
      <use href={`#i-${nome}`} />
    </svg>
  );
}
