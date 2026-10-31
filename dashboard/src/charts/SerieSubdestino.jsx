import { useMemo, useState } from 'react';
import Plot from './Plot';
import TarjetaGrafica from './TarjetaGrafica';
import { colores } from '../theme/colors';
import { configBase, layoutBase } from '../theme/plotlyBase';
import { etiquetaMes, formatoNumero, serieMensual } from '../series';

const fecha = (periodo) => `${periodo}-01`;

// Bloques de meses consecutivos sin observación, para sombrearlos en la gráfica.
function huecos(serie) {
  const bloques = [];
  serie.forEach((p, i) => {
    if (p.observado !== null) return;
    const previo = bloques.at(-1);
    if (previo && previo.fin === i - 1) previo.fin = i;
    else bloques.push({ inicio: i, fin: i });
  });
  return bloques.map(({ inicio, fin }) => [serie[inicio].periodo, serie[fin].periodo]);
}

function finDeMes(periodo) {
  const [a, m] = periodo.split('-').map(Number);
  return new Date(Date.UTC(a, m, 0)).toISOString().slice(0, 10);
}

export default function SerieSubdestino({ filas, subdestinos }) {
  const [subdestino, setSubdestino] = useState(subdestinos[0]);
  const serie = useMemo(() => serieMensual(filas, subdestino), [filas, subdestino]);
  const sinDato = huecos(serie);
  const estimados = serie.filter((p) => p.estimacion !== null);

  const trazas = [
    {
      type: 'scatter',
      mode: 'lines+markers',
      name: 'Observado',
      x: serie.map((p) => fecha(p.periodo)),
      y: serie.map((p) => p.observado),
      connectgaps: false, // el hueco se ve como hueco, nunca como cero
      customdata: serie.map((p) => etiquetaMes(p.periodo)),
      line: { color: colores.observado, width: 3 },
      marker: { color: colores.observado, size: 7 },
      hovertemplate: '<b>%{customdata}</b><br>Observado: %{y:,.0f}<extra></extra>',
    },
    {
      type: 'scatter',
      mode: 'markers+text',
      name: 'Estimación',
      x: estimados.map((p) => fecha(p.periodo)),
      y: estimados.map((p) => p.estimacion),
      text: estimados.map(() => 'Estimación'),
      textposition: 'top center',
      textfont: { color: colores.atencionTexto, size: 12 },
      customdata: estimados.map((p) => etiquetaMes(p.periodo)),
      marker: { color: colores.tarjeta, size: 11, symbol: 'diamond', line: { color: colores.atencion, width: 3 } },
      hovertemplate: '<b>%{customdata}</b><br>Estimación: %{y:,.0f}<br>(sin dato observado)<extra></extra>',
    },
  ];

  const layout = layoutBase({
    height: 420,
    uirevision: subdestino,
    margin: { l: 70, r: 30, t: 30, b: 50 },
    hovermode: 'closest',
    xaxis: {
      type: 'date',
      range: serie.length ? [fecha(serie[0].periodo), finDeMes(serie.at(-1).periodo)] : undefined,
      dtick: 'M1',
      tickformat: '%b<br>%Y',
    },
    yaxis: { title: { text: 'Visitantes extranjeros', font: { size: 13, color: colores.contexto } }, rangemode: 'tozero' },
    shapes: sinDato.map(([a, b]) => ({
      type: 'rect', xref: 'x', yref: 'paper', x0: fecha(a), x1: finDeMes(b), y0: 0, y1: 1,
      fillcolor: colores.tarjetaOscura, opacity: 0.9, line: { width: 0 }, layer: 'below',
    })),
    annotations: sinDato.map(([a]) => ({
      x: fecha(a), xref: 'x', y: 0.04, yref: 'paper', text: 'Sin dato de telefonía', showarrow: false,
      xanchor: 'left', xshift: 4, font: { size: 12, color: colores.contexto },
    })),
  });

  const controles = (
    <div className="grupo-botones" role="group" aria-label="Subdestino">
      <span className="control-etiqueta">Subdestino:</span>
      {subdestinos.map((s) => (
        <button key={s} type="button" className={s === subdestino ? 'activo' : ''} aria-pressed={s === subdestino}
          onClick={() => setSubdestino(s)}>
          {s}
        </button>
      ))}
    </div>
  );

  return (
    <TarjetaGrafica
      id="E1"
      titulo={`Visitantes extranjeros por mes — ${subdestino}`}
      queMuestra="Los visitantes únicos medidos por telefonía (línea azul) y la estimación para los meses sin cobertura (rombos naranjas, etiquetados «Estimación»)."
      paraQueSirve="Ver el nivel mensual de cada subdestino y qué meses son medición y cuáles son estimación."
      controles={controles}
      nota={`Unidad: visitantes extranjeros únicos por mes. La franja gris marca meses sin dato de telefonía: no se rellenan con cero. Cada subdestino es una serie aparte; no se suman entre sí.`}
    >
      <div className="leyenda" aria-hidden="true">
        <span><span className="muestra muestra-observado" /> Observado (telefonía)</span>
        <span><span className="muestra muestra-estimacion" /> Estimación</span>
        <span><span className="muestra muestra-sin-dato" /> Sin dato</span>
      </div>
      <Plot data={trazas} layout={layout} config={configBase} style={{ width: '100%' }} />
      <table className="tabla-metricas tabla-serie">
        <caption>Valores mensuales — {subdestino}</caption>
        <thead>
          <tr><th scope="col">Mes</th><th scope="col">Observado</th><th scope="col">Estimación</th></tr>
        </thead>
        <tbody>
          {serie.map((p) => (
            <tr key={p.periodo} className={p.estimacion !== null ? 'fila-estimacion' : ''}>
              <th scope="row">{etiquetaMes(p.periodo)}</th>
              <td className={p.observado === null ? 'sin-dato-celda' : ''}>
                {p.observado === null ? 'Sin dato' : formatoNumero.format(p.observado)}
              </td>
              <td>{p.estimacion === null ? '—' : formatoNumero.format(p.estimacion)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TarjetaGrafica>
  );
}
