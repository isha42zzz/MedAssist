from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared.proto import diagnosis_pb2
from shared.secure_channel import (
    build_client_codec,
    build_server_codec,
    derive_session_keys,
    generate_ephemeral_keypair,
)


def test_x25519_key_exchange_and_secure_request_round_trip():
    client_private_key, client_public_key = generate_ephemeral_keypair()
    server_private_key, server_public_key = generate_ephemeral_keypair()
    session_id = "session-123"
    nonce = b"0123456789abcdef"

    client_keys = derive_session_keys(client_private_key, server_public_key, session_id, nonce)
    server_keys = derive_session_keys(server_private_key, client_public_key, session_id, nonce)

    assert client_keys.client_write_key == server_keys.client_write_key
    assert client_keys.server_write_key == server_keys.server_write_key

    client_codec = build_client_codec(client_keys, session_id)
    server_codec = build_server_codec(server_keys, session_id)

    secure_request = diagnosis_pb2.SecureRequest(
        handshake_open=diagnosis_pb2.HandshakeOpenRequest(session_id=session_id)
    )
    envelope = client_codec.encrypt_message(secure_request)
    decoded = server_codec.decrypt_message(envelope, diagnosis_pb2.SecureRequest)

    assert decoded.handshake_open.session_id == session_id


def test_secure_channel_rejects_replayed_sequence():
    client_private_key, client_public_key = generate_ephemeral_keypair()
    server_private_key, server_public_key = generate_ephemeral_keypair()
    session_id = "session-456"
    nonce = b"fedcba9876543210"

    client_keys = derive_session_keys(client_private_key, server_public_key, session_id, nonce)
    server_keys = derive_session_keys(server_private_key, client_public_key, session_id, nonce)

    client_codec = build_client_codec(client_keys, session_id)
    server_codec = build_server_codec(server_keys, session_id)

    envelope = client_codec.encrypt_message(
        diagnosis_pb2.SecureRequest(
            handshake_open=diagnosis_pb2.HandshakeOpenRequest(session_id=session_id)
        )
    )
    server_codec.decrypt_message(envelope, diagnosis_pb2.SecureRequest)

    try:
        server_codec.decrypt_message(envelope, diagnosis_pb2.SecureRequest)
    except ValueError as exc:
        assert "sequence" in str(exc)
    else:
        raise AssertionError("expected sequence replay to be rejected")


def test_aes_gcm_uses_expected_nonce_shape():
    nonce = b"\x00\x00\x00\x00" + (7).to_bytes(8, "big")
    ciphertext = AESGCM(bytes(range(32))).encrypt(nonce, b"payload", b"aad")
    assert len(ciphertext) > len(b"payload")
