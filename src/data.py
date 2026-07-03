def _range(from_number, to_number):
    return list(range(from_number, to_number + 1))


def _booth(number, zone, status, size=None):
    return {
        "number": number,
        "zone": zone,
        "status": status,
        "size": size or ("2.0 x 1.5 m" if zone == "patio" else "2.0 x 1.3 m"),
    }


def _price(zone, booth_type, size, amount, numbers):
    return {
        number: {
            "zone": zone,
            "type": booth_type,
            "size": size,
            "price": amount,
        }
        for number in numbers
    }


FAIR_INFO = {
    "name": "Feria Origen Colombia 2027",
    "dates": "del 2 al 14 de enero de 2027",
    "venue": "Sede UNIBAC",
    "official_site": "https://www.origencolombia.com/",
    "purpose": "conectar talento, tradición y oportunidades que impulsan lo mejor de Colombia.",
    "tagline": "#SoyOrigenColombia",
    "experience_years": "22 años de experiencia",
    "total_fairs": "28 ferias realizadas",
    "total_exhibitors": "más de 1.000 expositores totales",
    "visitors_per_event": "más de 8.000 visitantes por evento",
    "official_fairs": (
        "Feria Origen Colombia Semana Santa 2026, Feria Origen Diciembre 2026 "
        "y Feria Origen Colombia Semana Santa 2027."
    ),
    "registration_form_url": "https://www.origencolombia.com/origen-colombia-2027/#ffff",
    "registration_form_label": "Formulario de inscripción - 29a Feria Origen Colombia Semana Santa 2026",
    "registration_form_note": (
        "El botón 'Inscríbete' de la web oficial lleva al formulario publicado para "
        "la 29a Feria Origen Colombia Semana Santa 2026."
    ),
    "active_fair_public_note": (
        "En la web oficial aparece la 29a Feria Origen Colombia Semana Santa 2026 "
        "con formulario de inscripción. También aparecen anunciadas Feria Origen "
        "Diciembre 2026 y Semana Santa 2027 bajo el texto 'Tejiendo el Origen'."
    ),
    "visitor_summary": (
        "Una feria para descubrir marcas, artesanos, emprendimientos, productos con "
        "identidad colombiana y experiencias culturales."
    ),
    "visitor_photo_invite": (
        "Si la persona viene como turista o visitante, Ori puede animarla a asistir "
        "mostrando la experiencia de ferias anteriores con fotos oficiales cargadas."
    ),
    "previous_fairs_summary": (
        "Las ferias anteriores muestran una experiencia cercana y cultural: visitantes "
        "recorriendo stands, maestros artesanos compartiendo sus piezas, productos de "
        "moda, arte, artesanía, belleza, salud y gastronomía, y el ambiente histórico "
        "del Convento de San Diego en Cartagena."
    ),
    "exhibitor_summary": (
        "Un espacio para que expositores presenten sus productos, conecten con visitantes "
        "y reciban acompañamiento comercial."
    ),
    "ori_mission": (
        "Ori acompaña la decisión: informa con claridad, sugiere opciones reales y abre el camino "
        "hacia la preinscripción o un asesor solo cuando el interés del cliente ya está maduro."
    ),
    "visitor_mode": (
        "Si la persona pregunta por la feria, productos, actividades, ubicación, experiencia o marcas, "
        "Ori actúa como anfitriona para visitantes y turistas. No debe hablarle como expositor."
    ),
    "sales_mode": (
        "Ori adopta personalidad de asesora comercial solo cuando la persona expresa que quiere participar, "
        "exponer, vender, reservar un stand, conocer precios de stand o tiene una marca/emprendimiento."
    ),
    "confirmed_exhibitors_note": (
        "Todavía no hay un listado oficial completo de expositores confirmados por marca. "
        "Mientras tanto, Ori puede orientar por categorías y productos esperados."
    ),
    "products": (
        "arte, artesanía típica, joyería, calzado y vestuario, decoración, anticuarios, "
        "salud y belleza, gastronomía, productos culturales y servicios creativos."
    ),
    "registration_categories": (
        "Arte, Artesanía típica, Joyería, Calzado y vestuario, Decoración, "
        "Anticuarios, Salud y belleza, Gastronomía."
    ),
    "registration_fields": (
        "razón social, nombre del representante, nombre para el stand, ciudad de origen, "
        "WhatsApp, correo electrónico, redes sociales o página web, categoría, productos "
        "a participar, catálogo o imágenes y preguntas o comentarios."
    ),
    "activities": (
        "muestras comerciales, recorridos por stands, experiencias culturales, "
        "activaciones de marca y espacios de networking."
    ),
    "venue_history": (
        "La sede está en el Convento de San Diego, fundado en 1608 y terminado "
        "aproximadamente en 1625. Fue sede de los Franciscanos Recoletos Descalzos "
        "hasta 1821, tuvo varios usos institucionales y en 1976 se estableció como "
        "sede de la Escuela de Bellas Artes. En 2021 fue declarado Bien de Interés "
        "Cultural de Carácter Nacional."
    ),
    "venue_context": (
        "Hoy el edificio es sede de la Institucion Universitaria Bellas Artes y Ciencias "
        "de Bolívar, UNIBAC. Está en la plaza de San Diego, en el centro histórico de "
        "Cartagena, cerca del Sofitel Santa Clara, las Bóvedas, galerías y restaurantes."
    ),
    "nearby_places": (
        "La feria queda en la plaza de San Diego, dentro del centro histórico de Cartagena. "
        "Cerca puedes encontrar el sector de San Diego, las Bóvedas, la muralla, el Sofitel "
        "Santa Clara, galerías, cafés, restaurantes y calles para caminar dentro del centro "
        "histórico. Ori no confirma horarios, precios ni disponibilidad de esos lugares."
    ),
    "arrival_tip": (
        "Para llegar, el visitante puede pedir indicaciones hacia UNIBAC, Convento de San Diego "
        "o plaza de San Diego, en el centro histórico de Cartagena. Es una zona reconocida del "
        "centro histórico y cercana a Las Bóvedas y al Sofitel Santa Clara."
    ),
    "google_maps_url": "https://maps.google.com/?q=10.428161,-75.5473187",
    "arrival_guide": (
        "Si el usuario pregunta cómo llegar, Ori debe actuar como guía local: confirmar que la feria "
        "queda en el Claustro de San Diego / UNIBAC, plaza de San Diego, Centro Histórico de Cartagena; "
        "preguntar desde dónde sale si no lo sabe; y si ya está en Cartagena, sugerir buscar en Maps "
        "'UNIBAC Cartagena' o 'Plaza de San Diego Cartagena'. En taxi o Uber puede pedir Plaza de San Diego "
        "o UNIBAC Bellas Artes. Si está en la Ciudad Amurallada puede caminar según su punto de partida. "
        "Desde Bocagrande el trayecto suele ser corto en taxi o app, dependiendo del tráfico. No inventar tarifas."
    ),
    "entry_cost": (
        "Para visitantes, la entrada se maneja como acceso libre. La web oficial de la edición 2027 no publica un costo de entrada diferente, "
        "así que no se deben inventar valores."
    ),
    "exhibition_spaces": {
        "patio": (
            "Patio de las Artes: espacio de convergencia donde los stands se ubican en "
            "pasillos formando un recorrido circular y continuo. Tiene arquitectura "
            "colonial, arcadas, vigas de madera, ventiladores de techo de gran formato "
            "y acceso directo desde la calle por el zaguán."
        ),
        "salon": (
            "Salón Pierre Daguet: antigua capilla colonial con techos artesonados de "
            "gran altura. Los stands se disponen en bloques e islas centrales para un "
            "recorrido fácil e intuitivo conectado con el patio central. Cuenta con aire "
            "acondicionado y acceso directo desde la calle por el atrio principal."
        ),
    },
    "gallery_sections": "Familia Origen Colombia, Rostros Origen, Visitantes y Nuestro Espacio.",
    "location": (
        "La feria se realiza en la Sede UNIBAC, en el Convento de San Diego, plaza de "
        "San Diego, centro histórico de Cartagena."
    ),
    "human_help": (
        "Por ahora no tengo un asesor disponible para transferirte desde este chat. "
        "Puedo tomar tu nombre, marca si aplica, ciudad y pregunta para dejar clara tu solicitud."
    ),
    "stand_includes": (
        "Todos los stands incluyen 3 muros blancos, excepto los esquineros que incluyen 2 muros blancos. "
        "También incluyen 1 mesa de 120 x 60 cm y 1 estante con 2 puestos de 180 cm."
    ),
}


