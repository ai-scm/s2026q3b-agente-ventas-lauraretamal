# Agente de análisis de ventas

Aplicación web de análisis de ventas en español. Permite consultar datos con preguntas en lenguaje natural y ver tablas, gráficos o descargar archivos CSV y Excel.

## Qué hace

1. Recibe una pregunta desde la interfaz de Streamlit.
2. Amazon Bedrock interpreta la intención y prepara un plan estructurado para consultar ventas.
3. Un servidor MCP local ejecuta la consulta en SQLite en modo de solo lectura.
4. La aplicación muestra hasta 50 filas, genera gráficos PNG y/o exporta CSV/XLSX según lo solicitado.
5. Si se configura un bucket S3, guarda y permite recuperar el historial de conversaciones.

El esquema de datos es `ventas(id, vendedor, sede, producto, cantidad, precio, fecha)`. Los ingresos se calculan como `cantidad * precio`; `precio` representa el valor unitario. La base de ejemplo se crea automáticamente con 400 registros reproducibles entre 2025-01-01 y 2026-06-30.

## Requisitos

- Python 3.11 o superior (la imagen Docker utiliza Python 3.11).
- Credenciales de AWS con acceso a Amazon Bedrock y permiso para invocar el modelo seleccionado.
- Docker y Docker Compose, si se elige la ejecución en contenedor.
- Opcional: un bucket S3 y permisos para listar, leer, escribir y borrar objetos si se quiere persistir el historial.

El modelo predeterminado es `amazon.nova-pro-v1:0`. La integración de Bedrock de esta aplicación está configurada para `us-east-1`.

## Configuración de AWS

Desde la raíz del proyecto, crea tu archivo de entorno a partir de la plantilla:

```bash
cp .env.example .env
```

Configura **una** forma de autenticación:

- **Token de Bedrock:** define `AWS_BEARER_TOKEN_BEDROCK` en `.env`.
- **Credenciales AWS estándar:** deja vacío el token y configura un perfil con `aws configure`, variables AWS o credenciales disponibles para boto3. En Docker Compose, el perfil local de `~/.aws` se monta como solo lectura.

Variables disponibles:

| Variable | Uso | Valor predeterminado |
| --- | --- | --- |
| `AWS_BEARER_TOKEN_BEDROCK` | Token bearer para Bedrock; opcional si boto3 encuentra credenciales estándar. | Vacío |
| `BEDROCK_MODEL_ID` | Identificador del modelo de Bedrock. | `amazon.nova-pro-v1:0` |
| `AWS_REGION` | Región declarada para el contenedor. La integración de Bedrock de la app usa `us-east-1`. | `us-east-1` |
| `CHAT_BUCKET_NAME` | Bucket para historial S3. Si está vacío, la persistencia queda deshabilitada. | Vacío |

No compartas ni subas `.env` al repositorio. La plantilla `.env.example` no contiene credenciales.

## Ejecutar localmente

En Linux o macOS, desde el directorio raíz:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # omite este paso si ya creaste .env
streamlit run app.py
```

Abre la URL local que muestra Streamlit (normalmente <http://localhost:8501>). En Windows PowerShell, activa el entorno con `.\.venv\Scripts\Activate.ps1` en lugar de `source .venv/bin/activate`.

Al iniciar, la aplicación crea `data/ventas.db` y `data/ventas.csv` si faltan o si la base no tiene el esquema esperado. También puedes regenerar explícitamente los datos de ejemplo:

```bash
python -m services.database
```

Este comando reemplaza la tabla `ventas` y sobrescribe el CSV de muestra.

## Ejecutar con Docker Compose

Después de configurar `.env` y las credenciales AWS:

```bash
docker compose up --build
```

Abre <http://localhost:8501>. Para detener la aplicación, usa `Ctrl+C`; para eliminar el contenedor, ejecuta `docker compose down`.

Compose publica el puerto 8501, carga `.env` si existe y monta el proyecto en `/app`. También monta `~/.aws` como solo lectura para que el contenedor pueda usar el perfil local. Los archivos de base y resultados se guardan en el directorio del proyecto gracias al montaje.

## Uso de la aplicación

- Escribe preguntas como “¿Cuáles fueron los ingresos por sede?” o “¿Qué producto vendió más unidades?”.
- Para pedir un gráfico o archivo, indícalo explícitamente, por ejemplo: “Grafica los ingresos por vendedor” o “Exporta las ventas por sede a Excel”.
- La interfaz muestra tablas y gráficos, y ofrece un botón para descargar los archivos generados.
- El panel lateral permite crear y abrir conversaciones guardadas. Sin `CHAT_BUCKET_NAME`, los chats permanecen solo en la sesión actual.
- Las referencias a resultados anteriores funcionan dentro de la conversación activa. Al reabrir un chat desde S3, se recupera el texto del historial, pero los resultados de consulta en memoria no se restauran.

## Datos, límites y archivos generados

- `data/ventas.csv`: conjunto de datos de muestra en formato CSV.
- `data/ventas.db`: base SQLite generada localmente; no se versiona.
- `outputs/`: gráficos PNG y archivos CSV/XLSX solicitados por el usuario.
- Las consultas del agente solo admiten `SELECT` o `WITH` y una única sentencia; el cliente MCP las limita a 1000 filas. La interfaz muestra como máximo 50 filas de una tabla.
- Los gráficos y exportaciones usan los resultados de consulta de la conversación. Se aceptan gráficos de barras, líneas y circular.
- El historial en S3 se guarda bajo el prefijo `ventas/`.

## Estructura del proyecto

```text
app.py                       Interfaz Streamlit y ciclo de conversación
ui/                          Componentes de chat y barra lateral
services/sales_agent.py      Planificación y flujo del agente LangGraph
services/mcp_sql.py          Cliente MCP y validación de consultas
services/sqlite_mcp_server.py Servidor MCP de lectura SQLite
services/database.py         Creación de la base y datos de muestra
services/actions.py          Generación de gráficos y exportaciones
services/chat_storage.py     Persistencia opcional del historial en S3
data/ventas.csv              Datos de muestra
outputs/                     Archivos generados
Dockerfile                   Imagen de la aplicación
docker-compose.yml           Configuración de ejecución en contenedor
```

## Solución de problemas

- **No se encuentran credenciales:** configura un perfil/credenciales AWS o el token `AWS_BEARER_TOKEN_BEDROCK` en `.env`.
- **Bedrock deniega la solicitud o el modelo no aparece:** confirma permisos para invocar el modelo, que el modelo esté habilitado en la cuenta y que la región sea `us-east-1`.
- **No se guarda el historial:** configura `CHAT_BUCKET_NAME` y verifica los permisos S3 para el bucket.
- **La base no se puede consultar:** detén la app y ejecuta `python -m services.database` para reconstruir la base de muestra. Esto borra los datos que hayas agregado a `ventas`.

# s2026q3b-agente-ventas-lauraretamal
