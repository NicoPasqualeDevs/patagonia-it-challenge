# Work Order Orchestrator

Componente que recibe un work order, lo interpreta con un LLM, arma un plan de acciones, las ejecuta, observa el resultado y decide el siguiente paso. Incluye una plataforma de agentes con RAG editable (ktags) e instrucciones de comportamiento por agente.

## Instalación local

Requisitos: Python 3.11+ y Node 18+.

```bash
python -m venv .venv
```

Activar el entorno virtual:

```bash
# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

Instalar dependencias de backend y configurar el entorno:

```bash
pip install -r requirements.txt
cp .env.example .env
```

El `.env` de testeo queda así (también está en `.env.example`):

Datos obligatorios en el env :

OPENAI_API_KEY=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

OPENAI_MODEL=gpt-4o-mini

Ejecución por consola:

**CLI** (con el venv activado, desde la raíz del repo):

```bash
python -m orchestrator.cli examples/work_order_ok.json
python -m orchestrator.cli examples/work_order_incomplete.json --text
python -m orchestrator.cli examples/work_order_flaky.json
python -m orchestrator.cli examples/work_order_sakura.json
python -m orchestrator.cli examples/work_order_nutrition.json
python -m orchestrator.cli examples/work_order_geo.json
python -m orchestrator.cli examples/work_order_suggest.json
python -m orchestrator.cli examples/work_order_reserve.json
python -m orchestrator.cli examples/work_order_dollar.json
python -m orchestrator.cli examples/work_order_weather.json
python -m orchestrator.cli examples/work_order_holiday.json
python -m orchestrator.cli examples/work_order_foodfacts.json
python -m orchestrator.cli examples/work_order_geocode.json
```

**UI**. Terminal 1:

Opcion 2: Ejecutar el front

Instalar el front:

```bash
cd frontend
npm install
cd ..
```

Terminal 1:

```bash
uvicorn orchestrator.api:app --reload --port 8080
```

Terminal 2:

```bash
cd frontend
npm run dev
```

Abrir http://localhost:5173.

- **Orquestador:** cargar un ejemplo, ejecutar, ver timeline + historial.
- **Agentes:** pool en reserva/activos, editar ktags e instrucciones, y chatear (solo activos).

Las trazas JSONL quedan en `traces/run-<id>.jsonl`. El registro de agentes se persiste en `data/platform.json`.

## Agentes semilla

Tres tipos, cinco agentes de dominio:

| Id           | Nombre         | Tipo      | Rol                                                            |
| ------------ | -------------- | --------- | -------------------------------------------------------------- |
| `agt_sakura` | Sakura         | menu      | Carta japonesa en Palermo                                      |
| `agt_lima`   | Lima de Barrio | menu      | Carta peruana en Belgrano                                      |
| `agt_nutri`  | NutriGuía      | nutrition | Orientación nutricional sobre esos locales                     |
| `agt_geo`    | Dónde Comer    | geo       | Elige un local activo y redirige el flujo a ese agente de menú |
| `agt_andino` | Café Andino    | menu      | Café y facturas en Recoleta                                    |

Cada ktag es un par `name` / `value`. NutriGuía también recupera platos y alérgenos de los menús; Dónde Comer recupera las ktags `ubicacion` de los locales **activos**. Si el usuario pide sugerencia y no nombra un local, el runtime activa Dónde Comer: elige un menú en turno, y si no hay ninguno habilita uno de reserva; después redirige el flujo a ese agente de menú para que atienda la carta. Si editás el menú o la dirección, las recomendaciones cambian.

Al arrancar, **Lima de Barrio** y **Café Andino** quedan en **reserva**; Sakura, NutriGuía y Dónde Comer arrancan **activos**. El intérprete recibe el roster (`id`, `name`, `goal`) y, si el work order encaja por nombre o por descripción, puede promover un agente de reserva a activo. El `goal` se usa como ktag preliminar `perfil` (nombre + descripción) en el RAG, además de los ktags reales. El chat de la UI solo está habilitado en activos.

Ejemplo de match por especialidad (sin `agent_id`): `examples/work_order_reserve.json`.

## Decisiones

- Loop explícito interpretar → planificar → ejecutar → observar → decidir. Sin grafo ni framework de workflows.
- IA en interpretación, planificación y respuesta RAG (`gpt-4o-mini` + embeddings `text-embedding-3-small`).
- Runtime: validación, reintento solo si un agente o una tool falla de verdad (o si el agente está en reserva y hay que activarlo), y fallback a ticket de soporte.
- `execute_agent` usa RAG y solo corre contra un agente activo. Si está en reserva, el runtime lo habilita y sigue.
- APIs públicas sin key (el planner las llama antes del mensaje de prueba; el chat también las usa si el usuario pregunta): clima Open-Meteo, dólar DolarAPI, feriados ArgentinaDatos, nutrición Open Food Facts, geocodificación USIG, hora WorldTimeAPI.
- Pool de agentes: reserva vs activo (en memoria, por run). No se persiste en `platform.json`.
- Store de agentes compartido entre runs (JSON). Runs del orquestador siguen en memoria.
- Front: historial de work orders + listas Activos/Reserva + editor de ktags e instrucciones + chat de prueba.

## Supuestos

- El modelo (`gpt-4o-mini` por defecto) está disponible y responde JSON estructurado.
- Los agentes semilla existen al arrancar (se crean si no está `data/platform.json`).
- Si faltan datos críticos (quién es el cliente), no se inventan IDs: el run termina en fallo/parcial con recomendación.

Librerías: `langchain-openai`, `pydantic`, `fastapi`, `uvicorn`, `python-dotenv`. Front: React 18, Vite, TypeScript.
