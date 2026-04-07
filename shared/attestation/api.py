from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from tempfile import NamedTemporaryFile

from .csv_attestation import AttestationReportProducor, AttestationReportVerifier


TEE_TYPE = "csv"
USERDATA_DIGEST_SIZE = 32
CSV_USERDATA_SIZE = 64
CSV_POLICY_NAMES = ("NODEBUG", "NOKS", "ES", "NOSEND", "DOMAIN", "CSV", "REUSE")


@dataclass(frozen=True)
class ParsedAttestation:
    tee_type: str
    user_data: bytes
    user_data_hex: str
    policy: str
    measurement: str
    chip_id: str


class _EncodedUserData:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __len__(self) -> int:
        return len(self._payload)

    def encode(self, _encoding: str = "utf-8") -> bytes:
        return self._payload


def build_user_data(tee_ephemeral_pubkey: bytes, hospital_ephemeral_pubkey: bytes, nonce: bytes) -> bytes:
    return sha256(tee_ephemeral_pubkey + hospital_ephemeral_pubkey + nonce).digest()


def generate_report(userdata: bytes) -> bytes:
    raw_user_data = bytes(userdata)
    if len(raw_user_data) != USERDATA_DIGEST_SIZE:
        raise ValueError(f"CSV attestation user data must be {USERDATA_DIGEST_SIZE} bytes")
    producer = AttestationReportProducor(
        _EncodedUserData(raw_user_data + bytes(CSV_USERDATA_SIZE - USERDATA_DIGEST_SIZE))
    )
    return bytes(producer.report)


def verify_report(report: bytes) -> ParsedAttestation:
    verifier = _load_verifier(report)
    if not verifier.verify_signature():
        raise ValueError("CSV attestation report verification failed")
    user_data = bytes(verifier.real_report[0x40:0x40 + USERDATA_DIGEST_SIZE])
    return ParsedAttestation(
        tee_type=TEE_TYPE,
        user_data=user_data,
        user_data_hex=user_data.hex(),
        policy=_policy_string(verifier),
        measurement=bytes(verifier.real_report[0x90:0xB0]).hex(),
        chip_id=verifier.chip_id,
    )


def report_digest(report: bytes) -> str:
    return sha256(report).hexdigest()


def _load_verifier(report: bytes) -> AttestationReportVerifier:
    with NamedTemporaryFile(mode="wb", suffix=".bin") as handle:
        handle.write(report)
        handle.flush()
        return AttestationReportVerifier(handle.name)


def _policy_string(verifier: AttestationReportVerifier) -> str:
    labels = []
    raw_policy = int.from_bytes(verifier.real_report[0xB0:0xB4], "little")
    for index, name in enumerate(CSV_POLICY_NAMES):
        if raw_policy & (1 << index):
            labels.append(name)
    labels.append("HSK_VERSION-0x%x" % ((raw_policy >> 8) & 0xF))
    labels.append("CEK_VERSION-0x%x" % ((raw_policy >> 12) & 0xF))
    labels.append("API_MAJOR-0x%x" % ((raw_policy >> 16) & 0xFF))
    labels.append("API_MINOR-0x%x" % ((raw_policy >> 24) & 0xFF))
    return " || ".join(labels)
