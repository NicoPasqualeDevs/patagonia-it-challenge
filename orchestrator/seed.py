from __future__ import annotations

from typing import Any

from orchestrator.instructions import default_instructions


def _kt(ktag_id: str, name: str, value: str) -> dict[str, str]:
    return {"id": ktag_id, "name": name, "value": value}


def seed_agents() -> dict[str, dict[str, Any]]:
    sakura = {
        "id": "agt_sakura",
        "name": "Sakura",
        "type": "menu",
        "goal": "Atender consultas de menú, precios y alérgenos del restaurante japonés",
        "personality": "preciso, cálido y breve",
        "capabilities": ["cart", "reservation", "contact"],
        "ktags": [
            _kt(
                "kt_sakura_ubicacion",
                "ubicacion",
                "Sakura está en Palermo, Honduras 4780, CABA. "
                "Esquina con Armenia. Subte D (Plaza Italia) a 8 cuadras. "
                "Zona peatonal de bares. No tiene sucursal en Belgrano ni Recoleta.",
            ),
            _kt(
                "kt_sakura_horarios",
                "horarios",
                "Martes a domingo 12:00–15:30 y 19:30–23:30. Lunes cerrado. "
                "Último pedido 23:00. Reservas por WhatsApp o en el agente.",
            ),
            _kt(
                "kt_sakura_nigiri",
                "nigiri_salmon",
                "Nigiri de salmón: 2 piezas de arroz sushi con salmón fresco. "
                "Precio $9.800. Contiene pescado y gluten (vinagre de arroz con trigo en algunos lotes: consultar). "
                "No es apto celiaco salvo aviso del turno. ~180 kcal el par.",
            ),
            _kt(
                "kt_sakura_ramen",
                "ramen_tonkotsu",
                "Ramen tonkotsu: caldo de cerdo 12 h, fideos de trigo, chashu, huevo ajitama, nori. "
                "Precio $16.500. Contiene gluten, cerdo, soja y huevo. No apto celiaco ni vegetariano. "
                "Versión picante +$1.200. ~890 kcal.",
            ),
            _kt(
                "kt_sakura_tempura",
                "tempura_moriawase",
                "Tempura moriawase: langostinos, zapallo, berenjena y sweet potato con tentsuyu. "
                "Precio $14.200. Contiene gluten, crustáceos y soja. No apto celiaco. ~620 kcal.",
            ),
            _kt(
                "kt_sakura_edamame",
                "edamame",
                "Edamame al vapor con sal marina. Precio $6.400. Vegano. Sin gluten. "
                "Apto celiaco. ~190 kcal. Opción con togarashi.",
            ),
            _kt(
                "kt_sakura_mochi",
                "mochi_matcha",
                "Mochi de matcha relleno de helado. Precio $5.900. Contiene lácteos y gluten (harina de arroz mezclada en planta). "
                "No se garantiza apto celiaco. ~240 kcal.",
            ),
            _kt(
                "kt_sakura_alergenos",
                "alergenos",
                "Cocina con soja, gluten, pescado, crustáceos, sésamo y huevo. "
                "No hay freidora dedicada sin gluten. El único plato seguro para celiacos es edamame, "
                "si se pide sin togarashi cruzado. Informar alergias al tomar la comanda.",
            ),
            _kt(
                "kt_sakura_promos",
                "promos",
                "Martes y miércoles: 20% en nigiris al mediodía. "
                "Happy hour 19:30–20:30: sake copa $4.500. No combina con reservas de más de 6 personas.",
            ),
        ],
    }

    lima = {
        "id": "agt_lima",
        "name": "Lima de Barrio",
        "type": "menu",
        "goal": "Atender consultas de menú, precios y alérgenos del restaurante peruano",
        "personality": "cercano, entusiasta y concreto",
        "capabilities": ["cart", "reservation", "contact"],
        "ktags": [
            _kt(
                "kt_lima_ubicacion",
                "ubicacion",
                "Lima de Barrio está en Belgrano, Cabildo 2450, CABA. "
                "A 3 cuadras del subte D (Juramento). Terraza al fondo. "
                "No está en Palermo. Delivery en Belgrano, Núñez y Colegiales.",
            ),
            _kt(
                "kt_lima_horarios",
                "horarios",
                "Lunes a sábado 12:00–16:00 y 20:00–00:00. Domingo 12:00–16:30 (solo almuerzo). "
                "Cocina cierra 15:30 y 23:30.",
            ),
            _kt(
                "kt_lima_ceviche",
                "ceviche_clasico",
                "Ceviche clásico: pescado del día, leche de tigre, cebolla morada, camote, choclo. "
                "Precio $18.000. Sin gluten. Apto celiaco. Contiene pescado. "
                "Opción sin ají a pedido. ~320 kcal. No se sirve bien cocido: es crudo marinado.",
            ),
            _kt(
                "kt_lima_lomo",
                "lomo_saltado",
                "Lomo saltado: bife de chorizo, cebolla, tomate, soja, papas fritas y arroz. "
                "Precio $19.400. Contiene gluten (sillao) y soja. No apto celiaco. "
                "Se puede pedir sin soja (pierde el sabor clásico). ~980 kcal.",
            ),
            _kt(
                "kt_lima_aji",
                "aji_de_gallina",
                "Ají de gallina: pechuga desmenuzada en salsa de ají amarillo, pecanas, papa y arroz. "
                "Precio $15.800. Contiene lácteos, frutos secos y gluten (pan en la salsa). "
                "No apto celiaco. ~740 kcal.",
            ),
            _kt(
                "kt_lima_causa",
                "causa_limena",
                "Causa limeña de pollo: papa amarilla, ají amarillo, palta y pollo. "
                "Precio $11.200. Sin gluten. Apto celiaco si se confirma el lote de palta. "
                "Contiene huevo en la mayonesa. Versión vegetariana de palta y palmito $10.400. ~410 kcal.",
            ),
            _kt(
                "kt_lima_pisco",
                "pisco_sour",
                "Pisco sour: pisco quebranta, limón, clara de huevo, jarabe. Precio $7.800. "
                "Contiene huevo. Sin gluten. ~210 kcal. No hay versión sin alcohol.",
            ),
            _kt(
                "kt_lima_alergenos",
                "alergenos",
                "Cocina con pescado, soja, gluten, lácteos, huevo y pecanas. "
                "Platos aptos celiaco habituales: ceviche clásico y causa limeña (confirmar turno). "
                "El lomo saltado y el ají de gallina no son aptos celiaco. Freidora compartida para papas.",
            ),
            _kt(
                "kt_lima_promos",
                "promos",
                "Jueves: 2x1 en pisco sour de 20:00 a 21:00. "
                "Almuerzo ejecutivo mar-vie $16.900 (entrada + fondo + chicha). No incluye ceviche.",
            ),
        ],
    }

    nutri = {
        "id": "agt_nutri",
        "name": "NutriGuía",
        "type": "nutrition",
        "goal": "Orientar comidas según objetivos nutricionales y alérgenos, usando la carta de los locales",
        "personality": "claro, prudente y práctico",
        "capabilities": ["contact"],
        "ktags": [
            _kt(
                "kt_nutri_celiaquia",
                "celiaquia",
                "Celiaco: evitar gluten (trigo, cebada, centeno, soja con trigo, pan en salsas, fideos de ramen, tempura, sillao). "
                "En Sakura el único plato habitualmente seguro es edamame. "
                "En Lima de Barrio: ceviche clásico y causa limeña (confirmar el turno). "
                "No recomendar ramen, tempura, lomo saltado ni ají de gallina.",
            ),
            _kt(
                "kt_nutri_hiposodico",
                "hiposodico",
                "Dieta hiposódica: evitar caldos largos, sillao, tentsuyu, ceviche (leche de tigre salada) y snacks con sal marina. "
                "Mejor opción relativa: causa limeña (pedir sin extra de sal) o nigiri de salmón sin salsa extra. "
                "El ramen tonkotsu es alto en sodio (~2.400 mg). Edamame pedir sin sal extra.",
            ),
            _kt(
                "kt_nutri_calorico",
                "deficit_calorico",
                "Déficit calórico: priorizar ceviche (~320 kcal), edamame (~190), nigiri de salmón (~180 el par) "
                "o causa (~410). Evitar ramen (~890), lomo saltado (~980) y ají de gallina (~740). "
                "Pisco sour y mochi suman calorías vacías.",
            ),
            _kt(
                "kt_nutri_proteico",
                "alto_proteico",
                "Alto proteico: lomo saltado (carne), ají de gallina (pollo), ceviche (pescado), nigiri de salmón, "
                "ramen con chashu. Causa de pollo es intermedia. Edamame aporta proteína vegetal (~18 g).",
            ),
            _kt(
                "kt_nutri_vegetariano",
                "vegetariano",
                "Vegetariano: en Sakura, edamame y consultar tempura de vegetales (lleva tentsuyu de pescado a veces: pedir sin salsa). "
                "Ramen y nigiri no son vegetarianos. En Lima: causa vegetariana de palta y palmito. "
                "Ceviche, lomo y ají no son vegetarianos. Pisco sour sí (lleva huevo: ovo-vegetariano).",
            ),
            _kt(
                "kt_nutri_disclaimer",
                "disclaimer",
                "Esto no reemplaza consulta médica. Las kcal son estimadas. "
                "Siempre cruzar con la carta actual del local porque el RAG de menú puede haber cambiado.",
            ),
        ],
    }

    geo = {
        "id": "agt_geo",
        "name": "Dónde Comer",
        "type": "geo",
        "goal": "Recomendar dónde comer en CABA según barrio y preferencia de cocina",
        "personality": "directo, local y útil",
        "capabilities": ["contact"],
        "ktags": [
            _kt(
                "kt_geo_palermo",
                "palermo",
                "Palermo: zona de Honduras y Armenia, bares y cocina de autor. "
                "Acá está Sakura (japonés, Honduras 4780). "
                "Si el usuario está en Palermo y quiere peruano, Lima de Barrio queda lejos (Belgrano, ~25–35 min). "
                "Recoleta queda a ~20 min al sur-este.",
            ),
            _kt(
                "kt_geo_belgrano",
                "belgrano",
                "Belgrano: Cabildo y Juramento, residencial con oferta de almuerzo. "
                "Acá está Lima de Barrio (peruano, Cabildo 2450). "
                "Sakura (Palermo) queda a ~25–35 min en bondi/subte D. "
                "Delivery de Lima cubre Belgrano, Núñez y Colegiales.",
            ),
            _kt(
                "kt_geo_recoleta",
                "recoleta",
                "Recoleta: Café Andino (Av. Callao 1240) para café y facturas. "
                "No hay sucursal de Sakura ni de Lima de Barrio en Recoleta. "
                "Japonés más cercano del catálogo: Sakura en Palermo (~20 min). "
                "Peruano más cercano del catálogo: Lima de Barrio en Belgrano (~30 min).",
            ),
            _kt(
                "kt_geo_criterios",
                "criterios",
                "Reglas: no inventar restaurantes. Recomendá UN solo local activo. "
                "El orquestador redirige el flujo al agente de menú de ese local. "
                "Si no hay ninguno activo, el orquestador habilita uno de reserva antes de preguntarte. "
                "Priorizar el barrio que diga el usuario. Si pide cocina + zona y no hay match, "
                "ofrecer el más cercano de los activos y decir el tiempo estimado.",
            ),
        ],
    }

    andino = {
        "id": "agt_andino",
        "name": "Café Andino",
        "type": "menu",
        "goal": "Atender consultas de menú y reservas",
        "personality": "cálido y concreto",
        "capabilities": ["contact"],
        "ktags": [
            _kt(
                "kt_andino_ubicacion",
                "ubicacion",
                "Café Andino está en Recoleta, Av. Callao 1240, CABA. Mesa en vereda. "
                "No es restaurante de almuerzo pesado: café de especialidad y facturas.",
            ),
            _kt(
                "kt_andino_horarios",
                "horarios",
                "Lunes a viernes 8:00–19:00. Sábados 9:00–14:00. Domingo cerrado.",
            ),
            _kt(
                "kt_andino_menu",
                "menu_del_dia",
                "Menú del día: café de especialidad (origen Salta o Colombia según tostada) "
                "con medialuna de manteca o tostado de jamón y queso. Precio combo $7.200. "
                "Medialuna sola $1.400. Flat white $4.900.",
            ),
            _kt(
                "kt_andino_cafe",
                "cafe_especialidad",
                "Café de especialidad: espresso, americano, flat white, filtrado V60. "
                "Leche de avena sin cargo extra. Grano de especialidad, no blend comercial.",
            ),
            _kt(
                "kt_andino_medialunas",
                "medialunas",
                "Medialunas de manteca horneadas en el local. Precio $1.400. "
                "Contienen gluten y lácteos. No hay versión sin TACC.",
            ),
        ],
    }

    agents = {
        sakura["id"]: sakura,
        lima["id"]: lima,
        nutri["id"]: nutri,
        geo["id"]: geo,
        andino["id"]: andino,
    }
    for agent in agents.values():
        agent["instructions"] = default_instructions(
            name=agent["name"],
            agent_type=str(agent.get("type") or "menu"),
            personality=str(agent.get("personality") or ""),
        )
    return agents
