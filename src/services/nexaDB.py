# nexaDB.py - Nexa Database Service
# Database service entitled nexaDB for NexaBot components. Like boltDB /w security features.
# Provides both unprotected and encrypted database classes for flexible data storage needs.
# Under the MIT License.

import os
from pathlib import Path
import json
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import HKDF, scrypt
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes
from services import nexaLoggerFactory
import inspect

logger = nexaLoggerFactory.get_logger("databases")

class unprotectedDB:
    """
    This is an UNECRYPTED database class for simple data storage without encryption.

    As a result, there is no assumed threat model. It is simply a JSON file storage with basic read/write capabilities.

    If you are a developer contributing, please consider the correct use case and scope of this class before adding features.

    # Methods:
    - load(): Load the database from the file into memory (private variable).
    - unload(): Unload the database from memory (private variable).
    - prime(): Creates data inside database that gets the database minimally functional. Usually just a {}.
    - fetchEntry(key: str): Getter method that fetches the data at a specific directory inside the database.
    - setEntry(key: str, value): Setter method that sets the data at a specific directory inside the database.
    - deleteEntry(key: str): Deleter method that deletes the data at a specific directory inside the database.
    - addEntry(key: str, value): Adds a new entry at a specific directory inside the database.
    - exists(key: str): Existence checker method that checks if a specific directory inside the database exists.
    """
    def __init__(self, dbPath: Path, create_if_missing: bool = False):
        logger.info(f"Unprotected Database construction invoked by {inspect.currentframe().f_back.f_globals['__name__']}.{inspect.currentframe().f_back.f_code.co_name}() at line {inspect.currentframe().f_back.f_lineno}.")
        self.dbPath = dbPath
        self.data = None

        # Check if the specified directory exists, error if not
        if not self.dbPath.parent.exists():
            if not create_if_missing:
                logger.error(f"Directory '{self.dbPath.parent}' does not exist for database path '{self.dbPath}'")
                raise FileNotFoundError(f"Directory '{self.dbPath.parent}' does not exist for database path '{self.dbPath}'")
            else:
                self.dbPath.parent.mkdir(parents=True, exist_ok=True)
                self.prime()  # Create an empty database file if we're creating the directory

    def load(self) -> None:
        """
        Load the database from the file into memory (private variable).
        """
        if not self.dbPath.exists():
            self.data = {}
            return

        with open(self.dbPath, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def unload(self) -> None:
        """
        Unload the database from memory (private variable).
        """

        # Save current data to file before unloading
        with open(self.dbPath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

        self.data = None


    def prime(self) -> None:
        """
        Creates data inside database that gets the database minimally functional. Usually just a {}.
        """
        self.data = {}
        with open(self.dbPath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def fetchEntry(self, key: str):
        """
        Getter method that fetches the data at a specific directory inside the database.

        Assume the database class has already been instantiated with the loaded data being:

        ```
        {
            "example1": "apple",
            "example2": "banana",
            "complex1": {
                "example1": "cherry"
            }
        }
        ```

        If you wanted to fetch a root entry called 'example1', provide argument 'key'. This results in the data associated with 'apple' being returned. 
        If it has multiple values, it is up to you to parse the remaining with the python library 'json'.

        You can go further by specifying complex keys using dot notation. For example, to get 'cherry', you would provide 'complex1.example1' as the key.
        """
        data = self.data

        if data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")
        
        keys = key.split(".")
        for k in keys:
            if k in data:
                data = data[k]
            else:
                return None
        return data

    def setEntry(self, key: str, value) -> None:
        """
        Setter method that sets the data at a specific directory inside the database.
        """
        if self.data is None:
            raise databaseIsUnloadedError(
                "Database has not been loaded. Please call load() before accessing entries."
            )

        data = self.data
        keys = key.split(".")

        for k in keys[:-1]:
            if k not in data or not isinstance(data[k], dict):
                data[k] = {}
            data = data[k]

        data[keys[-1]] = value
        


    def deleteEntry(self, key: str) -> None:
        """
        Deleter method that deletes data at a specific directory inside the database.
        """
        data = self.data

        if data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")

        keys = key.split(".")
        for k in keys[:-1]:
            if k not in data:
                return
            data = data[k]

        if keys[-1] in data:
            del data[keys[-1]]

    def addEntry(self, key: str, value) -> None:
        """
        Adds a new entry at a specific directory inside the database.

        Raises an error if the key already exists.
        """
        if self.data is None:
            raise databaseIsUnloadedError(
                "Database has not been loaded. Please call load() before accessing entries."
            )

        data = self.data
        keys = key.split(".")

        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            elif not isinstance(data[k], dict):
                raise TypeError(
                    f"Cannot create subkey under non-dictionary value at '{k}'"
                )
            data = data[k]

        final_key = keys[-1]

        if final_key in data:
            raise KeyError(f"Entry '{key}' already exists")

        data[final_key] = value


    def exists(self, key: str) -> bool:
        """
        Existence checker method that checks if a specific directory inside the database exists.
        """
        data = self.data

        if data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")
        
        keys = key.split(".")
        for k in keys:
            if k in data:
                data = data[k]
            else:
                return False
        return True
    


class protectedDB:
    """
    Encrypted database class for secure data storage.
    
    Uses AES-GCM to encrypt the entire JSON blob at rest.
    In-memory, data is stored as a standard Python dict.
    
    Threat Model:
    - Encryption at rest with authenticated encryption (AES-GCM)
    - Tamper detection via GCM auth tag. Corrupted or modified files will raise ValueError on load
    - Does NOT protect against memory scraping or runtime attacks
    - Volatile in-memory data. Unload asap after making changes to minimize risk.
    - Assumes server environment is trusted

    File layout: [nonce: 12 bytes][tag: 16 bytes][ciphertext: n bytes]

    # Methods:
    - load(): Load the database from the file into memory (private variable).
    - unload(): Unload the database from memory (private variable).
    - prime(): Creates data inside database that gets the database minimally functional. Usually just a {}.
    - fetchEntry(key: str): Getter method that fetches the data at a specific directory inside the database.
    - setEntry(key: str, value): Setter method that sets the data at a specific directory inside the database.
    - deleteEntry(key: str): Deleter method that deletes the data at a specific directory inside the database.
    - addEntry(key: str, value): Adds a new entry at a specific directory inside the database.
    - exists(key: str): Existence checker method that checks if a specific directory inside the database exists.
    """

    # Simple static salt.
    _SALT = b'nexaDB-salt-K9ui9pyWwfR9T1H1XiHz'

    def __init__(self, dbPath: Path, password: str, create_if_missing: bool = False):
        logger.info(f"Protected Database construction invoked by {inspect.currentframe().f_back.f_globals['__name__']}.{inspect.currentframe().f_back.f_code.co_name}() at line {inspect.currentframe().f_back.f_lineno}.")
        self.dbPath = dbPath
        self.password = password
        self.data = None
        self._key = self._derive_key(password)

        # Check if the specified directory exists, error if not
        if not self.dbPath.parent.exists():
            if not create_if_missing:
                logger.error(f"Directory '{self.dbPath.parent}' does not exist for database path '{self.dbPath}'")
                raise FileNotFoundError(f"Directory '{self.dbPath.parent}' does not exist for database path '{self.dbPath}'")
            else:
                self.dbPath.parent.mkdir(parents=True, exist_ok=True)
                self.prime()

    def _derive_key(self, password: str) -> bytes:
        """
        Derive a 32-byte AES key from the password using scrypt.
        scrypt provides memory-hard key stretching, making brute-force attacks significantly more expensive
        than raw SHA256.
        """
        return scrypt(
            password.encode("utf-8"),
            salt=self._SALT,
            key_len=32,
            N=2**14,  # CPU/memory cost factor
            r=8,       # Block size
            p=1        # Parallelization factor
        )

    def load(self) -> None:
        """
        Load and decrypt database into memory.
        Raises ValueError if the file has been tampered with or the password is incorrect.
        """
        if not self.dbPath.exists():
            self.data = {}
            return

        with open(self.dbPath, "rb") as f:
            raw = f.read()
            if len(raw) < 28:  # 12 (nonce) + 16 (tag) minimum
                raise ValueError("Encrypted file too short or corrupted")

            nonce = raw[:12]
            tag = raw[12:28]
            ciphertext = raw[28:]

            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
            try:
                plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            except ValueError:
                raise ValueError("Database integrity check failed. File may be corrupted or tampered with, or the password is incorrect.")

            self.data = json.loads(plaintext)

    def unload(self) -> None:
        """
        Encrypt and save database to file, then clear from memory.
        """
        if self.data is None:
            return

        plaintext = json.dumps(self.data, indent=4).encode("utf-8")
        nonce = get_random_bytes(12)
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)

        with open(self.dbPath, "wb") as f:
            f.write(nonce + tag + ciphertext)  # 12 + 16 + n bytes

        self.data = None

    def prime(self) -> None:
        """
        Creates data inside database that gets the database minimally functional.
        Routes through unload() to ensure the file is written encrypted from the start.
        """
        self.data = {}
        self.unload()

    def fetchEntry(self, key: str):
        if self.data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")
        data = self.data
        keys = key.split(".")
        for k in keys:
            if k in data:
                data = data[k]
            else:
                return None
        return data

    def setEntry(self, key: str, value) -> None:
        if self.data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")
        data = self.data
        keys = key.split(".")
        for k in keys[:-1]:
            if k not in data or not isinstance(data[k], dict):
                data[k] = {}
            data = data[k]
        data[keys[-1]] = value

    def addEntry(self, key: str, value) -> None:
        if self.data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")
        data = self.data
        keys = key.split(".")
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            elif not isinstance(data[k], dict):
                raise TypeError(f"Cannot create subkey under non-dictionary value at '{k}'")
            data = data[k]
        final_key = keys[-1]
        if final_key in data:
            raise KeyError(f"Entry '{key}' already exists")
        data[final_key] = value

    def deleteEntry(self, key: str) -> None:
        if self.data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")
        data = self.data
        keys = key.split(".")
        for k in keys[:-1]:
            if k not in data:
                return
            data = data[k]
        if keys[-1] in data:
            del data[keys[-1]]

    def exists(self, key: str) -> bool:
        if self.data is None:
            raise databaseIsUnloadedError("Database has not been loaded. Please call load() before accessing entries.")
        data = self.data
        keys = key.split(".")
        for k in keys:
            if k in data:
                data = data[k]
            else:
                return False
        return True



class databaseIsUnloadedError(Exception):
    """
    Exception raised when attempting to access the database before it has been loaded.
    """
    pass
