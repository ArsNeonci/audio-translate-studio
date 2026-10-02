"""Run against the isolated acceptance server, including real HTTP lock bypass attempts."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rules import ReplacementRules, LOCK_MESSAGE
from storage import file_digest


def request(base, path, method="GET", body=None, headers=None):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = Request(base + path, data=payload, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        response = urlopen(req, timeout=30)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers, response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:3001")
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    service = ReplacementRules(args.data / "config")
    original = service.read()
    job_id = (args.data / "current-job.txt").read_text().strip()
    job = args.data / "jobs" / job_id
    original_vi = file_digest(job / "transcript.vi.jsonl")
    def call(path, method="GET", body=None, expected=200):
        status, headers, data = request(args.base, path, method, body)
        assert status == expected, (path, status, data[:300])
        return json.loads(data)
    call("/api/rules")
    added = call("/api/rules", "POST", {"source": "HTTP acceptance phrase", "replacement": "Kiểm thử"})["rules"][-1]
    try:
        rules = call("/api/rules/" + added["id"], "PUT", {"source": added["source"], "replacement": "Đã sửa"})["rules"]
        assert rules[-1]["replacement"] == "Đã sửa"
        assert service.read() == rules
        with service.locked():
            assert call("/api/rules")["locked"] is True
            for method, path in [("POST", "/api/rules"), ("PUT", "/api/rules/" + added["id"]), ("DELETE", "/api/rules/" + added["id"])]:
                result = call(path, method, {"source": "bypass", "replacement": "x", "action": "list"}, expected=409)
                assert result["error"] == LOCK_MESSAGE
        assert call("/api/rules")["locked"] is False
    finally:
        call("/api/rules/" + added["id"], "DELETE")
    assert service.read() == original
    state = call(f"/api/jobs/{job_id}")["job"]
    assert state["status"] == "COMPLETED", state
    assert all(state["artifacts"].values())
    assert call(f"/api/jobs/{job_id}")["job"]["stages"] == state["stages"]
    for kind in ("zh", "vi", "moderated"):
        status, headers, content = request(args.base, f"/api/jobs/{job_id}/artifacts/{kind}?format=jsonl&download=1")
        assert status == 200 and "attachment" in headers["Content-Disposition"]
        assert len(content.decode("utf-8").splitlines()) == 2
    status, headers, body = request(args.base, f"/api/jobs/{job_id}/artifacts/voice", headers={"Range": "bytes=0-43"})
    assert status == 206 and len(body) == 44 and headers["Content-Type"] == "audio/wav"
    with (job / "voice.vi.wav").open("rb") as handle:
        assert body == handle.read(44)
    assert request(args.base, f"/api/jobs/{job_id}/artifacts/voice", headers={"Range": "bytes=999999999999-"})[0] == 416
    assert request(args.base, "/")[0] == 200
    assert file_digest(job / "transcript.vi.jsonl") == original_vi
    print("HTTP ACCEPTANCE OK: CRUD, persistence, cross-process 409 lock, unchanged transcripts, artifacts, audio range/416, refresh state")


if __name__ == "__main__":
    main()
