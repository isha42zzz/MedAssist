from hashlib import sha256

import pytest

from shared.attestation.api import ParsedAttestation, build_user_data, generate_report, report_digest, verify_report


def test_build_user_data_matches_sha256_digest():
    tee_pubkey = bytes(range(32))
    hospital_pubkey = bytes(range(32, 64))
    nonce = bytes(range(16))
    assert build_user_data(tee_pubkey, hospital_pubkey, nonce) == sha256(tee_pubkey + hospital_pubkey + nonce).digest()


def test_report_digest_uses_sha256():
    report = b"attestation-report"
    assert report_digest(report) == sha256(report).hexdigest()


def test_generate_report_adapts_digest_to_upstream_userdata(monkeypatch):
    calls = {}
    digest = bytes(range(32))

    class FakeProducer:
        def __init__(self, userdata):
            calls["length"] = len(userdata)
            calls["encoded"] = userdata.encode("utf-8")
            self.report = b"generated-report"

    monkeypatch.setattr("shared.attestation.api.AttestationReportProducor", FakeProducer)

    report = generate_report(digest)

    assert report == b"generated-report"
    assert calls["length"] == 64
    assert calls["encoded"] == digest + bytes(32)


def test_generate_report_rejects_non_digest_input():
    with pytest.raises(ValueError, match="32 bytes"):
        generate_report(b"short")


def test_verify_report_returns_user_data_and_loads_verifier_once(monkeypatch):
    calls = {"count": 0}
    user_data = bytes(range(32))
    report = b"report"
    raw_policy = (1 << 0) | (1 << 1) | (0xA << 8) | (0xB << 12) | (0x34 << 16) | (0x56 << 24)

    class FakeVerifier:
        chip_id = "chip-1"
        real_report = bytearray(256)

        def __init__(self):
            self.real_report[0x40:0x40 + 32] = user_data
            self.real_report[0x90:0xB0] = bytes(reversed(range(32)))
            self.real_report[0xB0:0xB4] = raw_policy.to_bytes(4, "little")

        def verify_signature(self):
            return True

    def fake_load_verifier(_report):
        assert _report == report
        calls["count"] += 1
        return FakeVerifier()

    monkeypatch.setattr("shared.attestation.api._load_verifier", fake_load_verifier)

    parsed = verify_report(report)

    assert isinstance(parsed, ParsedAttestation)
    assert parsed.user_data == user_data
    assert parsed.user_data_hex == user_data.hex()
    assert parsed.policy == "NODEBUG || NOKS || HSK_VERSION-0xa || CEK_VERSION-0xb || API_MAJOR-0x34 || API_MINOR-0x56"
    assert parsed.measurement == bytes(reversed(range(32))).hex()
    assert parsed.chip_id == "chip-1"
    assert calls["count"] == 1