BOOTHS = (
    [_booth(number, "patio", "available") for number in reversed(_range(40, 45))]
    + [
        _booth(39, "patio", "reserved"),
        _booth(38, "patio", "reserved"),
        _booth(37, "patio", "available"),
    ]
    + [_booth(number, "patio", "unavailable") for number in _range(46, 55)]
    + [
        _booth(36, "patio", "available"),
        _booth(35, "patio", "available"),
        _booth(34, "patio", "available"),
        _booth(33, "patio", "available"),
        _booth(32, "patio", "reserved"),
        _booth(31, "patio", "reserved"),
        _booth(30, "patio", "available"),
        _booth(29, "patio", "available"),
    ]
    + [
        _booth(number, "patio", "reserved" if number == 64 else "available")
        for number in _range(56, 64)
    ]
    + [
        _booth(12, "salon", "reserved", "3.0 + 2.0 x 1.3 m"),
        _booth(11, "salon", "reserved", "3.0 + 2.0 x 1.3 m"),
        _booth(13, "salon", "available"),
        _booth(10, "salon", "available"),
    ]
    + [_booth(number, "salon", "available") for number in [22, 23, 24, 25, 26]]
    + [_booth(27, "salon", "unavailable", "3.0 x 1.3 m")]
    + [_booth(number, "salon", "available") for number in [9, 8, 7, 6, 5, 4, 3]]
    + [
        _booth(2, "salon", "unavailable", "3.0 x 1.3 m"),
        _booth(1, "salon", "unavailable"),
        _booth(28, "salon", "unavailable"),
    ]
    + [_booth(number, "salon", "available") for number in [21, 14, 20, 15, 19, 16]]
    + [
        _booth(18, "salon", "unavailable", "3.0 x 1.3 m"),
        _booth(17, "salon", "unavailable", "3.0 x 1.3 m"),
    ]
)


