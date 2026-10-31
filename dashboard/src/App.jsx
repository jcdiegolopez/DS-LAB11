import SerieSubdestino from './charts/SerieSubdestino';
import TarjetaGrafica from './charts/TarjetaGrafica';
import { useVersion } from './state/useVersion';
import { describirMeses, formatoNumero, formatoRazon } from './series';

const fechaHora = new Intl.DateTimeFormat('es-GT', { dateStyle: 'long', timeStyle: 'short' });

function Encabezado() {
  return (
    <header className="encabezado">
      <p className="supra">Observatorio de turismo sostenible</p>
      <h1>Visitantes extranjeros en Tikal y Flores</h1>
      <p className="bajada">
        Estimación mensual por subdestino (Isla de Flores, El Remate y alrededores del lago, aeropuerto Mundo Maya).
        Datos de telefonía móvil y registros migratorios de INGUAT / IGM.
      </p>
    </header>
  );
}

function NoDisponible({ detalle }) {
  return (
    <div className="no-disponible" role="status">
      <h2>Estimaciones no disponibles</h2>
      <p>Todavía no hay una versión aprobada de las estimaciones. El tablero solo muestra versiones que pasaron los
        controles de calidad y la regla de aceptación.</p>
      {detalle && <p className="nota">{detalle}</p>}
    </div>
  );
}

function Version({ id, meta }) {
  const m = meta.metrics ?? {};
  const referencia = m.best_baseline_mae;
  return (
    <TarjetaGrafica id="E2" titulo="Versión publicada y calidad de la estimación">
      <dl className="ficha">
        <div><dt>Actualizado</dt><dd>{fechaHora.format(new Date(meta.generated_at))}</dd></div>
        <div><dt>Versión</dt><dd><code>{id}</code></dd></div>
        <div><dt>Error medio (MAE)</dt><dd>{m.mae != null ? `${formatoNumero.format(m.mae)} visitantes` : '—'}</dd></div>
        <div><dt>MAE de la mejor referencia simple</dt><dd>{referencia != null ? `${formatoNumero.format(referencia)} visitantes` : '—'}</dd></div>
        <div><dt>Razón frente a la referencia</dt><dd>{m.mae_ratio_vs_best_baseline != null ? formatoRazon.format(m.mae_ratio_vs_best_baseline) : '—'}</dd></div>
        <div><dt>Meses evaluados</dt><dd>{describirMeses(meta.eval_months ?? [])}</dd></div>
      </dl>
      <p className="nota">
        El error se mide con validación temporal: cada mes evaluado se estima solo con los meses observados anteriores
        y se compara con lo que midió la telefonía. Enero y febrero de 2026 no tienen medición, así que no tienen error calculado.
      </p>
    </TarjetaGrafica>
  );
}

function Cobertura({ filas }) {
  const observados = [...new Set(filas.filter((f) => f.kind === 'observed' && f.value !== null).map((f) => f.period))];
  const estimados = [...new Set(filas.filter((f) => f.kind === 'estimated').map((f) => f.period))];
  return (
    <TarjetaGrafica id="E3" titulo="Cobertura, vacíos y limitaciones">
      <ul className="lista">
        <li><strong>Con medición de telefonía:</strong> {describirMeses(observados)}.</li>
        <li><strong>Sin medición (se estiman):</strong> {describirMeses(estimados)}. Se muestran como «Sin dato» en la serie observada y con la etiqueta «Estimación».</li>
      </ul>
      <div className="aviso-fijo aviso-bloque">
        <strong>Limitaciones.</strong> La estimación reparte las entradas migratorias del mes (turistas y excursionistas)
        según la proporción observada en cada subdestino; supone que esa proporción se mantiene, y solo hay pocos meses para
        comprobarlo. No existe un total de Petén: los subdestinos comparten visitantes y no deben sumarse. Las cifras
        se refieren a visitantes extranjeros.
      </div>
    </TarjetaGrafica>
  );
}

export default function App() {
  const version = useVersion();

  let contenido;
  if (version.estado === 'cargando') contenido = <div className="sin-datos">Cargando la versión aprobada…</div>;
  else if (version.estado === 'lista') {
    const subdestinos = [...new Set(version.filas.map((f) => f.subdestination))];
    contenido = (
      <>
        <SerieSubdestino filas={version.filas} subdestinos={subdestinos} />
        <Version id={version.id} meta={version.meta} />
        <Cobertura filas={version.filas} />
      </>
    );
  } else contenido = <NoDisponible detalle={version.detalle} />;

  return (
    <div className="app">
      <Encabezado />
      <main>{contenido}</main>
      <footer className="pie">
        Fuente: INGUAT / IGM. Laboratorio 11 (CC3066 – Data Science, UVG). Uso académico.
      </footer>
    </div>
  );
}
