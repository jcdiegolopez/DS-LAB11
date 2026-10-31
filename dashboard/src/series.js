const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

export function etiquetaMes(periodo) {
  const [a, m] = periodo.split('-');
  return `${MESES[Number(m) - 1]} ${a}`;
}

export function rangoMeses(primero, ultimo) {
  const meses = [];
  let [a, m] = primero.split('-').map(Number);
  const [af, mf] = ultimo.split('-').map(Number);
  while (a < af || (a === af && m <= mf)) {
    meses.push(`${a}-${String(m).padStart(2, '0')}`);
    m += 1;
    if (m > 12) { m = 1; a += 1; }
  }
  return meses;
}

// Agrupa rangos de meses consecutivos: ['2025-09', ..., '2025-12'] -> 'sep 2025 – dic 2025'.
export function describirMeses(meses) {
  if (!meses.length) return 'ninguno';
  const ordenados = [...meses].sort();
  const tramos = [];
  let inicio = ordenados[0];
  let previo = ordenados[0];
  for (const mes of ordenados.slice(1)) {
    if (rangoMeses(previo, mes).length !== 2) {
      tramos.push([inicio, previo]);
      inicio = mes;
    }
    previo = mes;
  }
  tramos.push([inicio, previo]);
  return tramos.map(([a, b]) => (a === b ? etiquetaMes(a) : `${etiquetaMes(a)} – ${etiquetaMes(b)}`)).join(' y ');
}

// Una fila por mes del rango completo de la versión. Un mes sin observación queda en null
// ("Sin dato"), nunca en cero, aunque tenga estimación.
export function serieMensual(filas, subdestino) {
  const propias = filas.filter((f) => f.subdestination === subdestino);
  const periodos = propias.map((f) => f.period).sort();
  if (!periodos.length) return [];
  const valor = (periodo, kind) =>
    propias.find((f) => f.period === periodo && f.kind === kind)?.value ?? null;
  return rangoMeses(periodos[0], periodos.at(-1)).map((periodo) => ({
    periodo,
    observado: valor(periodo, 'observed'),
    estimacion: valor(periodo, 'estimated'),
  }));
}

export const formatoNumero = new Intl.NumberFormat('es-GT', { maximumFractionDigits: 0 });
export const formatoRazon = new Intl.NumberFormat('es-GT', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
