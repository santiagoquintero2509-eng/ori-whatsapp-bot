def _range(from_number, to_number):
    return list(range(from_number, to_number + 1))


def _booth(number, zone, status, size=None):
    return {
        "number": number,
        "zone": zone,
        "status": status,
        "size": size or ("2.0 x 1.5 m" if zone == "patio" else "2.0 x 1.3 m"),
    }


FAIR_INFO = {
    "name": "Feria Origen Colombia 2027",
    "dates": "del 2 al 14 de enero de 2027",
    "venue": "Sede UNIBAC",
    "official_site": "https://www.origencolombia.com/",
    "purpose": "conectar talento, tradicion y oportunidades que impulsan lo mejor de Colombia.",
    "tagline": "#SoyOrigenColombia",
    "experience_years": "22 anos de experiencia",
    "total_fairs": "28 ferias realizadas",
    "total_exhibitors": "mas de 1.000 expositores totales",
    "visitors_per_event": "mas de 8.000 visitantes por evento",
    "official_fairs": (
        "Feria Origen Colombia Semana Santa 2026, Feria Origen Diciembre 2026 "
        "y Feria Origen Colombia Semana Santa 2027."
    ),
    "registration_form_url": "https://www.origencolombia.com/origen-colombia-semana-santa/",
    "registration_form_label": "Formulario de inscripcion - 29a Feria Origen Colombia Semana Santa 2026",
    "registration_form_note": (
        "El boton 'Inscribete' de la web oficial lleva al formulario publicado para "
        "la 29a Feria Origen Colombia Semana Santa 2026."
    ),
    "active_fair_public_note": (
        "En la web oficial aparece la 29a Feria Origen Colombia Semana Santa 2026 "
        "con formulario de inscripcion. Tambien aparecen anunciadas Feria Origen "
        "Diciembre 2026 y Semana Santa 2027 bajo el texto 'Tejiendo el Origen'."
    ),
    "visitor_summary": (
        "Una feria para descubrir marcas, artesanos, emprendimientos, productos con "
        "identidad colombiana y experiencias culturales."
    ),
    "exhibitor_summary": (
        "Un espacio para que expositores presenten sus productos, conecten con visitantes "
        "y reciban acompanamiento comercial."
    ),
    "products": (
        "arte, artesania tipica, joyeria, calzado y vestuario, decoracion, anticuarios, "
        "salud y belleza, gastronomia, productos culturales y servicios creativos."
    ),
    "registration_categories": (
        "Arte, Artesania tipica, Joyeria, Calzado y vestuario, Decoracion, "
        "Anticuarios, Salud y belleza, Gastronomia."
    ),
    "registration_fields": (
        "razon social, nombre del representante, nombre para el stand, ciudad de origen, "
        "WhatsApp, correo electronico, redes sociales o pagina web, categoria, productos "
        "a participar, catalogo o imagenes y preguntas o comentarios."
    ),
    "activities": (
        "muestras comerciales, recorridos por stands, experiencias culturales, "
        "activaciones de marca y espacios de networking."
    ),
    "venue_history": (
        "La sede esta en el Convento de San Diego, fundado en 1608 y terminado "
        "aproximadamente en 1625. Fue sede de los Franciscanos Recoletos Descalzos "
        "hasta 1821, tuvo varios usos institucionales y en 1976 se establecio como "
        "sede de la Escuela de Bellas Artes. En 2021 fue declarado Bien de Interes "
        "Cultural de Caracter Nacional."
    ),
    "venue_context": (
        "Hoy el edificio es sede de la Institucion Universitaria Bellas Artes y Ciencias "
        "de Bolivar, UNIBAC. Esta en la plaza de San Diego, en el centro historico de "
        "Cartagena, cerca del Sofitel Santa Clara, las Bovedas, galerias y restaurantes."
    ),
    "exhibition_spaces": {
        "patio": (
            "Patio de las Artes: espacio de convergencia donde los stands se ubican en "
            "pasillos formando un recorrido circular y continuo. Tiene arquitectura "
            "colonial, arcadas, vigas de madera, ventiladores de techo de gran formato "
            "y acceso directo desde la calle por el zaguan."
        ),
        "salon": (
            "Salon Pierre Daguet: antigua capilla colonial con techos artesonados de "
            "gran altura. Los stands se disponen en bloques e islas centrales para un "
            "recorrido facil e intuitivo conectado con el patio central. Cuenta con aire "
            "acondicionado y acceso directo desde la calle por el atrio principal."
        ),
    },
    "gallery_sections": "Familia Origen Colombia, Rostros Origen, Visitantes y Nuestro Espacio.",
    "location": (
        "La feria se realiza en la Sede UNIBAC, en el Convento de San Diego, plaza de "
        "San Diego, centro historico de Cartagena. Si necesitas indicaciones exactas de "
        "llegada, escribe 'asesor' y el equipo te confirma la ruta."
    ),
    "human_help": (
        "Puedo pasarte con el equipo de la feria. Escribe tu nombre, tu marca y la "
        "pregunta concreta para que un asesor te contacte."
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
