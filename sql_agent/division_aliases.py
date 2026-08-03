from __future__ import annotations

import re


# Keys are exact values from DWH.LLM.division. Generic city/location words are
# intentionally not aliases because they would produce false store filters.
DIVISION_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "Bobbi Brown Mega Center Almaty": ("бобби браун мега центр алматы", "бобби браун мега сентер алматы", "бобби браун мега алматы"),
    "Bobbi Brown/Jo Malone Dostyk Plaza Almaty": ("бобби браун джо малон достык плаза алматы", "бобби браун и джо малон достык плаза алматы", "bobbi brown jo malone dostyk plaza almaty"),
    "Bobbi Brown/Jo Malone Mega Silk Way Astana": ("бобби браун джо малон мега силк вей астана", "бобби браун и джо малон мега силк вей астана", "bobbi brown jo malone mega silk way astana"),
    "Boucheron": ("бушерон",),
    "Buben&Zorweg Astana": ("бубен зорвег астана", "бубен энд зорвег астана", "buben and zorweg astana"),
    "Carrera y Carrera Astana": ("каррера и каррера астана", "карера и карера астана", "carrera and carrera astana"),
    "Cartier Almaty": ("картье алматы", "картиер алматы"),
    "CDV.KZ": ("сдв кз", "сиди ви кз", "cdv kz"),
    "Central Salon Almaty": ("центральный салон алматы", "централ салон алматы"),
    "Chateau Almaty": ("шато алматы",),
    "Chateau Astana": ("шато астана",),
    "Chopard Almaty": ("шопар алматы", "шопард алматы"),
    "Chopard Astana": ("шопар астана", "шопард астана"),
    "Chopard Спец.проект": ("шопар спецпроект", "шопард спецпроект", "chopard спецпроект"),
    "Code de Vie Baizaar Atyrau": ("код де ви байзаар атырау", "код де ви базар атырау", "code de vie baizaar atyrau"),
    "Code de Vie Keruen Astana": ("код де ви керуен астана",),
    "Code de Vie Keruen City Aktobe": ("код де ви керуен сити актобе",),
    "Code de Vie Keruen City Astana": ("код де ви керуен сити астана",),
    "Code de Vie Talan Astana": ("код де ви талан астана",),
    "Code de Vie Нурлы Жол Astana": ("код де ви нурлы жол астана", "code de vie nurly zhol astana"),
    "Farfetch": ("фарфетч", "фарфеч"),
    "Graff Almaty": ("графф алматы", "граф алматы"),
    "H.Stern": ("аш стерн", "эйч стерн", "h stern"),
    "Heritage Almaty": ("херитейдж алматы", "херитаж алматы"),
    "Heritage Astana": ("херитейдж астана", "херитаж астана"),
    "Home&Gift Distribution": ("хоум энд гифт дистрибьюшн", "home and gift distribution", "хоум гифт дистрибьюшн"),
    "Jewelry & Watch Astana St.Regis": ("джевелри энд вотч астана сент реджис", "ювелирный и часовой астана сент реджис", "jewelry and watch astana st regis"),
    "Jo Malone Mega Center Almaty": ("джо малон мега центр алматы", "джо малон мега сентер алматы", "джо малон мега алматы"),
    "Keruen Astana": ("керуен астана",),
    "Keruen Cinema": ("керуен синема", "кинотеатр керуен"),
    "Kiehl's Dostyk Plaza Almaty": ("килс достык плаза алматы", "киелс достык плаза алматы", "kiehls dostyk plaza almaty"),
    "Kiehl's Keruen Astana": ("килс керуен астана", "киелс керуен астана", "kiehls keruen astana"),
    "Kiehl's Mega Center Almaty": ("килс мега центр алматы", "киелс мега центр алматы", "kiehls mega center almaty"),
    "Kiton": ("китон",),
    "Multibrand Astana Raddisson": ("мультибренд астана радиссон", "мульти бренд астана радиссон", "multibrand astana radisson"),
    "Outlet City Актобе": ("аутлет сити актобе", "outlet city aktobe"),
    "Outlet City Астана": ("аутлет сити астана", "outlet city astana"),
    "Outlet City Атырау": ("аутлет сити атырау", "outlet city atyrau"),
    "Project 50%+40%": ("проект 50 40", "project 50 40"),
    "Rich Stone": ("рич стоун",),
    "Saks Fifth Avenue": ("сакс", "сакс фифт авеню", "сакс пятая авеню", "saks", "saks 5th avenue"),
    "Service Center Almaty": ("сервис центр алматы", "сервисный центр алматы"),
    "Stock J&W": ("сток джей энд дабл ю", "сток ювелирка и часы", "stock jewelry and watch"),
    "Talan Jewelry&Watch Astana": ("талан джевелри энд вотч астана", "талан ювелирный и часовой астана", "talan jewelry and watch astana"),
    "The Point": ("зе поинт", "поинт"),
    "Tiffany Almaty": ("тиффани алматы", "тифани алматы"),
    "Tiffany Astana": ("тиффани астана", "тифани астана"),
    "Van Cleef&Arpels Almaty": ("ван клиф энд арпельс алматы", "ван клиф арпельс алматы", "van cleef and arpels almaty"),
    "Viled Home Астана": ("вилед хоум астана", "viled home astana"),
    "Viled Style": ("вилед стайл",),
    "Viled.kz": ("вилед кз", "viled kz"),
    "Vintage Almaty": ("винтаж алматы",),
    "VLD-ALKO": ("влд алко", "vld alko"),
    "Визуальный мерчендайзинг": ("visual merchandising", "визуальный мерчандайзинг"),
    "Внутригрупповые обороты": ("внутригрупповой оборот", "intercompany turnover", "intercompany sales"),
    "Выставка": ("exhibition",),
    "Выставка Beauty": ("выставка бьюти", "beauty exhibition"),
    "Выставка в РК": ("выставка казахстан", "exhibition in kazakhstan", "выставка рк"),
    "Новый магазин": ("new store", "новая точка"),
    "Панфилова Бутик": ("бутик панфилова", "panfilova boutique", "панфилова бутик"),
    "Показ": ("fashion show", "шоу"),
    "Продажа Бизнеса": ("продажа бизнеса", "business sale"),
    "Реализация": ("реализация", "sales realization"),
    "Центральный склад": ("центральный склад", "central warehouse", "цс"),
    "Часовой бутик VILED": ("часовой бутик вилед", "viled watch boutique"),
    "Часовой и Ювелирный Бутик Атырау": ("часовой и ювелирный бутик атырау", "ювелирный и часовой бутик атырау", "jewelry and watch boutique atyrau"),
}


