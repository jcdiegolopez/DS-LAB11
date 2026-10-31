import { colores, fuentes } from './colors';

// Layout base que comparten todas las gráficas de Plotly del tablero.
export function layoutBase(extra = {}) {
  return {
    font: { family: fuentes.texto, size: 14, color: colores.tinta },
    paper_bgcolor: colores.tarjeta,
    plot_bgcolor: colores.tarjeta,
    separators: '.,',
    uirevision: 'fijo', // conserva el zoom del usuario entre renders
    margin: { l: 70, r: 120, t: 20, b: 50 },
    hoverlabel: { font: { family: fuentes.texto, size: 14 }, bgcolor: '#FFFFFF' },
    showlegend: false,
    ...extra,
    xaxis: {
      gridcolor: colores.rejilla,
      linecolor: colores.contexto,
      tickfont: { color: colores.contexto },
      ...(extra.xaxis || {}),
    },
    yaxis: {
      gridcolor: colores.rejilla,
      zeroline: false,
      tickfont: { color: colores.contexto },
      tickformat: '~s',
      ...(extra.yaxis || {}),
    },
  };
}

export const configBase = {
  displaylogo: false,
  responsive: true,
  locale: 'es',
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
};
