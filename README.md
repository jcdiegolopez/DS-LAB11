# Laboratorio 11 — MLOps (Observatorio de Turismo, Tikal y Flores)

Pipeline reproducible para estimar los visitantes extranjeros de enero y febrero de 2026 en los tres subdestinos de Tikal y Flores (Petén), con controles de calidad, evaluación temporal, registro de corridas en MLflow y publicación de versiones aprobadas.

El alcance, los supuestos y el diagrama están en [`docs/alcance.md`](docs/alcance.md).

## Qué hace

| Aspecto | Definición |
|---|---|
| Variable | Visitantes extranjeros únicos del mes, por subdestino |
| Series | `Isla De Flores`, `El Remate Y Alrededores Lago`, `Mundo Maya Aeropuerto` (no se suman: comparten personas) |
| Meses estimados | Enero y febrero de 2026, sin cobertura de telefonía |
| Procedimiento | Factor de reparto = visitantes de movilidad / entradas migratorias (Turista + Excursionista) en los meses observados; estimación = migración del mes × factor |
| Referencias | Último valor observado y promedio de los meses anteriores |

Flujo: lectura y huella de las fuentes → controles de calidad (se detiene si falla uno crítico) → preparación → ajuste → evaluación temporal y regla de aceptación → estimación → publicación solo si la regla lo autoriza → tablero, que lee siempre la versión aprobada vigente.

## Estructura

```
config.yaml                 configuración validada (rutas, períodos, umbrales, semilla)
pipeline/
  run.py                    orquestador: python -m pipeline.run
  stages/                   reading, preparation, fitting, estimation
  checks/                   seis controles de calidad y su reporte
  evaluation/               validación temporal, referencias y regla de aceptación
  publish/                  versiones aprobadas, puntero current y restauración
  tracking/                 registro y comparación de corridas en MLflow
  monitoring/               registro por ejecución, monitores y simulacro de fallo
dashboard/                  tablero (React + Plotly, servido con nginx)
docker/                     Dockerfiles del pipeline y del tablero
docker-compose.yml          pipeline, MLflow y tablero
notebooks/                  cuaderno del avance (ejecuta las etapas sobre los datos reales)
tests/                      pruebas unitarias con datos sintéticos
docs/                       alcance, diagrama del flujo y documento del avance
```

`data/raw/`, `runs/`, `approved/` y `mlruns/` se generan localmente y no se versionan.

## Requisitos

- Python 3.14 con `pip` (para ejecutar sin Docker)
- Node 22 o superior (solo para desarrollar el tablero sin Docker)
- Docker con Docker Compose (para el despliegue local completo)
- Los datos institucionales (no se publican; ver abajo)

Se recomienda un entorno virtual:

```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Datos

El repositorio incluye el paquete de datos entregado por el curso como `data/OneDrive_2026-10-29.zip`. Los datos son institucionales y de uso exclusivamente académico: el repositorio debe permanecer privado.

Para dejarlos donde espera la configuración:

```
unzip data/OneDrive_2026-10-29.zip -d data/raw
```

Eso crea `data/raw/Datos Inguat/`, ruta configurada en `config.yaml` (`paths.data_dir`). La carpeta `data/raw/` no se versiona.

## Ejecución

```
python -m pipeline.run --config config.yaml
```

Código de salida:

| Código | Significado |
|---|---|
| 0 | La ejecución terminó y la versión se publicó |
| 1 | Falló un control crítico o una etapa; no se tocó la versión aprobada |
| 2 | Terminó, pero la regla de aceptación no autorizó la publicación; no se tocó la versión aprobada |

Cada ejecución crea su carpeta en `runs/<run_id>/` con el reporte de calidad, la evaluación, las estimaciones, los parámetros del modelo y la configuración usada.

## Evaluación temporal y regla de aceptación

La validación usa una ventana creciente: para cada mes de `evaluation.eval_months` el factor se ajusta solo con los meses observados anteriores (al menos `evaluation.min_train_months`), y las referencias simples ven exactamente los mismos meses. Con un mínimo de 3 meses los evaluables son dic 2025 y mar–jun 2026; jul–ago 2026 no, porque la migración termina en junio de 2026. Enero y febrero de 2026 no tienen observación y nunca entran en un error.

Se calculan MAE y RMSE del factor y de cada referencia, global y por subdestino. Quedan en `runs/<run_id>/evaluation.csv` (cada mes, subdestino, valor observado y cada predicción) y `evaluation.json` (métricas, cada condición de la regla y la decisión), y se registran en MLflow.

La regla se fijó en `config.yaml` antes de ver los resultados. La versión se publica solo si se cumplen las tres condiciones:

| Condición | Umbral | Justificación |
|---|---|---|
| Todas las predicciones de los meses evaluados son finitas y no negativas | — | Una predicción inválida no se puede publicar |
| MAE del factor / MAE de la mejor referencia simple | ≤ `thresholds.max_mae_ratio_vs_baseline` = 1.0 | Con solo cinco meses evaluables no se exige ganar por un margen, pero el procedimiento no debe ser peor que una referencia trivial |
| MAE global del factor | ≤ `thresholds.max_mae` = 2,000 visitantes | Los meses evaluados van de unos 4,900 a 13,200 visitantes por subdestino (media cercana a 7,700); 2,000 es alrededor de una cuarta parte del nivel típico |

Si la regla no se cumple, la ejecución termina con código 2, deja la advertencia `acceptance rule not met` con la condición que falló y no toca la versión aprobada.

**Resultado con los datos actuales:** el factor tiene un MAE de 1,996 visitantes, frente a 1,719 del último valor observado (razón 1.16). Cumple el umbral absoluto, pero no la comparación con la referencia, así que la versión no se publica. El error se concentra en marzo de 2026, cuando la proporción de extranjeros captada por la telefonía casi se duplica respecto de los meses previos. En diciembre el error del factor es menor de 4 % en los tres subdestinos y en junio menor de 9 %. Con solo cinco meses evaluables este resultado es poco robusto.

## Versiones aprobadas

Cada versión aprobada se guarda en `approved/<run_id>/` (`estimates.csv` y `meta.json`). El archivo `approved/current` contiene el identificador de la versión vigente, y es lo único que lee el tablero. La versión nueva se escribe completa en una carpeta temporal y solo entonces se mueve el puntero. Las versiones anteriores se conservan.

```
python -m pipeline.publish.restore --list          # versiones; * marca la vigente
python -m pipeline.publish.restore --to <run_id>   # volver a una versión anterior
```

Si todavía no existe ninguna versión aprobada, `approved/current` no existe y el tablero debe indicar que las estimaciones no están disponibles.

## Registro de corridas (MLflow)

Cada ejecución, exitosa o fallida, queda registrada en el experimento `lab11-tikal-flores` con el commit de Git, la huella de las fuentes, los parámetros, las métricas, el resultado de los controles y los archivos. Una ejecución fallida se marca `FAILED` con su causa y no registra métricas que no llegó a calcular.

El almacenamiento es una base SQLite en `mlruns/mlflow.db` (esta versión de MLflow no admite el almacenamiento simple en carpeta). Para ver las corridas:

```
mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db
```

y abrir http://127.0.0.1:5000. Para comprobar que dos corridas con los mismos datos y configuración son equivalentes:

```
python -m pipeline.tracking.compare <run_a> <run_b> --rtol 1e-9
```

Compara parámetros, métricas, commit y estimaciones, y termina con código 0 si son equivalentes.

## Monitoreo

Cada ejecución, exitosa o fallida, deja `runs/<run_id>/run_log.json` y `run_log.md` con el inicio y el fin, la duración y el resultado de cada etapa (`ok`, `blocked` si un control crítico la detuvo, `failed` si lanzó un error), las advertencias, los errores, el resultado de la publicación (versión aprobada antes y después) y los tres monitores. Además agrega una línea a `runs/monitoring_log.jsonl`, el historial que también registra cada restauración de versión. Ambos archivos se adjuntan a la corrida en MLflow.

| Monitor | Qué revisa | Alerta cuando |
|---|---|---|
| Actualización (`freshness`) | El último mes de cada fuente frente a `coverage.expected_last_period` | Una fuente no llega al mes esperado, trae meses posteriores que la configuración no usa, o la versión aprobada se construyó con otras fuentes y esta ejecución no la reemplazó |
| Calidad (`quality`) | Filas, faltantes, claves duplicadas y meses cubiertos frente a la ejecución anterior | Las filas cambian más de `monitoring.max_row_change_ratio`, los faltantes de una columna suben más de `monitoring.max_missing_ratio_increase`, aparecen duplicados o se pierde un mes |
| Resultados (`results`) | Las estimaciones de la ejecución | Hay valores negativos o no finitos, o una estimación cambia más de `thresholds.max_period_change_ratio` frente al mes anterior o frente a la versión aprobada |

Los monitores solo alertan: las alertas se imprimen como `alert:` y quedan en el registro, pero no cambian el código de salida ni bloquean la publicación. Eso lo deciden los controles de calidad y la regla de aceptación. La primera ejecución no tiene con qué comparar y queda como línea base del monitor de calidad.

## Simulacro de fallo controlado

```
python -m pipeline.monitoring.drill --mode duplicate_key
```

Copia las fuentes en `runs/drill-<fecha>/data`, daña la copia, ejecuta el pipeline sobre ella, verifica que la versión aprobada siga vigente y con los mismos archivos, y vuelve a ejecutar con las fuentes originales (la corrección). La evidencia queda en `evidence/fault_drill_<modo>_<fecha>.md`. Los archivos originales no se modifican.

| Modo | Daño | Control que debe detenerlo |
|---|---|---|
| `missing_column` | Quita la columna `pais` de la hoja de movilidad | `columns_types` |
| `duplicate_key` | Duplica una fila de movilidad | `uniqueness` |
| `zero_denominator` | Pone en cero la migración de enero de 2026 | `values_denominators` |

Termina con código 0 si el fallo se detectó, la versión aprobada se conservó y la corrida corregida pasó la validación. Para demostrar la recuperación completa conviene correrlo cuando ya existe una versión aprobada, y después probar `python -m pipeline.publish.restore --to <run_id>` para volver a una versión anterior.

## Contrato entre etapas

Cada etapa es un módulo con `run(cfg, state)` que lee y escribe en `PipelineState` (`pipeline/contracts.py`):

| Etapa | Lee | Deja en `state` |
|---|---|---|
| `stages.reading` | archivos de datos | `source_fingerprint`, `raw` (`mobility` y `migration`) |
| `checks.runner` | `raw` | `check_results`, `warnings`; escribe `quality_report.json` y `.md` |
| `stages.preparation` | `raw` | `prepared` |
| `stages.fitting` | `prepared` | `model` (un diccionario o un dataclass; se guarda como JSON) |
| `evaluation.runner` | `prepared` | `metrics` (nombres de métricas con letras, números, `_`, `-`, `.` o espacio; valores finitos) y `accepted` (`True` o `False`); escribe `evaluation.csv` y `evaluation.json` |
| `stages.estimation` | `prepared`, `model` | `estimates` (columnas `target`, `subdestination`, `period`, `value`, `unit`, `kind`) |
| `publish.runner` | `estimates`, `accepted` | `published`, `published_dir`; estado `REJECTED` si `accepted` no es `True` |

`kind` solo puede ser `observed` o `estimated`; un mes sin dato queda con `value` vacío y nunca en cero. La publicación rechaza estimaciones con valores negativos, no finitos o repetidos antes de mover el puntero.

## Pruebas

```
python -m pytest
```

## Configuración

Todo lo variable está en `config.yaml`: rutas, fuentes, destino, cobertura esperada, meses evaluados, procedimiento y umbrales. El archivo se valida al cargarse y rechaza claves desconocidas, meses mal formados y combinaciones de períodos incoherentes.

## Tablero

El tablero (`dashboard/`, adaptado del Lab 10: React, Plotly y la misma paleta) lee en el navegador `approved/current` y, con ese identificador, `approved/<run_id>/estimates.csv` y `meta.json`. No lee nada de `runs/`: solo muestra versiones aprobadas.

- Una serie por subdestino, elegida con botones; no hay total de Petén.
- Lo observado va en azul. Las estimaciones van en naranja, con rombos y la etiqueta «Estimación».
- Enero y febrero de 2026 aparecen como «Sin dato» en la serie observada, con una franja gris; nunca como cero.
- Declara los meses con cobertura y los vacíos, la fecha de actualización, la versión, el MAE frente a la mejor referencia y las limitaciones.
- Si no existe `approved/current`, muestra «Estimaciones no disponibles».

Para desarrollarlo sin Docker:

```
cd dashboard
npm install
npm run dev        # http://localhost:5173, sirve ../approved (o APPROVED_DIR)
```

Al restaurar una versión con `pipeline.publish.restore`, basta recargar la página: el puntero se lee sin caché.

## Docker

`docker-compose.yml` define tres servicios. Los datos, `runs/`, `approved/` y `mlruns/` se montan desde el host; ninguno se copia a una imagen (`.dockerignore` los excluye).

| Servicio | Imagen | Puerto | Volúmenes |
|---|---|---|---|
| `pipeline` | `docker/pipeline.Dockerfile` (Python 3.14) | — | `data/raw` (solo lectura), `runs`, `approved`, `mlruns` |
| `mlflow` | la misma imagen, `mlflow server` | 5000 | `mlruns` |
| `dashboard` | `docker/dashboard.Dockerfile` (build con Node, servido con nginx) | 8080 | `approved` (solo lectura) |

El pipeline es un trabajo que se ejecuta y termina, por eso está en el perfil `jobs` y no arranca con `up`:

```
docker compose --profile jobs build
docker compose up -d                       # tablero en http://localhost:8080, MLflow en http://localhost:5000
GIT_COMMIT=$(git rev-parse HEAD) docker compose run --rm pipeline
docker compose run --rm pipeline python -m pipeline.publish.restore --list
docker compose down
```

En PowerShell, el commit se pasa con `$env:GIT_COMMIT = git rev-parse HEAD` antes de `docker compose run`. El contenedor no tiene el repositorio, así que sin esa variable la corrida queda registrada con commit `unknown`.

MLflow guarda en la base SQLite las rutas absolutas de los archivos adjuntos. El pipeline y MLflow montan `mlruns/` en la misma ruta (`/app/mlruns`) para que esas rutas sean válidas en ambos. Por eso conviene no mezclar en una misma carpeta `mlruns/` corridas hechas en el host y corridas hechas en contenedores: las del host apuntan a rutas de Windows que MLflow, dentro del contenedor, no puede abrir.

## Prueba desde una copia limpia

```
git clone https://github.com/jcdiegolopez/DS-LAB11.git lab11-limpio
cd lab11-limpio
unzip data/OneDrive_2026-10-29.zip -d data/raw
docker compose --profile jobs build
docker compose up -d
docker compose run --rm pipeline
```

El último comando termina con código 2 con los datos actuales (la regla de aceptación no autoriza la publicación), y el tablero muestra «Estimaciones no disponibles». Las corridas quedan en http://localhost:5000, en el experimento `lab11-tikal-flores`. Sin Docker, los pasos equivalentes son `pip install -r requirements.txt`, `python -m pytest` y `python -m pipeline.run --config config.yaml`.

## Limitaciones

- Solo hay 10 meses de movilidad y 8 con migración al mismo tiempo; únicamente 5 son evaluables, así que las métricas son poco robustas.
- El factor supone que la proporción de extranjeros que capta cada subdestino es estable; marzo de 2026 muestra que no siempre lo es.
- No hay un total de Petén: los archivos no lo traen y sumar subdestinos duplicaría personas.
- La migración cambió de clasificación entre 2022 y 2023; el ajuste solo usa meses de 2025–2026, posteriores al cambio.