def normalize_division_name(value: str) -> str:
    value = value.casefold().replace("ё", "е").replace("&", " and ")
    return " ".join(re.findall(r"[a-zа-я0-9]+", value))


def _build_alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for canonical_name, variants in DIVISION_NAME_ALIASES.items():
        for variant in (canonical_name, *variants):
            normalized = normalize_division_name(variant)
            previous = aliases.setdefault(normalized, canonical_name)
            if previous != canonical_name:
                raise ValueError(f"Duplicate division alias {variant!r}")
    return aliases


_DIVISION_ALIAS_INDEX = _build_alias_index()


def canonicalize_division_name(value: str) -> str:
    """Return the exact division value for a known Russian/English spelling."""
    return _DIVISION_ALIAS_INDEX.get(normalize_division_name(value), value.strip())


def find_contextual_division_name(question: str) -> str | None:
    """Recognize a known name in phrases such as ``в сакс`` or ``бутик Saks``."""
    normalized_question = f" {normalize_division_name(question)} "
    contexts = (
        "в ", "во ", "из ", "у ", "для ", "по ",
        "in ", "at ", "from ",
        "магазин ", "магазина ", "магазине ",
        "бутик ", "бутика ", "бутике ", "бутику ",
        "подразделение ", "подразделения ", "подразделении ", "подразделению ",
        "точка продаж ", "точке продаж ", "store ", "boutique ", "division ",
    )
    matches: list[tuple[int, str]] = []
    for alias, canonical_name in _DIVISION_ALIAS_INDEX.items():
        if any(f" {context}{alias} " in normalized_question for context in contexts):
            matches.append((len(alias), canonical_name))
    return max(matches, default=(0, None))[1]