STAND_PRICES = {}
STAND_PRICES.update(
    _price(
        "patio",
        "Stand general",
        "2.0 x 1.5 m",
        "$3.300.000",
        [46, 47, 48, 49, 50, 51, 52, 53, 54, 55],
    )
)
STAND_PRICES.update(
    _price(
        "patio",
        "Stand especial",
        "2.0 x 1.5 m",
        "$3.700.000",
        [40, 41, 42, 43, 44, 45, 56, 57, 58, 59, 60, 61],
    )
)
STAND_PRICES.update(
    _price(
        "patio",
        "Stand especial",
        "2.0 x 1.5 m",
        "$4.000.000",
        [29, 30, 33, 34, 35, 36, 37, 62, 63],
    )
)
STAND_PRICES.update(
    _price(
        "patio",
        "Stand esquina",
        "2.0 x 1.5 m",
        "$4.300.000",
        [31, 32, 38, 39, 64],
    )
)
STAND_PRICES.update(
    _price(
        "salon",
        "Stand general",
        "2.0 x 1.3 m",
        "$5.000.000",
        [3, 4, 5, 6, 7, 8, 10, 13, 15, 16, 19, 20, 23, 26],
    )
)
STAND_PRICES.update(
    _price(
        "salon",
        "Stand esquinero",
        "2.0 x 1.3 m",
        "$5.500.000",
        [24, 25],
    )
)
STAND_PRICES.update(
    _price(
        "salon",
        "Stand esquinero",
        "3.0 x 1.3 m",
        "$5.500.000",
        [9, 14, 21, 22],
    )
)
STAND_PRICES.update(
    _price(
        "salon",
        "Stand esquinero premium",
        "3.0 x 1.3 m",
        "$6.000.000",
        [2, 17, 18, 27],
    )
)
STAND_PRICES.update(
    _price(
        "salon",
        "Stand Delux",
        "3.0 + 2.0 x 1.3 m",
        "$6.000.000",
        [11, 12],
    )
)
