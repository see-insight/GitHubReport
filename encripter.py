from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import serialization, hashes

def load_public_key(public_key_path):
    """
    Load the public SSH key from the specified file path.

    Args:
        public_key_path (str): The file path to the public SSH key.

    Returns:
        public_key: The loaded public key object.
    """
    with open(public_key_path, "rb") as key_file:
        public_key = serialization.load_ssh_public_key(key_file.read())
    return public_key

def encrypt_password(password, public_key_path, filename="password.enc"):
    """
    Encrypt the password using the public key and save it to a file.

    Args:
        password (str): The password to encrypt.
        public_key_path (str): The file path to the public SSH key.
        filename (str): The file name to save the encrypted password. Default is "password.enc".
    """
    public_key = load_public_key(public_key_path)
    encrypted_password = public_key.encrypt(
        password.encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    with open(filename, "wb") as enc_file:
        enc_file.write(encrypted_password)

def makepwfile(password='', public_key_path="~/.ssh/id_rsa_python.pub"):
    """
    Prompt for a password if not provided, encrypt it using the public key, and save it to a file.

    Args:
        password (str): The password to encrypt. If empty, the user will be prompted to enter a password.
        public_key_path (str): The file path to the public SSH key.
    """
    if password == '':
        password = input('Password: ')
    if password:
        encrypt_password(password, public_key_path, filename="password.enc")
        print('Password Saved')

def load_private_key(private_key_path):
    """
    Load the private SSH key from the specified file path.

    Args:
        private_key_path (str): The file path to the private SSH key.

    Returns:
        private_key: The loaded private key object.
    """
    with open(private_key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None  # Use this if your private key is not password protected
        )
    return private_key

def decrypt_password(filename="password.enc", private_key_path="/home/colbrydi/.ssh/id_rsa_python"):
    """
    Decrypt the password using the private key from the specified file.

    Args:
        filename (str): The file name containing the encrypted password. Default is "password.enc".
        private_key_path (str): The file path to the private SSH key.

    Returns:
        str: The decrypted password.
    """
    private_key = load_private_key(private_key_path)
    with open(filename, "rb") as enc_file:
        encrypted_password = enc_file.read()
    decrypted_password = private_key.decrypt(
        encrypted_password,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return decrypted_password.decode()
