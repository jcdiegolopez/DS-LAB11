import { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';

// Fechas y números en español en ejes, selector de rango y hover.
Plotly.register({
  moduleType: 'locale',
  name: 'es',
  dictionary: {
    Autoscale: 'Escala automática', 'Reset axes': 'Restablecer ejes', 'Zoom in': 'Acercar',
    'Zoom out': 'Alejar', Pan: 'Desplazar', Zoom: 'Zoom', 'Download plot as a png': 'Descargar como PNG',
  },
  format: {
    days: ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'],
    shortDays: ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'],
    months: ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'],
    shortMonths: ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
    date: '%d/%m/%Y',
    decimal: '.',
    thousands: ',',
  },
});

// Componente React mínimo sobre Plotly (versión dist-min, ligera).
// Expone los eventos que usan los enlaces entre gráficas: clic, cambio de zoom y selección.
export default function Plot({ data, layout, config, style, onClick, onRelayout, onSelected }) {
  const ref = useRef(null);
  const handlers = useRef({});
  handlers.current = { onClick, onRelayout, onSelected };

  useEffect(() => {
    const el = ref.current;
    Plotly.react(el, data, layout, config);
  }, [data, layout, config]);

  useEffect(() => {
    const el = ref.current;
    const clic = (e) => handlers.current.onClick?.(e);
    const relayout = (e) => handlers.current.onRelayout?.(e);
    const seleccion = (e) => handlers.current.onSelected?.(e);
    const redimensionar = () => Plotly.Plots.resize(el);
    // Los eventos se registran después del primer dibujo.
    const t = setTimeout(() => {
      el.on?.('plotly_click', clic);
      el.on?.('plotly_relayout', relayout);
      el.on?.('plotly_selected', seleccion);
    }, 0);
    window.addEventListener('resize', redimensionar);
    return () => {
      clearTimeout(t);
      window.removeEventListener('resize', redimensionar);
      Plotly.purge(el);
    };
  }, []);

  return <div ref={ref} style={style} />;
}
