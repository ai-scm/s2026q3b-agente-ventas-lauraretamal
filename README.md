# Agente de análisis de datos

Aplicación web en español para consultar datos con preguntas naturales y obtener tablas, gráficos o archivos CSV y Excel. Incluye una base de ventas de ejemplo y permite subir archivos CSV propios.

## Requisitos

- Python 3.11 para ejecución local, igual que la imagen Docker del proyecto.
- Credenciales AWS con permiso para invocar el modelo Amazon Bedrock configurado.
- Opcional: Docker y Docker Compose.

El modelo predeterminado es `amazon.nova-pro-v1:0` y la aplicación usa la región `us-east-1`.

## Configurar AWS

```bash
cp .env.example .env
```

Configura en `.env` una de estas opciones:

- `AWS_BEARER_TOKEN_BEDROCK`: token bearer de Bedrock.
- Credenciales AWS estándar disponibles para boto3, por ejemplo un perfil configurado con `aws configure`.

`BEDROCK_MODEL_ID` permite elegir el identificador del modelo. No compartas ni subas `.env` al repositorio.

## Ejecutar localmente

Desde la raíz del proyecto, crea el entorno virtual, instala las dependencias y prepara la configuración de AWS:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Abre en el navegador la dirección que muestra Streamlit, normalmente <http://localhost:8501>.

## Ejecutar con Docker Compose

Configura AWS y ejecuta:

```bash
docker compose up --build
```

Abre <http://localhost:8501>. Compose monta el proyecto en el contenedor, por lo que los espacios de trabajo permanecen guardados localmente aunque se detenga el contenedor. Detén la aplicación con `Ctrl+C` y elimina el contenedor con `docker compose down`.

## Usar bases propias

En la barra lateral, escribe un nombre para el espacio de trabajo, selecciona un archivo CSV y pulsa **Crear espacio**. La aplicación crea una base SQLite para ese archivo y abre un chat nuevo asociado a esa base. Los encabezados se convierten a nombres sencillos para poder consultarlos con fiabilidad; por ejemplo, `Fecha de venta` pasa a `fecha_de_venta`.

El selector de bases permite cambiar entre el conjunto de ejemplo y los archivos subidos. Cada espacio mantiene conversaciones separadas; dentro de él se pueden crear varios chats. Las conversaciones se guardan automáticamente en el equipo que ejecuta la aplicación y se pueden reabrir desde la barra lateral. Los resultados anteriores también se conservan para permitir preguntas de seguimiento al reabrir un chat.

## Cómo funciona

1. `app.py` prepara la base de ejemplo y carga el espacio activo.
2. `services/prompt.py` describe el esquema activo y da instrucciones al agente.
3. `services/sales_agent.py` usa Amazon Bedrock para interpretar la pregunta y decidir qué consulta o acción realizar.
4. `services/mcp_sql.py` valida las consultas de solo lectura y las envía al servidor MCP de ese espacio.
5. `services/sqlite_mcp_server.py` consulta SQLite con un máximo de 1000 filas.
6. `services/actions.py` genera los gráficos PNG y archivos CSV/XLSX solicitados.
7. `ui/chat.py` presenta los resultados y `services/chat_storage.py` guarda localmente el chat y sus resultados.

Las consultas admiten solo `SELECT` o `WITH` y una sentencia a la vez. La interfaz muestra un máximo de 50 filas. Los gráficos admitidos son barras, líneas y circulares.

## Archivos y datos

- `data/ventas.csv` y `data/ventas.db`: base de ventas de ejemplo.
- `data/workspaces/`: CSV subidos, bases SQLite, conversaciones, resultados y archivos generados, organizados por espacio de trabajo. Esta carpeta no se versiona.
- `outputs/`: conserva los artefactos de ejecuciones anteriores de la base de ejemplo; los nuevos se guardan con su espacio de trabajo.
- `ui/`: componentes de presentación.
- `services/`: base de datos, agente, conexión MCP, acciones y persistencia local.
- `tests/`: pruebas automatizadas.
