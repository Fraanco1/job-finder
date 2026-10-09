"""German (and a few Scandinavian/Dutch) subject words -> English field labels.

The classifier's keyword lists are English. German-language adverts
(Fraunhofer, ETH, Werkstudent jobs) name the field as "Maschinenbau",
"Elektrotechnik", ... so sources pass the labels returned here as
``source_fields``; every label is a key of ``taxonomy.EURAXESS_FIELD_MAP``.
"""

from __future__ import annotations

import re

_RULES: list[tuple[str, str]] = [
    (r"informatik|softwareentwickl\w*|software-entwickl\w*|programmier\w*|"
     r"künstliche\w* intelligenz|maschinelle\w* lernen|datenwissenschaft|data science|"
     r"bildverarbeitung|cybersicherheit|it-sicherheit", "computer science"),
    (r"wirtschaftsinformatik", "information technology"),
    (r"elektrotechnik|elektronik|nachrichtentechnik|hochfrequenztechnik|leistungselektronik|"
     r"halbleiter\w*|mikroelektroni\w*|schaltung\w*|elektrisch\w*", "electrical engineering"),
    (r"regelungstechnik|automatisierungstechnik|automatisierung", "control engineering"),
    (r"maschinenbau|mechatronik|konstruktion|fertigungstechnik|produktionstechnik|"
     r"feinwerktechnik|fahrzeugtechnik|antriebstechnik|strömungsmechanik|thermodynamik", "mechanical engineering"),
    (r"luft- und raumfahrt\w*|luftfahrt\w*|raumfahrt\w*", "aerospace engineering"),
    (r"verfahrenstechnik|chemieingenieur\w*|prozesstechnik", "chemical engineering"),
    (r"werkstoff\w*|materialwissenschaft\w*|materialforschung|beschichtung\w*|"
     r"oberflächentechnik|kunststofftechnik|polymer\w*", "materials engineering"),
    (r"bauingenieur\w*|bauphysik|bauwesen|geotechnik|tragwerk\w*|siedlungswasser\w*", "civil engineering"),
    (r"umwelttechnik|umweltingenieur\w*|umweltwissenschaft\w*|kreislaufwirtschaft", "environmental science"),
    (r"medizintechnik|biomedizin\w*technik|biomedical engineering", "biomedical engineering"),
    (r"energietechnik|energiesystem\w*|erneuerbare\w* energie\w*|wasserstoff\w*|"
     r"photovoltaik|batterie\w*|elektrochemi\w*", "energy technology"),
    (r"physik|optik|photonik|laser\w*|quanten\w*|akustik", "physics"),
    (r"chemie|chemisch\w*|kemi", "chemistry"),
    (r"mathematik|statistik|matematik|wiskunde", "mathematics"),
    (r"biologie|biotechnologie|mikrobiologie|molekularbiologie|biochemie|bioinformatik", "biology"),
    (r"geowissenschaft\w*|geologie|geophysik|meteorologie|ozeanographie|fernerkundung", "earth science"),
    (r"wirtschaftsingenieur\w*|industrial engineering", "industrial engineering"),
    (r"messtechnik|sensorik|sensor\w*", "measurement technology"),
]
_COMPILED = [(re.compile(rf"(?<![\w-])(?:{rx})(?![\w-])", re.I), label) for rx, label in _RULES]


def german_fields(*texts: str | None) -> list[str]:
    """English field labels for German subject words found in ``texts``."""
    text = " ".join(t for t in texts if t)
    out: list[str] = []
    for rx, label in _COMPILED:
        if rx.search(text) and label not in out:
            out.append(label)
    return out
