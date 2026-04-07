from hashlib import sha256

from shared.attestation.api import ParsedAttestation, build_user_data, report_digest, verify_report


def test_build_user_data_matches_sha256_digest():
    tee_pubkey = bytes(range(32))
    hospital_pubkey = bytes(range(32, 64))
    nonce = bytes(range(16))
    assert build_user_data(tee_pubkey, hospital_pubkey, nonce) == sha256(tee_pubkey + hospital_pubkey + nonce).digest()


def test_report_digest_uses_sha256():
    report = b"attestation-report"
    assert report_digest(report) == sha256(report).hexdigest()


def test_verify_report_returns_user_data_and_loads_verifier_once(monkeypatch):
    calls = {"count": 0}
    user_data = bytes(range(32))
    report = b"report"

    class FakeVerifier:
        chip_id = "chip-1"
        real_report = bytearray(256)

        def __init__(self):
            self.real_report[0x40:0x40 + 32] = user_data
            self.real_report[0x90:0xB0] = bytes(reversed(range(32)))
            self.real_report[0xB0:0xB4] = (0).to_bytes(4, "little")

        def verify_signature(self):
            return True

    def fake_load_verifier(_report):
        assert _report == report
        calls["count"] += 1
        return FakeVerifier()

    monkeypatch.setattr("shared.attestation.api._load_verifier", fake_load_verifier)
    monkeypatch.setattr("shared.attestation.api._policy_string", lambda verifier: "NODEBUG || NOKS")

    parsed = verify_report(report)

    assert isinstance(parsed, ParsedAttestation)
    assert parsed.user_data == user_data
    assert parsed.user_data_hex == user_data.hex()
    assert parsed.policy == "NODEBUG || NOKS"
    assert parsed.measurement == bytes(reversed(range(32))).hex()
    assert parsed.chip_id == "chip-1"
    assert calls["count"] == 1
