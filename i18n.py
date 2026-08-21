"""Motor de internacionalizacion (i18n) para Semaforo IA.

Toda la interfaz (ventanas, botones, dialogos) y los reportes PDF/JSON deben
obtener sus textos a traves de la funcion t(texto_original). Las traducciones
viven en locales/translations.json y NO estan hardcodeadas en el codigo: para
agregar un nuevo idioma basta con sumar su codigo (ej. "fr") en cada entrada
de ese archivo, sin tocar ningun .py.
"""
import json
import os

from app_paths import resource_path, writable_path

_LOCALES_DIR = resource_path("locales")
_TRANSLATIONS_PATH = os.path.join(_LOCALES_DIR, "translations.json")
_CONFIG_PATH = writable_path("config.json")

DEFAULT_LANGUAGE = "es"


class Translator:
    def __init__(self, translations_path=_TRANSLATIONS_PATH):
        self.translations_path = translations_path
        self.current_lang = DEFAULT_LANGUAGE
        self._translations = {}
        self._reverse_index = {}
        self.reload()

    def reload(self):
        try:
            with open(self.translations_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = {}
        data.pop("_meta", None)
        self._translations = data
        self._build_reverse_index()

    def _build_reverse_index(self):
        index = {}
        for key, variants in self._translations.items():
            index[key] = key
            for text in variants.values():
                index.setdefault(text, key)
        self._reverse_index = index

    def available_languages(self):
        langs = set()
        for variants in self._translations.values():
            langs.update(variants.keys())
        langs.add(DEFAULT_LANGUAGE)
        return sorted(langs)

    def set_language(self, lang_code):
        if lang_code:
            self.current_lang = lang_code

    def key_for(self, text):
        """Devuelve la clave canonica (texto original) para cualquier texto ya traducido."""
        return self._reverse_index.get(text, text)

    def t(self, text, lang=None):
        """Traduce `text` (clave o variante ya traducida) al idioma indicado (o al actual)."""
        if not text:
            return text
        lang = lang or self.current_lang
        key = self._reverse_index.get(text, text)
        variants = self._translations.get(key)
        if not variants:
            return text
        return variants.get(lang, variants.get(DEFAULT_LANGUAGE, text))


translator = Translator()


def t(text, lang=None):
    return translator.t(text, lang)


def key_for(text):
    return translator.key_for(text)


def set_language(lang_code):
    translator.set_language(lang_code)


def get_language():
    return translator.current_lang


def available_languages():
    return translator.available_languages()


def next_language(current=None):
    """Devuelve el siguiente idioma disponible en la lista (para el boton de toggle)."""
    langs = available_languages()
    if not langs:
        return DEFAULT_LANGUAGE
    current = current or get_language()
    if current not in langs:
        return langs[0]
    idx = (langs.index(current) + 1) % len(langs)
    return langs[idx]


def load_saved_language():
    """Lee el idioma persistido en config.json (si existe) y lo aplica."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return get_language()
    lang = config.get("language", DEFAULT_LANGUAGE)
    set_language(lang)
    return lang


def save_language(lang_code):
    """Persiste el idioma elegido en config.json para recordarlo en el proximo inicio."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError):
        config = {}
    config["language"] = lang_code
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2, ensure_ascii=False)
    except OSError:
        pass
