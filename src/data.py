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
    "purpose": "conectar talento, tradicion y oportunidades que impulsan lo mejor de Colombia.",
    "visitor_summary": (
        "Una feria para descubrir marcas, artesanos, emprendimientos, productos con "
        "identidad colombiana y experiencias culturales."
    ),
    "exhibitor_summary": (
        "Un espacio para que expositores presenten sus productos, conecten con visitantes "
        "y reciban acompanamiento comercial."
    ),
    "products": (
        "artesanias, moda, accesorios, joyeria, decoracion, bienestar, gastronomia, "
        "productos culturales y servicios creativos."
    ),
    "activities": (
        "muestras comerciales, recorridos por stands, experiencias culturales, "
        "activaciones de marca y espacios de networking."
    ),
    "location": (
        "La feria se realiza en la Sede UNIBAC. Si necesitas la direccion exacta o "
        "indicaciones de llegada, escribe 'asesor' y el equipo te confirma la ruta."
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
