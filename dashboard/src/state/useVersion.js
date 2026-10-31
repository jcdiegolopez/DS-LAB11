import { useEffect, useState } from 'react';

// Ruta servida por nginx (y por Vite en desarrollo) desde el volumen de versiones aprobadas.
const BASE = `${import.meta.env.BASE_URL}approved/`;

async function leer(ruta, tipo) {
  // Sin caché: el puntero cambia cuando se publica o se restaura una versión.
  const r = await fetch(`${BASE}${ruta}`, { cache: 'no-store' });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`No se pudo leer ${ruta} (${r.status})`);
  return tipo === 'json' ? r.json() : r.text();
}

// CSV simple con comillas opcionales; los campos vacíos quedan como cadena vacía.
export function parsearCSV(texto) {
  const filas = [];
  let campo = '';
  let fila = [];
  let entreComillas = false;
  for (let i = 0; i < texto.length; i++) {
    const c = texto[i];
    if (entreComillas) {
      if (c === '"' && texto[i + 1] === '"') { campo += '"'; i++; }
      else if (c === '"') entreComillas = false;
      else campo += c;
    } else if (c === '"') entreComillas = true;
    else if (c === ',') { fila.push(campo); campo = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && texto[i + 1] === '\n') i++;
      fila.push(campo); campo = '';
      if (fila.some((v) => v !== '')) filas.push(fila);
      fila = [];
    } else campo += c;
  }
  if (campo !== '' || fila.length) { fila.push(campo); filas.push(fila); }
  const [encabezado, ...resto] = filas;
  return resto.map((f) => Object.fromEntries(encabezado.map((col, j) => [col, f[j] ?? ''])));
}

// Un valor vacío es "sin dato" (null), nunca cero.
function aNumero(texto) {
  if (texto === '' || texto == null) return null;
  const n = Number(texto);
  return Number.isFinite(n) ? n : null;
}

// estado: 'cargando' | 'sin_version' | 'lista' | 'error'
export function useVersion() {
  const [estado, setEstado] = useState({ estado: 'cargando' });

  useEffect(() => {
    let activo = true;
    (async () => {
      const id = (await leer('current', 'texto'))?.trim();
      if (!id) return { estado: 'sin_version' };
      const [meta, csv] = await Promise.all([leer(`${id}/meta.json`, 'json'), leer(`${id}/estimates.csv`, 'texto')]);
      if (!meta || !csv) return { estado: 'sin_version', detalle: `La versión ${id} está incompleta.` };
      const filas = parsearCSV(csv).map((f) => ({ ...f, value: aNumero(f.value) }));
      return { estado: 'lista', id, meta, filas };
    })()
      .then((r) => activo && setEstado(r))
      .catch((e) => activo && setEstado({ estado: 'error', detalle: e.message }));
    return () => {
      activo = false;
    };
  }, []);

  return estado;
}
