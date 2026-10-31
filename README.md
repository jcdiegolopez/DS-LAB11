# Laboratorio 11 — MLOps (Observatorio de Turismo, Tikal y Flores)

Pipeline reproducible para estimar los visitantes extranjeros de enero y febrero de 2026 en los tres subdestinos de Tikal y Flores (Petén), con controles de calidad, evaluación temporal, registro de corridas en MLflow y publicación de versiones aprobadas.

El alcance, los supuestos y el diagrama están en [`docs/alcance.md`](docs/alcance.md).

## Estado

En desarrollo. Disponibles: configuración validada, orquestador, controles de calidad, lectura, preparación, ajuste del factor, estimación, referencias simples, publicación de versiones aprobadas, registro en MLflow, monitoreo y simulacro de fallo controlado. Pendientes: la etapa de evaluación temporal con la regla de aceptación, el tablero y Docker.

## Requisitos

- Python 3 con `pip`
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

Cada ejecución crea su carpeta en `runs/<run_id>/` con el reporte de calidad, las estimaciones, los parámetros del modelo y la configuración usada.

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
| `evaluation.runner` | `prepared` | `metrics` (nombres de métricas con letras, números, `_`, `-`, `.` o espacio; valores finitos) y `accepted` (`True` o `False`) |
| `stages.estimation` | `prepared`, `model` | `estimates` (columnas `target`, `subdestination`, `period`, `value`, `unit`, `kind`) |
| `publish.runner` | `estimates`, `accepted` | `published`, `published_dir`; estado `REJECTED` si `accepted` no es `True` |

`kind` solo puede ser `observed` o `estimated`; un mes sin dato queda con `value` vacío y nunca en cero. La publicación rechaza estimaciones con valores negativos, no finitos o repetidos antes de mover el puntero.

## Pruebas

```
python -m pytest
```

## Configuración

Todo lo variable está en `config.yaml`: rutas, fuentes, destino, cobertura esperada, meses evaluados, procedimiento y umbrales. El archivo se valida al cargarse y rechaza claves desconocidas, meses mal formados y combinaciones de períodos incoherentes.

## Notas para Docker

- MLflow guarda en la base SQLite las rutas absolutas de los archivos adjuntos. El servicio del pipeline y el de MLflow deben montar `mlruns/` en la misma ruta dentro del contenedor.
- `mlruns/` y `approved/` deben ser volúmenes para que persistan al recrear los contenedores. Los datos institucionales se montan, nunca se copian a la imagen.
