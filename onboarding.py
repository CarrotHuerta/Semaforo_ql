"""Create the first local administrator, with no distributed passwords."""
import json
import os

from app_paths import atomic_json, initialize_user_data


def create_administrator(username, password, confirmation):
    from functional_core import LocalStore, ValidationError, hash_password
    username = username.strip().lower()
    if not username or len(username) > 128:
        raise ValidationError("Ingrese un nombre de usuario válido (máximo 128 caracteres).")
    if password != confirmation:
        raise ValidationError("Las contraseñas no coinciden.")
    encoded = hash_password(password)
    root = initialize_user_data()
    lock = root / ".account-setup.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    store = None
    try:
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        store = LocalStore(root / "semaforo.sqlite3")
        if config.get("users") or store.connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise ValidationError("Ya existen cuentas locales. Inicie sesión o recupere la cuenta existente.")
        profile = {"username": username, "display_name": username, "role": "Administrador",
                   "password_hash": encoded, "profile_photo": "", "force_password_change": False}
        with store.connection:
            store.connection.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)",
                                     (username, encoded, "Administrador"))
            config.update(users=[profile], default_user=username)
            atomic_json(root / "config.json", config)
        return profile
    finally:
        if store is not None:
            store.close()
        os.close(descriptor)
        lock.unlink(missing_ok=True)
