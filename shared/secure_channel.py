from __future__ import annotations

from dataclasses import dataclass
from typing import Type, TypeVar

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from google.protobuf.message import Message

from shared.proto import diagnosis_pb2


KEY_SIZE = 32
NONCE_PREFIX = b"\x00\x00\x00\x00"
INFO_PREFIX = b"medassist-session:"
T = TypeVar("T", bound=Message)


@dataclass(frozen=True)
class SessionKeys:
    client_write_key: bytes
    server_write_key: bytes


def generate_ephemeral_keypair() -> tuple[X25519PrivateKey, bytes]:
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, public_key


def derive_session_keys(
    private_key: X25519PrivateKey,
    peer_public_key: bytes,
    session_id: str,
    nonce: bytes,
) -> SessionKeys:
    shared_secret = private_key.exchange(X25519PublicKey.from_public_bytes(peer_public_key))
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE * 2,
        salt=nonce,
        info=INFO_PREFIX + session_id.encode("utf-8"),
    ).derive(shared_secret)
    return SessionKeys(
        client_write_key=derived[:KEY_SIZE],
        server_write_key=derived[KEY_SIZE:],
    )


@dataclass
class SecureSessionCodec:
    session_id: str
    send_key: bytes
    receive_key: bytes
    send_sequence: int = 0
    receive_sequence: int = 0

    def encrypt_message(self, message: Message) -> diagnosis_pb2.SecureEnvelope:
        plaintext = message.SerializeToString()
        sequence = self.send_sequence
        ciphertext = AESGCM(self.send_key).encrypt(
            _build_nonce(sequence),
            plaintext,
            _build_aad(self.session_id, sequence),
        )
        self.send_sequence += 1
        return diagnosis_pb2.SecureEnvelope(
            session_id=self.session_id,
            sequence=sequence,
            ciphertext=ciphertext,
        )

    def decrypt_message(self, envelope: diagnosis_pb2.SecureEnvelope, message_type: Type[T]) -> T:
        if envelope.session_id != self.session_id:
            raise ValueError("session_id mismatch")
        if envelope.sequence != self.receive_sequence:
            raise ValueError("unexpected secure message sequence")
        plaintext = AESGCM(self.receive_key).decrypt(
            _build_nonce(envelope.sequence),
            bytes(envelope.ciphertext),
            _build_aad(self.session_id, envelope.sequence),
        )
        self.receive_sequence += 1
        message = message_type()
        message.ParseFromString(plaintext)
        return message


def build_client_codec(keys: SessionKeys, session_id: str) -> SecureSessionCodec:
    return SecureSessionCodec(
        session_id=session_id,
        send_key=keys.client_write_key,
        receive_key=keys.server_write_key,
    )


def build_server_codec(keys: SessionKeys, session_id: str) -> SecureSessionCodec:
    return SecureSessionCodec(
        session_id=session_id,
        send_key=keys.server_write_key,
        receive_key=keys.client_write_key,
    )


def _build_nonce(sequence: int) -> bytes:
    return NONCE_PREFIX + sequence.to_bytes(8, "big")


def _build_aad(session_id: str, sequence: int) -> bytes:
    return session_id.encode("utf-8") + b":" + sequence.to_bytes(8, "big")
