// Contenedor común: título + "Qué muestra" + "Para qué sirve" + controles + contenido.
export default function TarjetaGrafica({ id, titulo, queMuestra, paraQueSirve, controles, nota, children }) {
  return (
    <section className="tarjeta" id={id}>
      <header className="tarjeta-encabezado">
        <h2>
          {id && <span className="tarjeta-id">{id}</span>} {titulo}
        </h2>
        {queMuestra && <p><strong>Qué muestra:</strong> {queMuestra}</p>}
        {paraQueSirve && <p><strong>Para qué sirve:</strong> {paraQueSirve}</p>}
      </header>
      {controles && <div className="controles">{controles}</div>}
      {children}
      {nota && <p className="nota">{nota}</p>}
    </section>
  );
}
