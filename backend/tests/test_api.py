from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CSV = "\n".join(
    ["Date,Description,Amount"]
    + [f"2026-0{m}-15,NETFLIX.COM,-15.49" for m in range(1, 7)]
    + ["2026-03-02,COFFEE,-4.50"]
)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_analyze_upload():
    res = client.post("/api/analyze", files={"file": ("bank.csv", CSV, "text/csv")})
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["transactions_analyzed"] == 7
    assert body["summary"]["subscriptions_found"] == 1
    assert body["summary"]["active_monthly_total"] == 15.49
    assert body["subscriptions"][0]["display_name"] == "Netflix"
    assert body["subscriptions"][0]["next_expected"] == "2026-07-15"


def test_analyze_bad_csv_returns_422():
    res = client.post("/api/analyze", files={"file": ("bad.csv", "a,b\n1,2", "text/csv")})
    assert res.status_code == 422
    assert "Missing required column" in res.json()["detail"]


def test_analyze_non_utf8_returns_422():
    res = client.post("/api/analyze", files={"file": ("bad.csv", b"\xff\xfe\x00", "text/csv")})
    assert res.status_code == 422


def test_sample_endpoint_finds_known_subscriptions():
    body = client.get("/api/sample").json()
    names = {s["merchant"] for s in body["subscriptions"]}
    assert {"netflix", "spotify usa", "amazon prime", "planet fitness"} <= names
    assert "payroll deposit" not in names
    adobe = next(s for s in body["subscriptions"] if s["merchant"] == "adobe creative")
    assert adobe["likely_cancelled"] is True
    netflix = next(s for s in body["subscriptions"] if s["merchant"] == "netflix")
    assert netflix["price_changed"] is True
