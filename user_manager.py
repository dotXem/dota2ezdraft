"""User management with GCS-backed storage."""

import yaml
import gcsfs
import bcrypt
import secrets

BUCKET = "heroes-ezdraft"
USERS_PATH = f"{BUCKET}/users.yaml"


def _get_fs():
    return gcsfs.GCSFileSystem()


def _default_config():
    return {
        "credentials": {"usernames": {}},
        "cookie": {
            "expiry_days": 30,
            "key": secrets.token_hex(32),
            "name": "ezdraft_cookie",
        },
        "preauthorized": {"emails": []},
        "heroes_lists": {},
    }


def load_config():
    """Load user config from GCS, falling back to local file then defaults."""
    fs = _get_fs()
    try:
        with fs.open(USERS_PATH, "r") as f:
            config = yaml.safe_load(f)
        if config:
            return config
    except FileNotFoundError:
        pass

    # Migration: load from local users.yaml and upload to GCS
    try:
        with open("users.yaml", "r") as f:
            config = yaml.safe_load(f)
        if config:
            # Replace weak cookie key with a strong one
            config["cookie"]["key"] = secrets.token_hex(32)
            save_config(config)
            return config
    except FileNotFoundError:
        pass

    config = _default_config()
    save_config(config)
    return config


def save_config(config):
    """Save user config to GCS."""
    fs = _get_fs()
    with fs.open(USERS_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def get_user_heroes(config, username):
    """Get hero lists for a user."""
    if not username:
        return {}
    return config.get("heroes_lists", {}).get(username, {})


def register_user(config, username, display_name, password):
    """Register a new user. Returns (success, error_message)."""
    if username in config["credentials"]["usernames"]:
        return False, "Username already taken."
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    config["credentials"]["usernames"][username] = {
        "name": display_name,
        "password": hashed,
        "email": None,
    }
    if "heroes_lists" not in config:
        config["heroes_lists"] = {}
    config["heroes_lists"][username] = {}
    save_config(config)
    return True, None


def change_password(config, username, current_password, new_password):
    """Change a user's password. Returns (success, error_message)."""
    stored_hash = config["credentials"]["usernames"][username]["password"]
    # Normalize $2y$ (PHP bcrypt) to $2b$ (Python bcrypt) for compatibility
    check_hash = stored_hash
    if check_hash.startswith("$2y$"):
        check_hash = "$2b$" + check_hash[4:]
    if not bcrypt.checkpw(current_password.encode(), check_hash.encode()):
        return False, "Current password is incorrect."
    new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    config["credentials"]["usernames"][username]["password"] = new_hash
    save_config(config)
    return True, None


def save_hero_list(config, username, list_name, heroes):
    """Create or update a hero list."""
    if username not in config.get("heroes_lists", {}):
        config["heroes_lists"][username] = {}
    config["heroes_lists"][username][list_name] = heroes
    save_config(config)


def delete_hero_list(config, username, list_name):
    """Delete a hero list."""
    lists = config.get("heroes_lists", {}).get(username, {})
    if list_name in lists:
        del lists[list_name]
        save_config(config)
