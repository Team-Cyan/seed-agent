import httpx
import pytest
import respx

from seed_agent.media_import.subtitles.http import Transport
from seed_agent.media_import.subtitles.provider import ProviderError


@respx.mock
def test_transport_auth_stays_at_fixed_origin_and_never_query():
    transport = Transport(
        "https://api.example.test", "fixture-secret", payload_hosts={"dl.example.test"}
    )
    api = respx.get("https://api.example.test/search").mock(
        return_value=httpx.Response(200, json={})
    )
    cdn = respx.get("https://dl.example.test/a.zip").mock(
        return_value=httpx.Response(200, content=b"zip")
    )
    assert transport.get("/search") == {}
    assert transport.payload("https://dl.example.test/a.zip", authenticate=True) == b"zip"
    assert api.calls[0].request.headers["Authorization"] == "Bearer fixture-secret"
    assert "Authorization" not in cdn.calls[0].request.headers
    assert cdn.calls[0].request.headers["X-API-Key"] == "fixture-secret"
    assert all("fixture-secret" not in str(c.request.url) for c in respx.calls)


@respx.mock
def test_transport_redirect_rejects_external_host_without_request():
    transport = Transport(
        "https://api.example.test", "fixture-secret", payload_hosts={"dl.example.test"}
    )
    respx.get("https://dl.example.test/a.zip").mock(
        return_value=httpx.Response(302, headers={"Location": "https://evil.test/steal"})
    )
    with pytest.raises(ProviderError) as error:
        transport.payload("https://dl.example.test/a.zip", authenticate=True)
    assert error.value.payload_attempted
    assert len(respx.calls) == 1


@respx.mock
def test_transport_pre_request_invalid_destination_has_no_attempt():
    transport = Transport("https://api.example.test", "fixture-secret", payload_hosts=set())
    with pytest.raises(ProviderError) as error:
        transport.payload("http://evil.test/subtitle")
    assert not error.value.payload_attempted
    assert len(respx.calls) == 0


@respx.mock
def test_transport_assrt_rate_error_body_reaches_adapter():
    transport = Transport("https://api.example.test", "fixture-secret", payload_hosts=set())
    respx.get("https://api.example.test/search").mock(
        return_value=httpx.Response(500, json={"status": 30900})
    )
    assert transport.get("/search") == {"status": 30900}


@respx.mock
def test_pacing_failure_does_not_reserve_download_allowance():
    transport = Transport("https://api.example.test", "fixture", payload_hosts={"dl.example.test"})
    reserved = []

    def paused():
        raise ProviderError("rate_limited", 30, payload_attempted=False)

    transport.pacer = paused
    with pytest.raises(ProviderError):
        transport.payload(
            "https://dl.example.test/a.zip", before_request=lambda: reserved.append(True)
        )
    assert not reserved and not respx.calls


@respx.mock
def test_redirect_to_plaintext_still_counts_existing_payload_attempt():
    transport = Transport("https://api.example.test", "fixture", payload_hosts={"dl.example.test"})
    reserved = []
    respx.get("https://dl.example.test/a.zip").mock(
        return_value=httpx.Response(302, headers={"location": "http://dl.example.test/a.zip"})
    )
    with pytest.raises(ProviderError) as error:
        transport.payload(
            "https://dl.example.test/a.zip", before_request=lambda: reserved.append(True)
        )
    assert error.value.payload_attempted
    assert reserved == [True]
    assert len(respx.calls) == 1
