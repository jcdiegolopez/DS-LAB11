# Laboratorio 11 — MLOps (Observatorio de Turismo, Tikal y Flores)

Pipeline reproducible para estimar los visitantes extranjeros de enero y febrero de 2026 en los tres subdestinos de Tikal y Flores (Petén), con controles de calidad, evaluación temporal y publicación de versiones aprobadas.

El alcance, los supuestos y el diagrama están en [`docs/alcance.md`](docs/alcance.md).

## Estado

En desarrollo (avance del 29 de octubre de 2026). Disponibles: configuración validada, orquestador y pruebas. Las etapas de lectura, controles, preparación, ajuste, evaluación y publicación se incorporan por módulos.

## Requisitos

- Python 3 con `pip`
- Los datos institucionales (no se publican; ver abajo)

```
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

El comando termina con código 0 si la ejecución fue exitosa y con 1 si falló un control crítico o una etapa.

## Pruebas

```
python -m pytest
```

## Configuración

Todo lo variable está en `config.yaml`: rutas, fuentes, destino, cobertura esperada, meses evaluados, procedimiento y umbrales. El archivo se valida al cargarse y rechaza claves desconocidas, meses mal formados y combinaciones de períodos incoherentes.
